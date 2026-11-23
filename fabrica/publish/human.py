"""Camada de acoes da publicacao (usada por youtube.py e tiktok.py).

- espera de prontidao REAL: elemento visivel + parado + sem carregando por cima + rede calma;
- clique e digitacao normais do Playwright;
- uma tentativa paciente por passo e, no maximo, UMA repeticao depois de conferir que o passo nao foi feito;
- captcha/login/verificacao: para na hora e avisa o dono.

Nao imita pessoa: sem curva de mouse, tremor, ponto aleatorio de clique, digitacao irregular ou
navegacao de fachada. Disfarcar automacao nao e objetivo deste projeto (docs/PUBLICACAO_SEGURA.md).
"""
from __future__ import annotations

import json
import math
import random
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from .. import paths
from ..log import get as get_log
from ..models import CaptchaAppeared, NeedsUserAction

log = get_log(__name__)

# Multiplicador global das esperas (testes usam 0.2 para rodar rapido)
SPEED = 1.0

DEFAULTS: dict[str, Any] = {
    "velocidade": 1.0,                  # multiplica todas as esperas (1 = normal; 1.5 = mais calmo)
    "pausa_pensar_s": [1.2, 3.5],       # antes de decisoes (escolher arquivo, Publicar...)
    "pausa_curta_s": [0.4, 1.2],        # entre acoes seguidas
    "hover_ms": [120, 450],             # mouse parado sobre o elemento antes do clique
    "digitacao_cps": [6.0, 9.0],        # letras por segundo (media de cada texto sorteada nesta faixa)
    "pausa_pontuacao_s": [0.25, 0.7],   # extra depois de . , ! ? ; :
    "pausa_palavra_s": [0.04, 0.22],    # extra entre palavras
    "digitar_ate_chars": 280,           # textos maiores (ou com #) sao colados de uma vez
    "aquecimento_s": [5, 20],           # tempo parado na pagina inicial antes do upload
    "rolagens_aquecimento": [1, 3],     # rolagens calmas na pagina inicial (sem curtir/seguir/comentar)
    "timeout_acao_s": 45,               # paciencia de cada acao (uma tentativa so)
    "pausa_antes_de_repetir_s": [25, 60],  # pausa longa antes da UNICA nova tentativa de um passo
    "rede_calma_max_s": 6,              # no maximo isso esperando a rede acalmar (melhor esforco)
}

# Carregando/spinners comuns (Studio do YouTube e TikTok). So contam se estiverem POR CIMA do alvo.
SPINNER_SELECTORS = [
    "tp-yt-paper-spinner[active]", "tp-yt-paper-spinner-lite[active]", "ytcp-spinner[active]",
    ".TUXLoading", '[class*="loading-spinner"]', '[class*="LoadingSpinner"]', '[class*="Spinner"]',
    '[class*="spinner"]', '[role="progressbar"][aria-busy="true"]',
]

# Pedidos de rede que nunca "acalmam" (upload do video, midia, telemetria, long-poll): ignorados
_NET_IGNORE_TYPES = {"media", "websocket", "eventsource", "image", "font"}
_NET_IGNORE_URL = re.compile(r"(upload|videoplayback|/log|collect|monitor|/mon\b|/report|heartbeat|ping|"
                             r"webcast|metrics|analytics|beacon|/tos-|vod-|/api/stats|csi|jnn|/gen_204|"
                             r"/generate_204|youtubei/v1/log)", re.I)


class StepError(RuntimeError):
    """Um passo falhou de vez (ja com print e mensagem em pt-BR)."""


def _rng() -> random.Random:
    return random.Random()


def _range(v: Any, default: list) -> tuple[float, float]:
    try:
        if isinstance(v, (int, float)):
            return float(v), float(v)
        a, b = float(v[0]), float(v[-1])
        return (min(a, b), max(a, b))
    except Exception:
        return float(default[0]), float(default[-1])


@dataclass
class Ritmo:
    """Faixas de tempo lidas de cfg publicacao.humano.* (com os padroes acima)."""
    velocidade: float = 1.0
    pensar: tuple[float, float] = (1.2, 3.5)
    curta: tuple[float, float] = (0.4, 1.2)
    hover_ms: tuple[float, float] = (120, 450)
    cps: tuple[float, float] = (6.0, 9.0)
    pontuacao: tuple[float, float] = (0.25, 0.7)
    palavra: tuple[float, float] = (0.04, 0.22)
    digitar_ate: int = 280
    aquecimento: tuple[float, float] = (5, 20)
    rolagens: tuple[int, int] = (1, 3)
    timeout: float = 45.0
    pausa_repetir: tuple[float, float] = (25, 60)
    rede_max: float = 6.0

    @classmethod
    def from_cfg(cls, cfg: Any) -> "Ritmo":
        def g(k: str) -> Any:
            v = cfg.get(f"publicacao.humano.{k}") if cfg is not None else None
            return DEFAULTS[k] if v is None else v
        rol = _range(g("rolagens_aquecimento"), DEFAULTS["rolagens_aquecimento"])
        try:
            vel = max(0.1, float(g("velocidade")))
        except Exception:
            vel = 1.0
        return cls(
            velocidade=vel,
            pensar=_range(g("pausa_pensar_s"), DEFAULTS["pausa_pensar_s"]),
            curta=_range(g("pausa_curta_s"), DEFAULTS["pausa_curta_s"]),
            hover_ms=_range(g("hover_ms"), DEFAULTS["hover_ms"]),
            cps=_range(g("digitacao_cps"), DEFAULTS["digitacao_cps"]),
            pontuacao=_range(g("pausa_pontuacao_s"), DEFAULTS["pausa_pontuacao_s"]),
            palavra=_range(g("pausa_palavra_s"), DEFAULTS["pausa_palavra_s"]),
            digitar_ate=int(g("digitar_ate_chars") or 280),
            aquecimento=_range(g("aquecimento_s"), DEFAULTS["aquecimento_s"]),
            rolagens=(int(rol[0]), int(rol[1])),
            timeout=float(g("timeout_acao_s") or 45),
            pausa_repetir=_range(g("pausa_antes_de_repetir_s"), DEFAULTS["pausa_antes_de_repetir_s"]),
            rede_max=float(g("rede_calma_max_s") or 6),
        )

    def scale(self) -> float:
        return self.velocidade * SPEED


# ------------------------------------------------------------- registro de tempos
@dataclass
class Tempos:
    """Registro dos tempos "humanos" de um envio (vai para logs/publicacao_ritmo.log)."""
    mouse: list[tuple[float, float, int]] = field(default_factory=list)   # (distancia px, ms, pontos)
    hover_ms: list[float] = field(default_factory=list)
    cliques: list[tuple[float, float]] = field(default_factory=list)       # deslocamento do centro (fracao w, h)
    digitacao: list[tuple[int, float]] = field(default_factory=list)       # (letras, segundos)
    colagens: list[int] = field(default_factory=list)
    pensar: list[float] = field(default_factory=list)
    rolagens: list[tuple[int, int]] = field(default_factory=list)          # (passos, px)
    prontidao_s: list[float] = field(default_factory=list)
    rede_calma_s: list[float] = field(default_factory=list)
    aquecimento_s: list[float] = field(default_factory=list)
    repeticoes: list[str] = field(default_factory=list)
    passos: list[tuple[str, float, bool]] = field(default_factory=list)

    def resumo(self) -> dict:
        def stat(xs: list[float]) -> str:
            if not xs:
                return "-"
            return f"n={len(xs)} media={sum(xs) / len(xs):.2f} min={min(xs):.2f} max={max(xs):.2f}"
        chars = sum(c for c, _ in self.digitacao)
        secs = sum(s for _, s in self.digitacao)
        mv = [ms for _, ms, _ in self.mouse]
        return {
            "mouse_ms": stat(mv),
            "mouse_px": stat([d for d, _, _ in self.mouse]),
            "mouse_pontos": stat([float(n) for _, _, n in self.mouse]),
            "hover_ms": stat(self.hover_ms),
            "clique_desvio_do_centro": stat([math.hypot(a, b) for a, b in self.cliques]),
            "digitacao": f"{chars} letras em {secs:.1f} s = {chars / secs:.1f} letras/s" if secs else "-",
            "colagens": f"{len(self.colagens)} ({sum(self.colagens)} letras)",
            "pensar_s": stat(self.pensar),
            "rolagens": f"{len(self.rolagens)} ({sum(p for p, _ in self.rolagens)} passos)",
            "prontidao_s": stat(self.prontidao_s),
            "rede_calma_s": stat(self.rede_calma_s),
            "aquecimento_s": stat(self.aquecimento_s),
            "repeticoes": len(self.repeticoes),
            "passos": len(self.passos),
        }

    def linhas(self) -> list[str]:
        return [f"{k}: {v}" for k, v in self.resumo().items()]


def append_timing_log(platform: str, clip_id: str, t: Tempos, extra: str = "") -> None:
    try:
        paths.LOGS.mkdir(parents=True, exist_ok=True)
        f = paths.LOGS / "publicacao_ritmo.log"
        with open(f, "a", encoding="utf-8") as fh:
            fh.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} [{platform}] {clip_id} {extra}\n")
            fh.write("   " + json.dumps(t.resumo(), ensure_ascii=False) + "\n")
            for name, secs, ok in t.passos:
                fh.write(f"   passo {'ok ' if ok else 'ERRO'} {secs:6.1f}s  {name}\n")
    except Exception as e:
        log.debug("log de ritmo: %s", e)


# ------------------------------------------------------------------- rede calma
class NetWatch:
    """Conta pedidos de rede "de interface" em andamento numa aba (ignora upload, midia e telemetria)."""

    def __init__(self, page: Any):
        self.inflight: dict[int, float] = {}
        self.last = time.monotonic()
        self.ok = False
        try:
            page.on("request", self._start)
            page.on("requestfinished", self._end)
            page.on("requestfailed", self._end)
            self.ok = True
        except Exception:
            pass

    def _relevant(self, req: Any) -> bool:
        try:
            if req.resource_type in _NET_IGNORE_TYPES:
                return False
            return not _NET_IGNORE_URL.search(req.url or "")
        except Exception:
            return False

    def _start(self, req: Any) -> None:
        if self._relevant(req):
            self.inflight[id(req)] = time.monotonic()
            self.last = time.monotonic()

    def _end(self, req: Any) -> None:
        if self.inflight.pop(id(req), None) is not None:
            self.last = time.monotonic()

    def busy(self, now: float) -> int:
        # pedidos pendurados ha mais de 8 s sao de fundo (long-poll): nao contam
        for k, t0 in list(self.inflight.items()):
            if now - t0 > 60:
                self.inflight.pop(k, None)
        return sum(1 for t0 in self.inflight.values() if now - t0 <= 8)


_STATE_JS = """(el, spinSels) => {
  const r = el.getBoundingClientRect();
  let busy = false;
  for (let n = el; n; n = n.parentElement || (n.getRootNode && n.getRootNode().host) || null) {
    if (n.getAttribute && (n.getAttribute('aria-busy') === 'true' || n.getAttribute('data-loading') === 'true')) { busy = true; break; }
  }
  let spin = '';
  outer: for (const s of spinSels) {
    let list = [];
    try { list = document.querySelectorAll(s); } catch (e) { continue; }
    for (const sp of list) {
      if (sp === el || el.contains(sp)) continue;
      const q = sp.getBoundingClientRect();
      if (q.width < 4 || q.height < 4) continue;
      const st = getComputedStyle(sp);
      if (st.visibility === 'hidden' || st.display === 'none' || parseFloat(st.opacity) === 0) continue;
      if (q.left < r.right && q.right > r.left && q.top < r.bottom && q.bottom > r.top) { spin = s; break outer; }
    }
  }
  const dis = el.disabled === true || el.getAttribute('aria-disabled') === 'true' ||
              el.getAttribute('data-disabled') === 'true' || el.hasAttribute('disabled');
  return {x: r.x, y: r.y, w: r.width, h: r.height, busy, spin, dis, vw: innerWidth, vh: innerHeight};
}"""


_HIT_JS = """(el, [x, y]) => {
  let t = document.elementFromPoint(x, y);
  while (t && t.shadowRoot) { const i = t.shadowRoot.elementFromPoint(x, y); if (!i || i === t) break; t = i; }
  for (let n = t; n; n = n.parentNode || n.host) { if (n === el) return true; }
  return false;
}"""


# ------------------------------------------------------------------------ ator
class Actor:
    """Faz as acoes numa aba com ritmo humano e registra os tempos.

    h = Actor(page, cfg, "youtube", clip_id, emit, blockers=lambda: _check_blockers(page))
    h.warm_up(url); h.click(loc); h.type_text("..."); h.step("nome", fn, verify=...)
    """

    def __init__(self, page: Any, cfg: Any = None, platform: str = "", clip_id: str = "",
                 emit: Callable[[str], None] | None = None, blockers: Callable[[], None] | None = None,
                 rng: random.Random | None = None):
        self.page = page
        self.cfg = cfg
        self.r = Ritmo.from_cfg(cfg)
        self.platform = platform
        self.clip_id = clip_id
        self.emit = emit or (lambda m: log.info(m))
        self._check = blockers or (lambda: None)
        self.t = Tempos()
        self.net = NetWatch(page)
        self.mouse: tuple[float, float] | None = None
        self.rng = rng or _rng()

    def blockers(self) -> bool:
        """Confere login/captcha/limite. CAPTCHA: mostra a janela e espera o DONO resolver (ajuda.py).
        True = havia um CAPTCHA e o dono resolveu."""
        try:
            self._check()
            return False
        except CaptchaAppeared:
            from . import ajuda

            if ajuda.wait_owner(self.page, self.platform, self._check, self.emit, self.cfg):
                return True
            raise

    # ---------------------------------------------------------------- esperas
    def sleep(self, a: float, b: float | None = None) -> float:
        """Espera fixa (media da faixa), so para a pagina acompanhar."""
        b = a if b is None else b
        secs = max(0.0, (a + b) / 2) * self.r.scale()
        self._wait(secs)
        return secs

    def _wait(self, secs: float) -> None:
        if secs <= 0:
            return
        try:
            self.page.wait_for_timeout(secs * 1000)
        except Exception:
            time.sleep(secs)

    def pause(self) -> None:
        self.sleep(*self.r.curta)

    def think(self) -> None:
        self.t.pensar.append(self.sleep(*self.r.pensar))

    # ------------------------------------------------------------- prontidao
    def wait_net_calm(self, quiet: float = 0.5, max_s: float | None = None) -> float:
        """Espera (melhor esforco) a rede da interface ficar parada por `quiet` s."""
        if not self.net.ok:
            return 0.0
        max_s = self.r.rede_max if max_s is None else max_s
        t0 = time.monotonic()
        while True:
            now = time.monotonic()
            if self.net.busy(now) == 0 and now - self.net.last >= quiet:
                break
            if now - t0 >= max_s:
                break
            self._wait(0.1)
        dt = time.monotonic() - t0
        self.t.rede_calma_s.append(dt)
        return dt

    def state(self, loc: Any) -> dict | None:
        try:
            return loc.evaluate(_STATE_JS, SPINNER_SELECTORS)
        except Exception:
            return None

    def wait_ready(self, loc: Any, timeout: float | None = None, enabled: bool = False,
                   what: str = "elemento") -> dict:
        """Visivel + parado (mesma posicao em 2 leituras) + sem carregando por cima (+ habilitado) + rede calma."""
        timeout = self.r.timeout if timeout is None else timeout
        t0 = time.monotonic()
        try:
            loc.wait_for(state="visible", timeout=timeout * 1000)
        except Exception:
            raise RuntimeError(f"{what} não apareceu em {int(timeout)} s")
        last, stable, st = None, 0, None
        why = "?"
        while time.monotonic() - t0 < timeout:
            st = self.state(loc)
            if st and st["w"] > 0 and st["h"] > 0:
                pos = (round(st["x"]), round(st["y"]), round(st["w"]), round(st["h"]))
                stable = stable + 1 if pos == last else 0
                last = pos
                if stable >= 1 and not st["busy"] and not st["spin"] and not (enabled and st["dis"]):
                    break
                why = ("carregando" if (st["busy"] or st["spin"]) else
                       "desativado" if (enabled and st["dis"]) else "mexendo")
            else:
                why = "invisível"
            self._wait(0.18)
        else:
            raise RuntimeError(f"{what} não ficou pronto em {int(timeout)} s ({why})")
        self.wait_net_calm(max_s=min(self.r.rede_max, max(0.5, timeout - (time.monotonic() - t0))))
        self.t.prontidao_s.append(time.monotonic() - t0)
        return st or {}

    # ------------------------------------------------------------------ mouse
    def _viewport(self) -> tuple[float, float]:
        try:
            w, h = self.page.evaluate("() => [innerWidth, innerHeight]")
            return float(w), float(h)
        except Exception:
            return 1366.0, 800.0

    def move_to(self, x: float, y: float, target_w: float = 40.0) -> None:
        """Leva o mouse ao ponto (para abrir menus que so aparecem com o mouse em cima)."""
        self.page.mouse.move(x, y)
        self.mouse = (x, y)

    # ---------------------------------------------------------------- rolagem
    def wheel(self, total_dy: float) -> None:
        self.page.mouse.wheel(0, total_dy)
        self.t.rolagens.append((1, int(abs(total_dy))))

    def scroll_into_view(self, loc: Any) -> None:
        try:
            loc.scroll_into_view_if_needed(timeout=5000)
        except Exception:
            pass

    # ------------------------------------------------------------------ clique
    def click(self, loc: Any, *, enabled: bool = True, timeout: float | None = None, what: str = "botão",
              on_press: Callable[[], None] | None = None) -> None:
        """Espera ficar pronto e usa o clique normal do Playwright (que confere se o elemento esta livre).

        on_press: chamado imediatamente antes do clique (ex.: registrar o clique em Publicar)."""
        timeout = self.r.timeout if timeout is None else timeout
        self.wait_ready(loc, timeout=timeout, enabled=enabled, what=what)
        self.scroll_into_view(loc)
        if on_press is not None:
            loc.click(trial=True, timeout=timeout * 1000)  # confere que da para clicar antes de registrar
            on_press()
        loc.click(timeout=timeout * 1000)
        self.sleep(0.5)

    def _bbox(self, loc: Any) -> dict | None:
        try:
            return loc.bounding_box(timeout=3_000)
        except Exception:
            return None

    # ---------------------------------------------------------------- teclado
    def select_all_and_delete(self) -> None:
        kb = self.page.keyboard
        kb.press("Control+A")
        self.sleep(0.12, 0.3)
        kb.press("Backspace")
        self.sleep(0.15, 0.35)

    def type_text(self, text: str) -> None:
        """Digita o texto (atraso fixo e curto, para os campos com autocompletar acompanharem)."""
        t0 = time.monotonic()
        for line_i, line in enumerate(text.split(chr(10))):
            if line_i:
                self.page.keyboard.press("Enter")
            if line:
                self.page.keyboard.type(line, delay=20)
        if text:
            self.t.digitacao.append((len(text), time.monotonic() - t0))

    def paste_text(self, text: str) -> None:
        """Como colar um texto pronto (Ctrl+V): cada linha entra de uma vez; Enter entre linhas."""
        kb = self.page.keyboard
        self.sleep(0.3, 0.8)
        for line_i, line in enumerate(text.split("\n")):
            if line_i:
                kb.press("Enter")
                time.sleep(0.01)
            if line:
                kb.insert_text(line)
        self.t.colagens.append(len(text))
        self.sleep(0.3, 0.7)

    def write(self, text: str) -> None:
        """Digita textos curtos sem '#'; cola textos longos ou com hashtags (o autocompletar atrapalha)."""
        if len(text) <= self.r.digitar_ate and "#" not in text:
            self.type_text(text)
        else:
            self.paste_text(text)

    # ----------------------------------------------------------- navegacao
    def goto(self, url: str, timeout: float = 60) -> None:
        self.page.goto(url, wait_until="domcontentloaded", timeout=timeout * 1000)
        try:
            self.page.locator("body").wait_for(state="visible", timeout=timeout * 1000)
        except Exception:
            pass
        self.wait_net_calm(quiet=0.8, max_s=max(self.r.rede_max, 8))

    def warm_up(self, url: str) -> float:
        """Abre a pagina inicial e confere se ha login/captcha antes de ir para o envio."""
        t0 = time.monotonic()
        self.goto(url)
        self.blockers()
        dt = time.monotonic() - t0
        self.t.aquecimento_s.append(dt)
        return dt

    # ---------------------------------------------------------------- passos
    def step(self, name: str, fn: Callable[[], Any], *, verify: Callable[[], bool] | None = None,
             retry: bool = True) -> Any:
        """Uma tentativa paciente. Falhou: print + erro em pt-BR; no maximo UMA nova tentativa depois de
        uma pausa longa, e so se `verify()` mostrar que o passo NAO foi feito. retry=False para passos
        que nao podem ser repetidos (escolher o arquivo, Publicar). Captcha/login: sobe na hora."""
        t0 = time.monotonic()
        try:
            out = fn()
            self.t.passos.append((name, time.monotonic() - t0, True))
            return out
        except NeedsUserAction:
            self.t.passos.append((name, time.monotonic() - t0, False))
            raise
        except Exception as e1:
            self.t.passos.append((name, time.monotonic() - t0, False))
            shot = self.screenshot("passo")
            msg = f"[{self.platform}] o passo '{name}' falhou: {_short(e1)}" + (f" (print: {shot})" if shot else "")
            self.emit(msg)
            self.blockers()  # captcha/login/limite: para aqui, sem repetir
            if verify is not None and _safe(verify):
                self.emit(f"[{self.platform}] conferi: '{name}' já tinha dado certo; sigo sem repetir.")
                return None
            if not retry:
                raise StepError(f"o passo '{name}' falhou ({_short(e1)}). Não repito este passo para não "
                                f"enviar duas vezes; desisti deste post.") from e1
            wait = sum(self.r.pausa_repetir) / 2 * self.r.scale()
            self.emit(f"[{self.platform}] vou esperar {int(wait)} s e tentar '{name}' UMA vez mais.")
            self.t.repeticoes.append(name)
            self._wait(wait)
            self.blockers()
            if verify is not None and _safe(verify):
                self.emit(f"[{self.platform}] conferi: '{name}' já está feito; sigo.")
                return None
            t1 = time.monotonic()
            try:
                out = fn()
                self.t.passos.append((name + " (2a tentativa)", time.monotonic() - t1, True))
                return out
            except NeedsUserAction:
                raise
            except Exception as e2:
                self.t.passos.append((name + " (2a tentativa)", time.monotonic() - t1, False))
                shot2 = self.screenshot("passo2")
                raise StepError(f"o passo '{name}' falhou de novo ({_short(e2)}); desisti deste post"
                                + (f" (print: {shot2})" if shot2 else "")) from e2

    def screenshot(self, tag: str) -> str | None:
        from .browser import screenshot
        return screenshot(self.page, self.platform or "pub", self.clip_id or "x", tag)

    def finish(self, extra: str = "") -> None:
        """Grava o resumo dos tempos em logs/publicacao_ritmo.log e no log normal."""
        append_timing_log(self.platform, self.clip_id, self.t, extra)
        r = self.t.resumo()
        log.info("[%s] ritmo: mouse %s | hover %s | digitacao %s | pensar %s | aquecimento %s | repeticoes %s",
                 self.platform, r["mouse_ms"], r["hover_ms"], r["digitacao"], r["pensar_s"], r["aquecimento_s"],
                 r["repeticoes"])


def _safe(fn: Callable[[], bool]) -> bool:
    try:
        return bool(fn())
    except Exception:
        return False


def _short(e: BaseException) -> str:
    s = str(e).strip().splitlines()[0] if str(e).strip() else type(e).__name__
    s = re.sub(r"\s+", " ", s)
    # mensagens do Playwright sao longas e em ingles: deixa so o essencial
    if s.startswith(("Timeout", "Locator.", "Page.", "Error:")) or "Timeout" in s[:40]:
        s = "tempo esgotado esperando a página (" + s[:120] + ")"
    return s[:220]


# ------------------------------------------------- funcoes antigas (compatibilidade)
def sleep(a: float, b: float | None = None) -> None:
    """Dorme um tempo aleatorio entre a e b segundos (sem aba)."""
    b = a if b is None else b
    time.sleep(max(0.0, (a + b) / 2) * SPEED)


def pause() -> None:
    sleep(0.4, 1.2)


def think() -> None:
    sleep(1.0, 2.5)
