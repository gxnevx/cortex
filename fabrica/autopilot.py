"""PILOTO AUTOMATICO 24/7 do CORTEX.

Dois trabalhadores em paralelo + painel ao vivo no terminal:
  - PRODUTOR: quando a fila de cortes prontos fica baixa (ou os assuntos ficam velhos), roda uma rodada
    completa (tendencias -> videos -> cortes -> edicao) e coloca os cortes na fila.
  - PUBLICADOR: publica um corte por vez, espacado ao longo do dia (mais vezes no horario nobre),
    respeitando o limite diario de cada rede, a janela de horario e as series (Parte 1 antes da 2).
Erros nunca derrubam o piloto: ele registra, espera um pouco e tenta de novo.
"""
from __future__ import annotations

import collections
import contextlib
import ctypes
import json
import logging
import os
import random
import threading
import time
import traceback
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from rich.console import Group
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from . import andamento, db, log, notify, paths, ui
from .config import Config, load_config
from .util import fmt_duration

_log = log.get("autopiloto")
HEARTBEAT = paths.STATE / "autopiloto.json"
STOP_FILE = paths.STATE / "parar_piloto"
SPIN = "|/-\\"


# ================================================================ log ao vivo
class LiveLogHandler(logging.Handler):
    def __init__(self, maxlen: int = 300):
        super().__init__(logging.INFO)
        self.lines: collections.deque = collections.deque(maxlen=maxlen)

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = ui.term(record.getMessage())
            if record.exc_info:
                msg += " (erro detalhado no arquivo de log)"
            self.lines.append((datetime.fromtimestamp(record.created).strftime("%H:%M:%S"), record.levelno,
                               record.name.replace("fabrica.", ""), msg))
        except Exception:
            pass


# ================================================================ estado
@dataclass
class State:
    started: float = field(default_factory=time.time)
    prod_activity: str = "aguardando"
    prod_since: float = field(default_factory=time.time)
    pub_activity: str = "aguardando"
    pub_since: float = field(default_factory=time.time)
    next_production: float = 0.0
    next_post: float = 0.0
    cycles: int = 0
    cycles_ok: int = 0
    last_cycle: str = "-"
    errors: int = 0
    brain: str = "?"
    alerts: list = field(default_factory=list)          # mensagens para o usuario
    paused_platforms: dict = field(default_factory=dict)  # plataforma -> ate quando
    logins: dict = field(default_factory=dict)
    logins_checked: float = 0.0
    tested_ids: set = field(default_factory=set)        # modo teste: nao repete o mesmo corte
    watch_activity: str = "iniciando"                    # vigia da via rapida
    user_busy: bool = False                              # voce esta usando o PC agora
    busy_since: float = 0.0
    metrics_activity: str = "iniciando"                  # leitura de views

    def set_prod(self, msg: str) -> None:
        self.prod_activity, self.prod_since = ui.term(msg), time.time()
        _log.info("[produtor] %s", msg)

    def set_pub(self, msg: str) -> None:
        self.pub_activity, self.pub_since = ui.term(msg), time.time()
        _log.info("[publicador] %s", msg)

    def alert(self, msg: str) -> None:
        if msg not in self.alerts:
            self.alerts.append(ui.term(msg))
            self.alerts[:] = self.alerts[-4:]
            _log.warning("ATENCAO: %s", msg)


# ================================================================ reporter
class AutopilotReporter(ui.Reporter):
    """Reporter da esteira que, em vez de imprimir, atualiza o painel."""

    def __init__(self, state: State):
        super().__init__(quiet=True)
        self.state = state

    def stage(self, n, total, title):
        self.state.set_prod(f"[{n}/{total}] {title}")

    def working(self, msg):
        import contextlib

        @contextlib.contextmanager
        def _cm():
            prev = self.state.prod_activity
            self.state.set_prod(msg)
            try:
                yield
            finally:
                self.state.prod_activity = prev

        return _cm()


# ================================================================ utilidades
def keep_awake(on: bool) -> None:
    """Impede o Windows de suspender enquanto o piloto roda (so durante o processo)."""
    try:
        ES_CONTINUOUS, ES_SYSTEM_REQUIRED = 0x80000000, 0x00000001
        ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS | (ES_SYSTEM_REQUIRED if on else 0))
    except Exception:
        pass


def user_idle_s() -> float:
    """Segundos desde o ultimo uso de mouse/teclado (Windows)."""
    try:
        class LASTINPUTINFO(ctypes.Structure):
            _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]

        lii = LASTINPUTINFO()
        lii.cbSize = ctypes.sizeof(LASTINPUTINFO)
        if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(lii)):
            return 1e9
        return max(0.0, (ctypes.windll.kernel32.GetTickCount() - lii.dwTime) / 1000.0)
    except Exception:
        return 1e9


def set_low_priority() -> None:
    """Prioridade 'abaixo do normal' para o CORTEX e tudo que ele abrir (ffmpeg, Whisper, Chrome):
    o Windows da preferencia para o que voce estiver usando. Tambem rebaixa o Ollama."""
    try:
        BELOW_NORMAL = 0x00004000
        ctypes.windll.kernel32.SetPriorityClass(ctypes.windll.kernel32.GetCurrentProcess(), BELOW_NORMAL)
    except Exception:
        pass
    try:
        from .util import run_cmd

        run_cmd(["powershell", "-NoProfile", "-NonInteractive", "-Command",
                 "Get-Process ollama* -ErrorAction SilentlyContinue | ForEach-Object { $_.PriorityClass = 'BelowNormal' }"],
                timeout=20)
    except Exception:
        pass


def capacity(cfg: Config) -> int:
    """Quantos cortes da para postar hoje (o mesmo corte vai para todas as redes)."""
    from . import policy

    plats = cfg.get("publicacao.plataformas", ["youtube", "tiktok"]) or []
    return max([policy.effective_limit(p, cfg) for p in plats] or [0])


def target_queue(cfg: Config) -> int:
    """Tamanho ideal da fila: capacidade de posts x estoque (produz mais e publica so os de nota maior)."""
    cap = capacity(cfg)
    estoque = float(cfg.get("autopiloto.estoque_dias", 2.5))
    max_q = int(cfg.get("autopiloto.fila_maxima", 12))
    if cap <= 0:  # aquecimento da conta (dias sem post): so um estoque pequeno para quando liberar
        return min(max_q, int(cfg.get("autopiloto.estoque_aquecimento", 3)))
    return max(2, min(max_q, int(round(cap * estoque))))


def free_memory() -> None:
    """Libera os modelos de transcricao da RAM entre as rodadas (PC rodando 24/7)."""
    try:
        from . import transcribe

        fn = getattr(transcribe, "unload_models", None)
        if fn:
            fn()
    except Exception:
        pass
    from . import memoria

    memoria.unload_ollama()
    memoria.unload_whisper()


def _parse_hm(s: str) -> tuple[int, int]:
    h, m = s.strip().split(":")
    return int(h), int(m)


def in_window(now: datetime, start: str, end: str) -> bool:
    """Janela que pode atravessar a meia-noite (ex.: 07:30 -> 00:30)."""
    sh, sm = _parse_hm(start)
    eh, em = _parse_hm(end)
    s = now.replace(hour=sh, minute=sm, second=0, microsecond=0)
    e = now.replace(hour=eh, minute=em, second=0, microsecond=0)
    if e <= s:  # atravessa meia-noite
        return now >= s or now < e
    return s <= now < e


def minutes_until_window_end(now: datetime, start: str, end: str) -> float:
    eh, em = _parse_hm(end)
    e = now.replace(hour=eh, minute=em, second=0, microsecond=0)
    if e <= now:
        e += timedelta(days=1)
    return (e - now).total_seconds() / 60


def next_window_start(now: datetime, start: str) -> datetime:
    sh, sm = _parse_hm(start)
    s = now.replace(hour=sh, minute=sm, second=0, microsecond=0)
    if s <= now:
        s += timedelta(days=1)
    return s


def in_prime(now: datetime, ranges: list[str]) -> bool:
    for r in ranges or []:
        try:
            a, b = r.split("-")
            if in_window(now, a, b):
                return True
        except ValueError:
            continue
    return False


def queue(cfg: Config) -> list:
    """Cortes prontos esperando publicacao (respeitando o modo do piloto)."""
    from pathlib import Path

    from .pipeline import publish_order

    clips = [c for c in db.clips_by_status("aprovado") if Path(c.path).exists()]
    return publish_order(clips)


def expire_old(cfg: Config) -> int:
    """Assunto velho nao viraliza: cortes nao publicados depois de X horas saem da fila."""
    hours = float(cfg.get("autopiloto.validade_horas", 36))
    limit = time.time() - hours * 3600
    n = 0
    for r in db.conn().execute("SELECT id, created FROM clips WHERE status='renderizado'").fetchall():
        if (r["created"] or time.time()) < limit:
            if db.conn().execute("SELECT 1 FROM posts WHERE clip_id=? AND ok=1 AND dry_run=0", (r["id"],)).fetchone() \
                    and (r["created"] or 0) > limit - 7 * 86400:
                continue    # saiu em uma rede ou ficou sem confirmacao: o dono confere antes
            db.set_clip_status(r["id"], "expirado")
            n += 1
    for r in db.conn().execute("SELECT id, created, curador FROM clips WHERE status='aprovado'").fetchall():
        # aprovado pelo editor-chefe (nao pelo dono) ha mais de 5 dias e ainda nao saiu em lugar nenhum
        if r["curador"] and (r["created"] or time.time()) < time.time() - 5 * 86400 and not db.conn().execute(
                "SELECT 1 FROM posts WHERE clip_id=? AND ok=1 AND dry_run=0", (r["id"],)).fetchone():
            db.set_clip_status(r["id"], "expirado")
            n += 1
    return n


# ================================================================ piloto
class Autopilot:
    def __init__(self, dry_run: bool = False, no_publish: bool = False):
        self.cfg = load_config()
        self.dry_run = dry_run
        self.no_publish = no_publish
        self.state = State()
        self.stop = threading.Event()
        self._urgent = 0.0
        self.loghandler = LiveLogHandler()
        self._lock_file = paths.STATE / "autopiloto.lock"
        self.fast_lane: list = []                 # candidatos da via rapida (vigia), processados primeiro
        self.fast_lock = threading.Lock()

    # ------------------------------------------------------------ vigia
    def watcher(self) -> None:
        """A cada N minutos procura momentos explodindo (clipes da Twitch/Kick, video novo bombando)."""
        while not self.stop.is_set():
            cfg = self.cfg
            every = float(cfg.get("busca.via_rapida.intervalo_min", 10)) * 60
            try:  # sem vaga de post hoje: checa 3x menos (economiza rede e CPU)
                from . import policy

                plats = cfg.get("publicacao.plataformas", ["youtube", "tiktok"]) or []
                if not any(policy.effective_limit(p, cfg) - db.posts_today(p) > 0 for p in plats):
                    every *= 3
            except Exception:
                pass
            try:
                if cfg.get("busca.via_rapida.ativa", True):
                    from . import watcher as vigia

                    self.state.watch_activity = "procurando momentos explodindo..."
                    found = vigia.poll(cfg) or []
                    with self.fast_lock:
                        known = {c.id for c in self.fast_lane}
                        new = [c for c in found if c.id not in known]
                        self.fast_lane.extend(new)
                    self.state.watch_activity = (f"{datetime.now():%H:%M} | {len(new)} achado(s)"
                                                 if new else f"{datetime.now():%H:%M} | nada explodindo agora")
                    for c in new:
                        _log.info("[vigia] via rapida: %s (%s)", c.title[:70],
                                  (c.extra or {}).get("motivo_via_rapida", ""))
                else:
                    self.state.watch_activity = "desligado (config busca.via_rapida.ativa)"
            except ImportError:
                self.state.watch_activity = "indisponivel nesta versao"
                every = 3600
            except Exception as e:
                self.state.watch_activity = f"erro: {str(e)[:60]}"
                _log.error("vigia: %s\n%s", e, traceback.format_exc())
            self.stop.wait(every)

    # ---------------------------------------------------------- metricas
    def metrics_worker(self) -> None:
        """A cada 30 min le as views dos posts e checa a saude das contas."""
        while not self.stop.is_set():
            cfg = self.cfg
            try:
                from . import metrics

                if self.state.pub_activity.startswith("publicando"):
                    self.stop.wait(120)  # nao le metricas no meio de um upload
                    continue
                res = metrics.collect(cfg) or {}
                saude = res.get("saude") or {}
                ruins = [f"{p}: {n}" for p, n in saude.items() if n not in ("normal", None)]
                self.state.metrics_activity = (f"{datetime.now():%H:%M} | {res.get('lidos', 0)} leitura(s)"
                                               + (f" | ATENCAO {', '.join(ruins)}" if ruins else " | contas saudaveis"))
                for m in res.get("mensagens") or []:
                    _log.info("[metricas] %s", m)
                    if any(k in m.lower() for k in ("pausa", "aten", "views")):
                        self.state.alert(m)
                        notify.toast("CORTEX: saude da conta", m, cfg)
            except ImportError:
                self.state.metrics_activity = "indisponivel nesta versao"
            except Exception as e:
                self.state.metrics_activity = f"erro: {str(e)[:60]}"
                _log.error("metricas: %s\n%s", e, traceback.format_exc())
            self.stop.wait(float(cfg.get("autopiloto.intervalo_metricas_min", 30)) * 60)

    def _run_fast_lane(self, cfg: Config) -> bool:
        """Processa a via rapida, se houver. Devolve True se rodou algo."""
        from .pipeline import RunOptions, run

        with self.fast_lock:
            batch, self.fast_lane = self.fast_lane[:3], self.fast_lane[3:]
        if not batch:
            return False
        self.state.cycles += 1
        self.state.set_prod(f"VIA RAPIDA: {len(batch)} momento(s) explodindo")
        opts = RunOptions(trigger="via_rapida", candidates=batch, n_videos=len(batch), publish_mode="fila",
                          interactive=False, notify=False)
        summary = run(cfg, opts, AutopilotReporter(self.state))
        n = len(summary.get("clips", []))
        self.state.last_cycle = f"{datetime.now():%H:%M} | via rapida | {n} cortes | {summary.get('status')}"
        if n:
            self.state.cycles_ok += 1
            # corta a espera do publicador: corte quente deve sair logo (respeitando as regras da conta)
            self._urgent = time.time() + 1800     # momento explodindo: nao espera a janela
            self.state.next_post = min(self.state.next_post, time.time() + random.uniform(60, 300))
        self.state.set_prod(f"via rapida ok: +{n} cortes na fila")
        return True

    @staticmethod
    def _created(clip) -> float:
        try:
            r = db.conn().execute("SELECT created FROM clips WHERE id=?", (clip.plan.id,)).fetchone()
            return float(r[0] or 0) if r else 0.0
        except Exception:
            return 0.0

    def _wait_user(self, cfg: Config, q: int) -> bool:
        """True = adiar a producao porque voce esta usando o PC (so se ainda ha algo na fila para postar)."""
        if not cfg.get("autopiloto.esperar_pc_ocioso", True):
            self.state.user_busy = False
            return False
        idle = user_idle_s()
        busy = idle < float(cfg.get("autopiloto.ocioso_min", 5)) * 60
        if not busy:
            self.state.user_busy = False
            self.state.busy_since = 0.0
            return False
        if not self.state.busy_since:
            self.state.busy_since = time.time()
        waited = time.time() - self.state.busy_since
        max_wait = float(cfg.get("autopiloto.espera_maxima_ocioso_min", 120)) * 60
        # fila vazia ou espera longa demais: produz mesmo assim (com prioridade baixa)
        self.state.user_busy = q > 0 and waited < max_wait
        return self.state.user_busy

    # --------------------------------------------------------- produtor
    def producer(self) -> None:
        from . import storage
        from .pipeline import RunOptions, run

        backoff = 0
        last_run = 0.0
        while not self.stop.is_set():
            try:
                cfg = self.cfg = load_config()
                outra = andamento.read()
                if outra and outra.get("pid") != os.getpid():
                    self.state.prod_activity = "esperando terminar o seu pedido"
                    self.stop.wait(20)
                    continue
                if capacity(cfg) <= 0:      # conta nova ou limite zerado: nada de via rapida
                    with self.fast_lock:
                        self.fast_lane.clear()
                if (self.fast_lane and storage.free_gb() >= float(cfg.get("armazenamento.espaco_minimo_livre_gb", 2))
                        and len(queue(cfg)) < int(cfg.get("autopiloto.fila_maxima", 12))
                        and not self._wait_user(cfg, 1)):
                    if self._run_fast_lane(cfg):
                        free_memory()
                        continue
                qlist = queue(cfg)
                q = len(qlist)
                max_q = int(cfg.get("autopiloto.fila_maxima", 12))
                target = target_queue(cfg)          # proporcional ao que da para postar (x estoque)
                every = float(cfg.get("autopiloto.intervalo_producao_min", 90)) * 60
                force_h = float(cfg.get("autopiloto.producao_maxima_h", 6)) * 3600
                now = time.time()
                due = now >= self.state.next_production
                # assunto fresco: se nada na fila tem menos de X horas, produz pelo menos 1 video
                newest = max((self._created(c) for c in qlist), default=0.0)
                stale = capacity(cfg) > 0 and (now - newest) > force_h and (now - last_run) > force_h
                need = q < target or stale
                if due and need and q < max_q and not self._wait_user(cfg, q):
                    if storage.free_gb() < float(cfg.get("armazenamento.espaco_minimo_livre_gb", 2)):
                        self.state.set_prod("disco quase cheio: limpando e arquivando no OneDrive...")
                        storage.cleanup(cfg)
                        try:
                            storage.archive_to_onedrive(cfg)
                        except Exception as e:
                            _log.warning("arquivo OneDrive: %s", e)
                        if storage.free_gb() < float(cfg.get("armazenamento.espaco_minimo_livre_gb", 2)):
                            self.state.alert("Disco cheio: produção pausada. Libere espaço no C:.")
                            self.state.next_production = time.time() + 1800
                            continue
                    self.state.cycles += 1
                    per_video = max(1.0, float(cfg.get("autopiloto.cortes_por_video_estimado", 2)))
                    missing = max(1, target - q)
                    n_videos = max(1, min(int(cfg.get("execucao.videos_por_execucao", 5)),
                                          int(-(-missing // per_video))))
                    self.state.set_prod(f"rodada #{self.state.cycles}: fila {q}/{target}, {n_videos} video(s)")
                    opts = RunOptions(trigger="autopiloto", publish_mode="fila", interactive=False, notify=False,
                                      n_videos=n_videos, max_clips=missing + 1)
                    summary = run(cfg, opts, AutopilotReporter(self.state))
                    last_run = time.time()
                    try:
                        from . import curadoria

                        if cfg.get("autopiloto.publicacao", "auto") == "auto":
                            curadoria.curate(cfg)
                    except Exception as e:
                        _log.warning("curadoria: %s", e)
                    free_memory()
                    self.state.brain = summary.get("brain", "?")
                    n = len(summary.get("clips", []))
                    st = summary.get("status")
                    self.state.last_cycle = f"{datetime.now():%H:%M} | {n} cortes | {st}"
                    for a in summary.get("actions", []):
                        self.state.alert(a)
                    if st == "erro" or n == 0 or len(queue(cfg)) <= q:
                        self.state.errors += 1 if st == "erro" else 0
                        backoff = min(backoff + 1, 4)
                        wait = 600 * (2 ** (backoff - 1))  # 10, 20, 40, 80 min
                        self.state.next_production = time.time() + wait
                        self.state.set_prod(f"rodada sem cortes; nova tentativa em {fmt_duration(wait)}")
                    else:
                        backoff = 0
                        self.state.cycles_ok += 1
                        self.state.next_production = time.time() + every
                        self.state.set_prod(f"rodada ok: +{n} cortes na fila")
                else:
                    if not due:
                        msg = "esperando a proxima rodada"
                    elif q >= max_q or not need:
                        msg = f"fila cheia ({q}/{target} cortes) - esperando o publicador"
                    elif self.state.user_busy:
                        msg = "voce esta usando o PC: produzo quando ficar ocioso"
                    else:
                        msg = "aguardando"
                    if self.state.prod_activity != msg:
                        self.state.prod_activity = msg
                    self.stop.wait(20)
            except Exception as e:
                self.state.errors += 1
                self.state.set_prod(f"erro: {str(e)[:80]} - tentando de novo em 10 min")
                _log.error("produtor: %s\n%s", e, traceback.format_exc())
                self.state.next_production = time.time() + 600
                self.stop.wait(30)

    # ------------------------------------------------------- publicador
    def _logged_platforms(self, cfg: Config) -> list[str]:
        from . import publish

        from . import policy

        if time.time() - self.state.logins_checked > 600:
            for p in cfg.get("publicacao.plataformas", ["youtube", "tiktok"]):
                try:
                    self.state.logins[p] = bool(publish.check_login(p, cfg))
                except Exception:
                    self.state.logins[p] = False
                if self.state.logins[p]:
                    policy.register_login(p)
            self.state.logins_checked = time.time()
        return [p for p, ok in self.state.logins.items() if ok]

    def _next_post_time(self, cfg: Config, platforms: list[str]) -> float:
        """Proximo horario de post entre as redes (melhores janelas de cada uma, ver policy.DEFAULT_SLOTS)."""
        from . import policy

        ts = [t for t in (policy.next_slot(p, cfg) for p in platforms) if t]
        return max(time.time() + 20, min(ts)) if ts else time.time() + 3600

    def publisher(self) -> None:
        from .pipeline import MAX_TENTATIVAS, publish_clips

        while not self.stop.is_set():
            try:
                cfg = self.cfg
                now = datetime.now()
                if self.no_publish:
                    self.state.pub_activity = "desligado (modo so produzir)"
                    self.stop.wait(30)
                    continue
                if cfg.get("autopiloto.publicacao", "auto") == "auto":
                    from . import curadoria

                    if curadoria.pending(cfg) and not andamento.read():   # julga depois que a rodada termina
                        self.state.set_pub("escolhendo o que vale postar")
                        r = curadoria.curate(cfg)
                        if r["aprovados"] or r["descartados"]:
                            self.state.set_pub(f"{len(r['aprovados'])} aprovado(s), {len(r['descartados'])} descartado(s)")
                            if r["aprovados"]:
                                self.state.next_post = min(self.state.next_post, time.time() + 60)
                expired = expire_old(cfg)
                if expired:
                    _log.info("%s corte(s) velhos sairam da fila", expired)
                from . import policy as _pol

                sig = tuple((p, _pol.daily_limit(p, cfg)) for p in cfg.get("publicacao.plataformas", ["youtube", "tiktok"]))
                if getattr(self, "_limit_sig", sig) != sig:
                    self.state.next_post = min(self.state.next_post, time.time() + 30)
                self._limit_sig = sig
                if time.time() < self.state.next_post:
                    self.stop.wait(5)
                    continue
                start, end = cfg.get("autopiloto.janela_publicacao", ["07:30", "00:30"])
                if not in_window(now, start, end):
                    nxt = next_window_start(now, start) + timedelta(minutes=random.uniform(0, 20))
                    self.state.next_post = nxt.timestamp()
                    self.state.set_pub(f"fora da janela de publicacao; volta as {nxt:%H:%M}")
                    continue
                from . import policy
                from .publish import guard

                logged = [p for p in self._logged_platforms(cfg)
                          if self.state.paused_platforms.get(p, 0) < time.time() and not guard.paused_until(p)]
                platforms, reasons = [], []
                for p in logged:
                    ok, why = policy.can_post(p, cfg)
                    if ok and not self.dry_run and time.time() > self._urgent and not policy.slot_due(p, cfg):
                        ok, why = False, f"proximo horario {datetime.fromtimestamp(policy.next_slot(p, cfg)):%d/%m %H:%M}"
                    (platforms.append(p) if ok else reasons.append(f"{p}: {why}"))
                if not platforms:
                    not_logged = [p for p, ok in self.state.logins.items() if not ok]
                    if not logged and not_logged:
                        self.state.alert(f"Faça login: {', '.join(not_logged)} (menu > Contas)")
                        self.state.set_pub("sem rede logada para publicar")
                        self.state.next_post = time.time() + 300
                    else:
                        self.state.set_pub(" | ".join(reasons)[:90] or "aguardando")
                        self.state.next_post = self._next_post_time(cfg, logged) if logged else time.time() + 600
                    continue
                # so cortes que ainda faltam em alguma rede liberada agora (evita travar num corte ja postado nela)
                q = [c for c in queue(cfg) if c.plan.id not in self.state.tested_ids
                     and any(not db.already_posted(c.plan.id, p) and db.failed_attempts(c.plan.id, p) < MAX_TENTATIVAS
                             for p in platforms)]
                q.sort(key=lambda c: sum(db.failed_attempts(c.plan.id, p) for p in platforms))   # estavel
                if not q:
                    self.state.set_pub("fila vazia - esperando o produtor")
                    self.state.next_post = time.time() + 120
                    continue
                clip = q[0]
                self.state.set_pub(f"publicando: {clip.plan.title[:50]}")
                results, actions = publish_clips(cfg, [clip], self.dry_run, AutopilotReporter(self.state), only=platforms)
                for a in actions:
                    self.state.alert(a)
                for r in results:
                    if r.error and r.error.startswith("ACAO_NECESSARIA"):
                        self.state.paused_platforms[r.platform] = time.time() + 3600
                        self.state.alert(f"{r.platform}: {r.error.split(':', 1)[1].strip()[:90]}")
                        notify.toast("CORTEX precisa de voce", f"{r.platform}: {r.error.split(':', 1)[1].strip()}", cfg)
                if self.dry_run:
                    self.state.tested_ids.add(clip.plan.id)
                ok = [r.platform for r in results if r.ok]
                self.state.next_post = self._next_post_time(cfg, self._logged_platforms(cfg) or platforms)
                self.state.set_pub(("ok em " + ", ".join(ok) if ok else "falhou (ver log)") +
                                   f"; proximo post as {datetime.fromtimestamp(self.state.next_post):%H:%M}")
            except Exception as e:
                self.state.errors += 1
                self.state.set_pub(f"erro: {str(e)[:80]}")
                _log.error("publicador: %s\n%s", e, traceback.format_exc())
                self.state.next_post = time.time() + 600
                self.stop.wait(30)

    # ------------------------------------------------------------ painel
    def _countdown(self, ts: float) -> str:
        d = ts - time.time()
        return "agora" if d <= 0 else fmt_duration(d)

    def render(self) -> Layout:
        cfg = self.cfg
        st = self.state
        tick = SPIN[int(time.time() * 8) % len(SPIN)]
        uptime = fmt_duration(time.time() - st.started)

        head = Text()
        for i, line in enumerate(ui._BANNER):
            n = max(1, len(line) - 1)
            t = Text(" ")
            for j, ch in enumerate(line):
                t.append(ch, style=f"bold {ui._lerp_hex(ui.C_RED, ui.C_CYAN, min(1.0, j / n * 0.7 + i * 0.06))}")
            head.append_text(t)
            head.append("\n")
        mode = "TESTE (nao publica de verdade)" if self.dry_run else ("SO PRODUZINDO" if self.no_publish else "ATIVO")
        status = Text(f" {tick} PILOTO AUTOMATICO {mode}", style=f"bold {ui.C_OK if not self.dry_run else ui.C_YEL}")
        status.append(f"   ligado ha {uptime}   |   cerebro: {st.brain}   |   {datetime.now():%d/%m %H:%M:%S}",
                      style=ui.C_DIM)

        # agora
        now_t = Table.grid(padding=(0, 1))
        now_t.add_column(style=ui.C_CYAN, no_wrap=True)
        now_t.add_column()
        busy = not st.prod_activity.startswith(("esperando", "aguardando", "fila cheia", "rodada ok"))
        now_t.add_row("Cortando", Text((tick + " " if busy else "") + st.prod_activity[:70], style="white"))
        now_t.add_row("Postando", Text(st.pub_activity[:70], style="white"))
        now_t.add_row("Próximo post", Text(self._countdown(st.next_post), style=ui.C_YEL))
        now_t.add_row("Próxima busca", Text(self._countdown(st.next_production), style=ui.C_YEL))
        now_t.add_row("Última rodada", Text(st.last_cycle, style=ui.C_DIM))
        fl = len(self.fast_lane)
        now_t.add_row("Vigia", Text(ui.term(st.watch_activity)[:60] + (f" | {fl} na frente da fila" if fl else ""),
                                    style=ui.C_YEL if fl else ui.C_DIM))

        # hoje
        from . import policy

        lim = {p: policy.effective_limit(p, cfg) for p in cfg.get("publicacao.plataformas", ["youtube", "tiktok"])}
        today = datetime.now().replace(hour=0, minute=0, second=0).timestamp()
        try:
            made = db.conn().execute("SELECT COUNT(*) FROM clips WHERE created>=? AND status!='planejado'",
                                     (today,)).fetchone()[0]
            fails = db.conn().execute("SELECT COUNT(*) FROM posts WHERE ts>=? AND ok=0", (today,)).fetchone()[0]
        except Exception:
            made, fails = 0, 0
        from . import storage

        day_t = Table.grid(padding=(0, 1))
        day_t.add_column(style=ui.C_CYAN, no_wrap=True)
        day_t.add_column()
        day_t.add_row("Cortes feitos", Text(str(made), style="bold white"))
        for p in cfg.get("publicacao.plataformas", ["youtube", "tiktok"]):
            logged = st.logins.get(p)
            mark = Text(" ok", style=ui.C_OK) if logged else Text(" SEM LOGIN", style=ui.C_RED) if logged is False else Text("")
            n = db.posts_today(p)
            row = Text(f"{n}/{lim.get(p, 8)}", style="bold white")
            row.append_text(mark)
            day_t.add_row(f"Posts {p}", row)
        day_t.add_row("Falhas", Text(str(fails + st.errors), style=ui.C_RED if (fails + st.errors) else ui.C_OK))
        free = storage.free_gb()
        day_t.add_row("Disco livre", Text(f"{free:.1f} GB", style=ui.C_OK if free > 3 else ui.C_YEL))
        try:
            from . import uso_ia

            day_t.add_row("IA hoje", Text(uso_ia.resumo(cfg), style="white"))
        except Exception:
            pass
        try:
            from . import memoria

            mem = memoria.status()
            low = mem["reserva_livre"] < 3
            day_t.add_row("Memória", Text(f"{mem['ram_livre']:.1f} GB livres" + (" (feche programas)" if low else ""),
                                          style=ui.C_YEL if low else ui.C_OK))
        except Exception:
            pass
        day_t.add_row("PC", Text("em uso por você (eu espero)" if st.user_busy else "livre",
                                 style=ui.C_YEL if st.user_busy else ui.C_OK))

        # fila
        q = queue(cfg)
        q_t = Table.grid(padding=(0, 1))
        q_t.add_column(no_wrap=True)
        q_t.add_column(no_wrap=True)
        q_t.add_column(overflow="ellipsis", no_wrap=True)
        for i, c in enumerate(q[:5], 1):
            part = f" (P{c.plan.part}/{c.plan.parts_total})" if c.plan.part else ""
            q_t.add_row(f"{i}.", ui.score_text(c.plan.score), Text(ui.term(c.plan.title)[:60] + part))
        if not q:
            q_t.add_row("", Text("vazia", style=ui.C_DIM), Text(""))

        # log
        log_lines = list(self.loghandler.lines)[-14:]
        lg = Text()
        for ts, lvl, name, msg in log_lines:
            color = ui.C_RED if lvl >= logging.ERROR else (ui.C_YEL if lvl >= logging.WARNING else "white")
            lg.append(f"{ts} ", style=ui.C_DIM)
            lg.append(f"{name[:10]:<10} ", style=ui.C_CYAN)
            lg.append(msg[:150] + "\n", style=color)

        alerts = Text()
        from .publish import guard

        for msg in guard.waiting().values():
            alerts.append(">> " + msg + "\n", style=f"bold white on {ui.C_RED}")
        for a in st.alerts[-3:]:
            alerts.append("! " + a + "\n", style=f"bold {ui.C_YEL}")

        layout = Layout()
        layout.split_column(
            Layout(Group(head, status), name="head", size=8),
            Layout(name="mid", size=13),
            Layout(Panel(q_t, title=f"Fila de publicação ({len(q)})", border_style=ui.C_DIM), name="queue", size=7),
            Layout(Panel(Group(alerts, lg) if alerts.plain else lg, title="Log ao vivo", border_style=ui.C_DIM), name="log"),
            Layout(Text(" Ctrl+C para parar  |  posta sozinho todo dia: risco de banimento  |  relatório: relatorios\\ultimo.html", style=ui.C_DIM),
                   name="foot", size=1),
        )
        layout["mid"].split_row(
            Layout(Panel(now_t, title="Agora", border_style=ui.C_CYAN), ratio=3),
            Layout(Panel(day_t, title="Hoje", border_style=ui.C_RED), ratio=2),
        )
        return layout

    # ------------------------------------------------------------ ciclo
    def _single_instance(self) -> None:
        if self._lock_file.exists():
            try:
                d = json.loads(self._lock_file.read_text())
                pid = int(d["pid"])
                if pid != os.getpid() and andamento.alive(d):
                    raise RuntimeError("O automático já está rodando.")
            except (ValueError, KeyError):
                pass
        self._lock_file.write_text(json.dumps({**andamento.me(), "ts": time.time()}))

    def _heartbeat(self) -> None:
        st = self.state
        andamento.write_json(HEARTBEAT, {
            **andamento.me(), "ts": time.time(), "desde": st.started, "produtor": st.prod_activity,
            "publicador": st.pub_activity, "rodadas": st.cycles, "rodadas_ok": st.cycles_ok, "erros": st.errors,
            "alertas": st.alerts, "teste": self.dry_run, "proximo_post": st.next_post, "proxima_busca": st.next_production,
            "ultima_rodada": st.last_cycle, "pc_em_uso": st.user_busy, "vigia": st.watch_activity,
        })

    def run(self, headless: bool = False) -> int:
        paths.ensure_dirs()
        self._single_instance()
        STOP_FILE.unlink(missing_ok=True)
        logging.getLogger("fabrica").addHandler(self.loghandler)
        if self.cfg.get("autopiloto.prioridade_baixa", True):
            set_low_priority()
        if self.cfg.get("autopiloto.manter_pc_acordado", True):
            keep_awake(True)
        _log.info("Piloto automatico iniciado%s", " (modo teste)" if self.dry_run else "")
        workers = [threading.Thread(target=self.producer, name="produtor", daemon=True),
                   threading.Thread(target=self.publisher, name="publicador", daemon=True),
                   threading.Thread(target=self.watcher, name="vigia", daemon=True),
                   threading.Thread(target=self.metrics_worker, name="metricas", daemon=True)]
        # o publicador comeca alguns minutos depois (deixa o produtor encher a fila)
        self.state.next_post = time.time() + random.uniform(30, 120)
        for w in workers:
            w.start()
        try:
            if headless:
                self._loop(lambda: None, 1.0)
            else:
                with Live(self.render(), console=ui.console, refresh_per_second=2, screen=True,
                          redirect_stdout=False, redirect_stderr=False) as live:
                    self._loop(lambda: live.update(self.render()), 0.5)
        except KeyboardInterrupt:
            pass
        finally:
            self.stop.set()
            # post no meio: espera terminar (nunca larga um envio pela metade)
            pub = next(w for w in workers if w.name == "publicador")
            end = time.time() + 2400
            while pub.is_alive() and self.state.pub_activity.startswith("publicando") and time.time() < end:
                pub.join(timeout=2)
                with contextlib.suppress(Exception):
                    self._heartbeat()
            keep_awake(False)
            logging.getLogger("fabrica").removeHandler(self.loghandler)
            for f in (self._lock_file, HEARTBEAT):
                with contextlib.suppress(OSError):
                    f.unlink()
        _log.info("Automatico parado")
        for w in workers:
            w.join(timeout=3)
        if getattr(self, "_stuck", False):
            andamento.end()
            os._exit(3)   # o vigia do Windows liga de novo em ate 10 min
        if not headless:
            ui.console.print()
            ui.ok("Automático parado.")
        return 0

    def _loop(self, draw, pause: float) -> None:
        """Batimento e painel. Um erro de desenho ou de disco nunca derruba o automatico."""
        fails = 0
        while not self.stop.is_set():
            if STOP_FILE.exists():
                STOP_FILE.unlink(missing_ok=True)
                return
            run = andamento.read()
            if run and run.get("pid") == os.getpid() and time.time() - float(run.get("msg_desde") or time.time()) > 2.5 * 3600:
                _log.error("a rodada travou no passo '%s' ha mais de 2 h: reiniciando o automatico", run.get("msg"))
                self._stuck = True
                return
            try:
                draw()
                self._heartbeat()
                fails = 0
            except Exception as e:
                fails += 1
                if fails in (1, 50):
                    _log.warning("painel: %s", e)
            time.sleep(pause)


def running() -> bool:
    """O automatico esta ligado (em qualquer processo)?"""
    d = andamento.read_json(HEARTBEAT) or {}
    return andamento.alive(d) and time.time() - float(d.get("ts", 0)) < 180


def request_stop() -> None:
    """Pede para o automatico (em outra janela) parar."""
    STOP_FILE.write_text(str(time.time()), encoding="utf-8")


def status_text() -> str:
    from .pipeline import _pid_alive

    if not HEARTBEAT.exists():
        return "Piloto automatico: DESLIGADO"
    try:
        d = json.loads(HEARTBEAT.read_text(encoding="utf-8"))
        if not _pid_alive(int(d["pid"])) or time.time() - d["ts"] > 120:
            return "Piloto automatico: DESLIGADO (ultima execucao terminou)"
        return (f"Piloto automatico: LIGADO ha {fmt_duration(time.time() - d['desde'])} | "
                f"{d['rodadas']} rodadas | produtor: {d['produtor']} | publicador: {d['publicador']}")
    except Exception:
        return "Piloto automatico: estado desconhecido"
