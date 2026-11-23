"""Cerebro Ollama (IA local). Usa /api/chat com saida estruturada (format = JSON schema).

Contexto pequeno (num_ctx 8192): a transcricao e dividida em janelas de ~7 min; cada janela gera
candidatos e, se sobrar candidato, um passo final ranqueia e da titulo aos melhores.
"""
from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path
from urllib.parse import urlparse

import requests

from .. import log, paths, tools
from ..models import Candidate, Transcript, Trend
from ..util import fmt_duration
from . import prompts
from .base import (BrainUnavailable, LLMBrain, cache_get, cache_set, extract_json, list_from_json,
                   safe_text, time_chunks, _cfg_get)

logger = log.get(__name__)

PID_FILE = paths.STATE / "ollama_serve.pid"
DETACHED_PROCESS = 0x00000008
CREATE_NEW_PROCESS_GROUP = 0x00000200
CREATE_NO_WINDOW = 0x08000000
EMBED_HINTS = ("bge", "embed", "nomic", "minilm", "e5-", "gte-")


def _model_matches(wanted: str, have: str) -> bool:
    w, h = wanted.strip().lower(), have.strip().lower()
    if w == h:
        return True
    if ":" not in w and h == f"{w}:latest":
        return True
    return False


class OllamaBrain(LLMBrain):
    name = "ollama"

    def __init__(self, cfg=None):
        super().__init__(cfg)
        self.url = str(_cfg_get(cfg, "cerebro.ollama_url", "http://127.0.0.1:11434")).rstrip("/")
        self.model = str(_cfg_get(cfg, "cerebro.ollama_modelo", "qwen3:4b") or "qwen3:4b").strip()
        # IA local roda na CPU: precisa de mais folga que o Claude (prompt grande leva minutos)
        self.timeout = max(float(_cfg_get(cfg, "cerebro.timeout_s", 300) or 300),
                           float(_cfg_get(cfg, "cerebro.ollama_timeout_s", 600) or 600))
        self.num_ctx = int(_cfg_get(cfg, "cerebro.ollama_num_ctx", 8192) or 8192)
        self.temperature = float(_cfg_get(cfg, "cerebro.ollama_temperatura", 0.4))
        self.window_s = float(_cfg_get(cfg, "cerebro.ollama_janela_min", 7)) * 60
        self.max_windows = int(_cfg_get(cfg, "cerebro.ollama_max_janelas", 8) or 8)
        # caracteres de transcricao por janela (~3,5 caracteres/token, sobra espaco p/ instrucoes e resposta)
        self.window_chars = max(4000, int((self.num_ctx - 3000) * 3.2))
        # limita a CPU: evita saturar a CPU
        self.num_thread = int(_cfg_get(cfg, "cerebro.ollama_threads", 6) or 6)
        self._think_ok = True

    # ----- servidor
    def server_up(self, timeout: float = 2.0) -> bool:
        try:
            return requests.get(f"{self.url}/api/tags", timeout=timeout).ok
        except requests.RequestException:
            return False

    def list_models(self) -> list[str]:
        r = requests.get(f"{self.url}/api/tags", timeout=5)
        r.raise_for_status()
        return [m.get("name") or m.get("model") for m in r.json().get("models", [])]

    def start_server(self, wait_s: float = 15.0) -> bool:
        """Inicia `ollama serve` em segundo plano (sem janela). Retorna True se respondeu a tempo."""
        exe = tools.ollama()
        if not exe:
            return False
        env = dict(os.environ)
        u = urlparse(self.url)
        if u.hostname and u.port:
            env.setdefault("OLLAMA_HOST", f"{u.hostname}:{u.port}")
        try:
            proc = subprocess.Popen([exe, "serve"], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL, env=env, close_fds=True,
                                    creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW)
            try:
                PID_FILE.parent.mkdir(parents=True, exist_ok=True)
                PID_FILE.write_text(str(proc.pid), encoding="utf-8")
            except OSError:
                pass
        except OSError as e:
            logger.debug("nao consegui iniciar o ollama: %s", e)
            return False
        t0 = time.time()
        while time.time() - t0 < wait_s:
            if self.server_up(1.0):
                return True
            time.sleep(0.5)
        return self.server_up(2.0)

    @staticmethod
    def stop_started_server() -> bool:
        """Encerra o `ollama serve` que NOS iniciamos (usado nos testes)."""
        try:
            pid = int(PID_FILE.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            return False
        try:
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, creationflags=CREATE_NO_WINDOW)
        finally:
            try:
                PID_FILE.unlink()
            except OSError:
                pass
        return True

    # ----- disponibilidade
    def available(self, refresh: bool = False) -> bool:
        key = f"ollama:{self.model}"
        if not refresh:
            c = cache_get(key)
            if c is not None and not c["ok"]:
                self._status = c["msg"]
                return False
        ok, msg = self._check()
        self._status = msg
        cache_set(key, ok, msg)
        return ok

    def model_on_disk(self) -> bool | None:
        """Olha o manifesto do modelo no disco (sem precisar do servidor). None = nao da para saber."""
        root = Path(os.environ.get("OLLAMA_MODELS") or Path.home() / ".ollama" / "models") / "manifests"
        if not root.is_dir():
            return None
        name, _, tag = self.model.partition(":")
        tag = tag or "latest"
        parts = name.split("/")
        if len(parts) == 1:
            parts = ["registry.ollama.ai", "library", parts[0]]
        elif len(parts) == 2:
            parts = ["registry.ollama.ai"] + parts
        return (root.joinpath(*parts) / tag).is_file()

    def _check(self) -> tuple[bool, str]:
        if not self.server_up():
            if not tools.ollama():
                return False, "Ollama não está instalado."
            if self.model_on_disk() is False:     # nao liga o servidor a toa
                return False, (f"Modelo '{self.model}' não está baixado no Ollama. "
                               f"Rode no CMD: ollama pull {self.model}")
            logger.info("Iniciando o Ollama em segundo plano...")
            if not self.start_server():
                return False, f"Ollama não respondeu em {self.url} (tentei iniciar `ollama serve`)."
        try:
            models = self.list_models()
        except Exception as e:
            return False, f"Ollama respondeu com erro ({e})."
        if not any(_model_matches(self.model, m) for m in models):
            chat = [m for m in models if not any(h in m.lower() for h in EMBED_HINTS)]
            extra = f" Modelos instalados: {', '.join(chat)}." if chat else ""
            return False, (f"Modelo '{self.model}' não está baixado no Ollama. "
                           f"Rode no CMD: ollama pull {self.model}.{extra}")
        return True, f"Cérebro: Ollama local ({self.model})."

    # ----- chamada
    def chat(self, user: str, system: str, schema: dict | None = None, timeout: float | None = None,
             num_predict: int = 2048) -> str:
        body = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "stream": False,
            "format": schema or "json",
            "options": {"num_ctx": self.num_ctx, "temperature": self.temperature, "num_predict": num_predict,
                        "num_thread": self.num_thread},
            "keep_alive": "10m",
        }
        if self._think_ok:
            body["think"] = False
        try:
            r = requests.post(f"{self.url}/api/chat", json=body, timeout=timeout or self.timeout)
            if r.status_code == 400 and "think" in r.text.lower() and "think" in body:
                self._think_ok = False
                body.pop("think")
                r = requests.post(f"{self.url}/api/chat", json=body, timeout=timeout or self.timeout)
        except requests.ConnectionError as e:
            raise BrainUnavailable(f"Ollama caiu ou não está rodando ({e.__class__.__name__}).") from None
        except requests.Timeout:
            raise RuntimeError(f"Ollama demorou mais de {int(timeout or self.timeout)} s") from None
        if r.status_code == 404:
            raise BrainUnavailable(f"Modelo '{self.model}' não encontrado no Ollama (ollama pull {self.model}).")
        if not r.ok:
            raise RuntimeError(f"Ollama HTTP {r.status_code}: {r.text[:200]}")
        data = r.json()
        try:
            from .. import uso_ia

            uso_ia.registrar("ollama", "chamada", float(data.get("total_duration") or 0) / 1e9)
        except Exception:
            pass
        content = (data.get("message") or {}).get("content") or ""
        if data.get("done_reason") == "length":
            logger.debug("ollama: resposta cortada pelo limite de tokens (tentando aproveitar)")
        return content

    # ----- tarefas
    def _windows(self, transcript: Transcript, sig) -> list[Transcript]:
        wins = time_chunks(transcript, self.window_chars, overlap_s=40, max_s=self.window_s)
        if len(wins) <= self.max_windows:
            return wins
        # muitas janelas (live longa): fica com as mais "quentes" pelos sinais
        def heat(w: Transcript) -> float:
            if sig is not None and sig.curve:
                a, b = int(w.segments[0].start), int(w.segments[-1].end)
                seg = sig.curve[a: b + 1]
                if seg:
                    srt = sorted(seg, reverse=True)
                    return sum(srt[: max(1, len(srt) // 5)]) / max(1, len(srt) // 5)
            return sum(t.text.count("?") + t.text.count("!") for t in w.segments) / max(1, len(w.segments))
        best = sorted(wins, key=heat, reverse=True)[: self.max_windows]
        return sorted(best, key=lambda w: w.segments[0].start)

    def _pick_raw(self, video: Candidate, transcript: Transcript, cfg, limit: int, sig, sig_summary: str) -> list[dict]:
        from .. import signals as sigmod
        from .base import coerce_raw

        auto = str(_cfg_get(cfg, "execucao.cortes_por_video", "auto")).strip().lower() == "auto"
        wins = self._windows(transcript, sig)
        moments = sigmod.hot_moments(sig, top=30) if sig is not None else []
        cands: list[dict] = []
        for i, w in enumerate(wins, 1):
            a, b = w.segments[0].start, w.segments[-1].end
            if len(wins) > 1:
                note = (f"(trecho {i}/{len(wins)} do vídeo: {fmt_duration(a)} a {fmt_duration(b)}; "
                        "escolha só cortes deste trecho)")
                ms = [m for m in moments if m.end >= a and m.start <= b]
                summ = sigmod.summarize_for_prompt(sig, moments=ms) if sig is not None else ""
                wl = min(limit, 3)
            else:
                note, summ, wl = "", sig_summary, limit
            prompt = prompts.clips_prompt(video, w.text_with_timestamps(), summ, cfg, wl, chunk_note=note, auto=auto)
            try:
                res = self.chat(prompt, prompts.SYSTEM_CLIPS, prompts.CLIPS_SCHEMA)
                items = list_from_json(extract_json(res), ("cortes", "clips", "cuts"))
            except BrainUnavailable:
                raise
            except Exception as e:
                logger.warning("ollama: janela %d/%d falhou (%s)", i, len(wins), safe_text(e))
                continue
            for it in items:
                c = coerce_raw(it)
                if not c:
                    continue
                # modelos pequenos as vezes devolvem tempo relativo a janela
                if not (a - 10 <= c["start"] <= b + 10) and 0 <= c["start"] <= (b - a) + 10 and a > 30:
                    c["start"] += a
                    c["end"] += a
                    for k in ("teaser_start", "teaser_end"):
                        if c.get(k) is not None and c[k] <= (b - a) + 10:
                            c[k] += a
                if not (a - 10 <= c["start"] <= b + 10) or c["end"] <= c["start"]:
                    continue
                c["excerpt"] = transcript.slice(c["start"], c["end"], rebase=False).text[:400]
                cands.append(c)
        if len(wins) > 1 and len(cands) > limit:
            try:
                cands = self._final_rank(video, cands, limit, cfg)
            except Exception as e:
                logger.warning("ollama: passo final falhou (%s); usando notas das janelas", safe_text(e))
        return cands

    def _final_rank(self, video: Candidate, cands: list[dict], limit: int, cfg) -> list[dict]:
        cands = sorted(cands, key=lambda c: -c["score"])[:20]
        prompt = prompts.rank_clips_prompt(video, cands, limit, cfg)
        res = self.chat(prompt, prompts.SYSTEM_CLIPS, prompts.RANK_SCHEMA)
        chosen = list_from_json(extract_json(res), ("cortes", "clips"))
        out: list[dict] = []
        for r in chosen:
            try:
                idx = int(r.get("indice"))
            except (TypeError, ValueError):
                continue
            if not 1 <= idx <= len(cands):
                continue
            c = dict(cands[idx - 1])
            for src, dst in (("titulo", "title"), ("gancho", "hook"), ("descricao", "description"),
                             ("hashtags", "hashtags"), ("motivo", "reason"), ("categoria", "category"),
                             ("teaser_texto", "teaser_text")):
                if r.get(src):
                    c[dst] = r[src]
            try:
                c["score"] = float(r.get("pontuacao", c["score"]))
            except (TypeError, ValueError):
                pass
            out.append(c)
        return out or cands

    def _rank_raw(self, trends: list[Trend], cfg, limit: int) -> list[dict]:
        prompt = prompts.trends_prompt(trends[:40], cfg, limit)
        res = self.chat(prompt, prompts.SYSTEM_TRENDS, prompts.TRENDS_SCHEMA)
        return list_from_json(extract_json(res), ("temas", "trends", "assuntos"))
