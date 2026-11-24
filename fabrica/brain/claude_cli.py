"""Cerebro Claude: usa o Claude Code (CLI) em modo headless, sem ferramentas, so respondendo JSON.

Comando (prompt via STDIN, cwd = paths.STATE para nao puxar CLAUDE.md de projeto):
    claude -p --output-format json --tools "" --permission-prompts none --no-session-persistence
           --disable-slash-commands --strict-mcp-config --system-prompt "<...>" [--model X] [--effort Y]
"""
from __future__ import annotations

import json
import os
import re
import subprocess

from .. import log, paths, tools
from ..models import Candidate, Transcript, Trend
from ..util import fmt_duration, run_cmd
from . import prompts
from .base import (BrainUnavailable, LLMBrain, cache_get, cache_set, extract_json, list_from_json,
                   safe_text, time_chunks, _cfg_get)

logger = log.get(__name__)

LOGIN_MSG = "Claude Code não está logado. Rode: cortex login claude (e digite /login)."
LIMIT_MSG = "Claude atingiu o limite de uso agora; tento de novo mais tarde."
MAX_CHARS = 120_000          # acima disso a transcricao e dividida em blocos

_LOGIN_PAT = re.compile(r"not logged in|please run /login|run /login|invalid api key|oauth token (?:has )?expired|"
                        r"authentication_error|authentication failed|unauthori[sz]ed|\b401\b", re.I)
_LIMIT_PAT = re.compile(r"usage limit|rate limit|limit reached|credit balance|quota|\b429\b|overloaded", re.I)
_HOST_PREFIXES = ("CLAUDECODE", "CLAUDE_CODE_", "CLAUDE_AGENT_SDK", "CLAUDE_PID", "CLAUDE_EFFORT",
                  "CLAUDE_PREVIEW", "AI_AGENT", "BAGGAGE")


def clean_env() -> dict:
    """Ambiente para o CLI filho. Se estivermos dentro de outra sessao do Claude Code (ex.: testes rodando
    num agente), remove as variaveis da sessao hospedeira para o filho se comportar como no CMD do usuario."""
    env = dict(os.environ)
    nested = "CLAUDECODE" in env or "CLAUDE_CODE_ENTRYPOINT" in env
    if nested:
        for k in list(env):
            if k.startswith(_HOST_PREFIXES):
                env.pop(k, None)
        env.pop("ANTHROPIC_BASE_URL", None)       # proxy do app hospedeiro
    env.setdefault("DISABLE_AUTOUPDATER", "1")
    return env


def build_args(exe: str, system: str, model: str = "", effort: str = "", minimal: bool = False) -> list[str]:
    if minimal:  # versoes antigas do CLI (sem --tools / --permission-prompts)
        args = [exe, "-p", "--output-format", "json",
                "--disallowedTools", "Bash,Edit,Write,MultiEdit,NotebookEdit,WebFetch,WebSearch,Task,Read,Glob,Grep",
                "--append-system-prompt", system]
    else:
        args = [exe, "-p", "--output-format", "json", "--tools", "", "--permission-prompts", "none",
                "--no-session-persistence", "--disable-slash-commands", "--strict-mcp-config",
                "--system-prompt", system]
    if model:
        args += ["--model", model]
    if effort and not minimal:
        args += ["--effort", effort]
    return args


def parse_cli_output(stdout: str, stderr: str = "") -> str:
    """Interpreta a saida de `claude -p --output-format json` e devolve o texto da resposta.
    Levanta BrainUnavailable (login/limite) ou RuntimeError."""
    data = None
    out = (stdout or "").strip()
    if out:
        try:
            data = json.loads(out)
        except json.JSONDecodeError:
            for line in reversed(out.splitlines()):
                line = line.strip()
                if line.startswith("{") and '"result"' in line:
                    try:
                        data = json.loads(line)
                        break
                    except json.JSONDecodeError:
                        continue
    if isinstance(data, list):  # stream-json acumulado
        data = next((d for d in reversed(data) if isinstance(d, dict) and d.get("type") == "result"), None)
    if not isinstance(data, dict):
        text = (out + "\n" + (stderr or "")).strip()
        if _LOGIN_PAT.search(text):
            raise BrainUnavailable(LOGIN_MSG)
        if _LIMIT_PAT.search(text):
            raise BrainUnavailable(LIMIT_MSG)
        raise RuntimeError(f"saída inesperada do Claude Code: {safe_text(text, 300)!r}")
    result = data.get("result")
    if data.get("is_error"):
        msg = str(result or data.get("error") or data.get("terminal_reason") or "")
        if _LOGIN_PAT.search(msg):
            raise BrainUnavailable(LOGIN_MSG)
        if _LIMIT_PAT.search(msg):
            raise BrainUnavailable(LIMIT_MSG)
        raise RuntimeError(f"Claude Code respondeu com erro: {safe_text(msg, 300)}")
    if data.get("structured_output") is not None:
        return json.dumps(data["structured_output"], ensure_ascii=False)
    if not result:
        raise RuntimeError("Claude Code devolveu resposta vazia")
    return str(result)


class ClaudeBrain(LLMBrain):
    name = "claude"

    def __init__(self, cfg=None):
        super().__init__(cfg)
        self.exe = tools.claude()
        self.model = str(_cfg_get(cfg, "cerebro.claude_modelo", "") or "").strip()
        self.effort = str(_cfg_get(cfg, "cerebro.claude_esforco", "") or "").strip()
        self.timeout = float(_cfg_get(cfg, "cerebro.timeout_s", 300) or 300)
        self._minimal = False

    # ----- disponibilidade
    def available(self, refresh: bool = False) -> bool:
        if not refresh:
            c = cache_get("claude")
            if c is not None:
                self._status = c["msg"]
                return bool(c["ok"])
        ok, msg = self._check()
        self._status = msg
        cache_set("claude", ok, msg)
        return ok

    def _check(self) -> tuple[bool, str]:
        if not self.exe:
            return False, "Claude Code não encontrado neste PC."
        paths.STATE.mkdir(parents=True, exist_ok=True)
        ok_msg = "Cérebro: Claude (Claude Code)" + (f", modelo {self.model}" if self.model else "") + "."
        try:
            proc = run_cmd([self.exe, "auth", "status"], timeout=45, cwd=paths.STATE, env=clean_env())
            data = json.loads((proc.stdout or "").strip() or "{}")
            if data.get("loggedIn"):
                return True, ok_msg
            if not os.environ.get("ANTHROPIC_API_KEY"):
                return False, LOGIN_MSG
        except Exception as e:  # versao sem "auth status": testa com uma pergunta minima
            logger.debug("claude auth status falhou: %s", e)
        try:
            self._run("Responda apenas: ok", "Responda só com a palavra ok.", timeout=90)
            return True, ok_msg
        except BrainUnavailable as e:
            return False, str(e)
        except Exception as e:
            return False, f"Claude Code não respondeu ({str(e)[:120]})."

    # ----- chamada
    def _run(self, prompt: str, system: str, timeout: float | None = None, images: list | None = None) -> str:
        if not self.exe:
            raise BrainUnavailable("Claude Code não encontrado neste PC.")
        from .. import uso_ia

        if not uso_ia.pode_claude(self.cfg):  # teto diario: poupa a cota da assinatura do dono
            raise BrainUnavailable(f"Teto diário do Claude atingido ({uso_ia.teto_claude(self.cfg)} chamadas); "
                                   "usando a IA local até amanhã.")
        paths.STATE.mkdir(parents=True, exist_ok=True)
        timeout = timeout or self.timeout
        for attempt in range(2):
            args = build_args(self.exe, system, self.model, self.effort, minimal=self._minimal)
            if images:      # imagens vao dentro da mensagem (stream-json); a resposta vem em linhas
                from ..revisao import json_mensagem

                i = args.index("--output-format")
                args[i + 1] = "stream-json"
                args += ["--input-format", "stream-json", "--verbose"]
            import time as _t

            t0 = _t.time()
            try:
                proc = run_cmd(args, timeout=timeout, cwd=paths.STATE, input_text=json_mensagem(prompt, images) if images else prompt, env=clean_env())
            except subprocess.TimeoutExpired:
                raise RuntimeError(f"Claude Code demorou mais de {int(timeout)} s") from None
            uso_ia.registrar("claude", "chamada", _t.time() - t0)
            err = proc.stderr or ""
            if not self._minimal and re.search(r"unknown option|unknown argument|error: option", err, re.I):
                logger.info("Claude Code antigo: usando opções mínimas")
                self._minimal = True
                continue
            try:
                return parse_cli_output(proc.stdout, err)
            except BrainUnavailable as e:
                cache_set("claude", False, str(e), ttl=1800 if str(e) == LIMIT_MSG else None)
                self._status = str(e)
                raise
        raise RuntimeError("Claude Code não aceitou as opções de linha de comando")

    # ----- tarefas
    def _pick_raw(self, video: Candidate, transcript: Transcript, cfg, limit: int, sig, sig_summary: str) -> list[dict]:
        auto = str(_cfg_get(cfg, "execucao.cortes_por_video", "auto")).strip().lower() == "auto"
        full = transcript.text_with_timestamps()
        lim = int(_cfg_get(self.cfg, "cerebro.claude_max_caracteres", 60_000) or 60_000)
        if len(full) > lim:     # video longo: so as regioes com sinal (publico, chat, volume, palavras). Um pedido por video
            foco = self._focus(video, transcript, cfg, lim)
            if foco:
                logger.info("video longo: mando %d mil caracteres das melhores regioes (de %d mil)", len(foco) // 1000, len(full) // 1000)
                full = foco
        if len(full) <= MAX_CHARS:
            chunks = [(full, "")]
        else:
            parts = time_chunks(transcript, int(MAX_CHARS * 0.85))
            chunks = []
            for i, ch in enumerate(parts, 1):
                note = (f"(bloco {i}/{len(parts)} do vídeo: {fmt_duration(ch.segments[0].start)} a "
                        f"{fmt_duration(ch.segments[-1].end)}; escolha só cortes deste bloco)")
                chunks.append((ch.text_with_timestamps(), note))
        raws: list[dict] = []
        for text, note in chunks:
            prompt = prompts.clips_prompt(video, text, sig_summary, cfg, limit, chunk_note=note, auto=auto)
            res = self._run(prompt, prompts.SYSTEM_CLIPS)
            items = list_from_json(extract_json(res), ("cortes", "clips", "cuts"))
            logger.debug("claude: %d cortes sugeridos (%s)", len(items), note or "vídeo inteiro")
            raws.extend(items)
        return raws

    def _focus(self, video: Candidate, transcript: Transcript, cfg, lim: int) -> str:
        """Texto das regioes mais quentes, com contexto em volta, na ordem do video."""
        try:
            wins = sorted(self._heuristic().candidate_windows(video, transcript, cfg, max_clips=24), key=lambda w: -w["score"])
        except Exception as e:
            logger.debug("foco: %s", safe_text(e))
            return ""
        spans: list[list[float]] = []
        total = 0
        for w in wins:
            a, b = max(0.0, w["start"] - 100), w["end"] + 120
            size = len(transcript.slice(a, b, rebase=False).text_with_timestamps())
            if total + size > lim:
                continue
            total += size
            spans.append([a, b])
        spans.sort()
        merged: list[list[float]] = []
        for a, b in spans:
            if merged and a <= merged[-1][1] + 20:
                merged[-1][1] = max(merged[-1][1], b)
            else:
                merged.append([a, b])
        parts = [transcript.slice(a, b, rebase=False).text_with_timestamps() for a, b in merged]
        return "\n[... trecho do meio sem destaque ...]\n".join(parts) if len(merged) >= 2 else ""

    def _rank_raw(self, trends: list[Trend], cfg, limit: int) -> list[dict]:
        prompt = prompts.trends_prompt(trends[:80], cfg, limit)
        res = self._run(prompt, prompts.SYSTEM_TRENDS)
        return list_from_json(extract_json(res), ("temas", "trends", "assuntos"))
