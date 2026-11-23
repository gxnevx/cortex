"""Interface no terminal: banner ASCII, cores, tabelas e o 'Reporter' usado pela esteira."""
from __future__ import annotations

import contextlib
import time
from typing import Iterable, Sequence

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from . import __version__, log

console = Console(highlight=False, soft_wrap=False)
_log = log.get("ui")

# Paleta: vermelho TikTok -> ciano TikTok (passando pelo roxo)
C_RED = "#FE2C55"
C_CYAN = "#25F4EE"
C_YEL = "#FFE600"
C_DIM = "grey58"
C_OK = "#3DDC84"

APP_NAME = "CORTEX"
APP_FULL = "Central Operacional de Recortes, Tendencias e EXposicao"

_BANNER = [
    " ██████╗ ██████╗ ██████╗ ████████╗███████╗██╗  ██╗",
    "██╔════╝██╔═══██╗██╔══██╗╚══██╔══╝██╔════╝╚██╗██╔╝",
    "██║     ██║   ██║██████╔╝   ██║   █████╗   ╚███╔╝ ",
    "██║     ██║   ██║██╔══██╗   ██║   ██╔══╝   ██╔██╗ ",
    "╚██████╗╚██████╔╝██║  ██║   ██║   ███████╗██╔╝ ██╗",
    " ╚═════╝ ╚═════╝ ╚═╝  ╚═╝   ╚═╝   ╚══════╝╚═╝  ╚═╝",
]

# Arte lateral: tesoura cortando a fita de video
_SIDE = [
    "   ▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄",
    "   █ > ▓▓▓▓░░░░░░░░  █",
    "   █▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄█",
    "    8< - - - - - - - - ",
    "   ▄▄▄▄▄▄▄▄▄  ▄▄▄▄▄▄▄▄",
    "   █ 9:16  █  █ 9:16 █",
]

_FILM = "▐▌▐▌▐▌▐▌▐▌▐▌▐▌▐▌▐▌▐▌▐▌▐▌▐▌▐▌▐▌▐▌▐▌▐▌▐▌▐▌▐▌▐▌▐▌▐▌▐▌▐▌▐▌▐▌▐▌▐▌▐▌▐▌▐▌▐▌▐▌▐▌▐▌▐▌▐▌▐"


def _hex_to_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _lerp_hex(a: str, b: str, t: float) -> str:
    ra, ga, ba = _hex_to_rgb(a)
    rb, gb, bb = _hex_to_rgb(b)
    return "#{:02X}{:02X}{:02X}".format(int(ra + (rb - ra) * t), int(ga + (gb - ga) * t), int(ba + (bb - ba) * t))


def gradient_line(text: str, a: str = C_RED, b: str = C_CYAN) -> Text:
    """Gradiente horizontal caractere a caractere."""
    out = Text()
    n = max(1, len(text) - 1)
    for i, ch in enumerate(text):
        out.append(ch, style=f"bold {_lerp_hex(a, b, i / n)}")
    return out


def banner(subtitle: str | None = None, compact: bool = False) -> None:
    console.print()
    wide = console.width >= 80 and not compact
    for i, line in enumerate(_BANNER):
        # gradiente diagonal: cada linha desloca um pouco a cor
        shift = i / (len(_BANNER) - 1) * 0.35
        t = Text("  ")
        n = max(1, len(line) - 1)
        for j, ch in enumerate(line):
            tt = min(1.0, j / n * 0.65 + shift)
            t.append(ch, style=f"bold {_lerp_hex(C_RED, C_CYAN, tt)}")
        if wide:
            side = _SIDE[i]
            for j, ch in enumerate(side):
                color = C_YEL if ch in "8<>" else (C_RED if ch in "▓" else C_DIM)
                t.append(ch, style=color)
        console.print(t)
    # "Central Operacional de Recortes, Tendencias e EXposicao" com as iniciais destacadas
    full = Text("  ")
    for word in ["Central", "Operacional", "de", "Recortes,", "Tendências", "e", "EXposição"]:
        if word in ("de", "e"):
            full.append(word + " ", style=C_DIM)
        else:
            k = 2 if word.startswith("EX") else 1
            full.append(word[:k], style=f"bold {C_YEL}")
            full.append(word[k:] + " ", style=C_DIM)
    console.print(full)
    console.print(Text("  " + _FILM[:74], style=C_DIM))
    tag = Text("  8<  ", style=f"bold {C_YEL}")
    tag.append("descobre", style="bold white")
    tag.append("  /  ", style=C_DIM)
    tag.append("corta", style="bold white")
    tag.append("  /  ", style=C_DIM)
    tag.append("edita", style="bold white")
    tag.append("  /  ", style=C_DIM)
    tag.append("publica", style="bold white")
    tag.append(f"        v{__version__}", style=C_DIM)
    console.print(tag)
    if subtitle:
        console.print(Text("  " + subtitle, style=C_DIM))
    console.print()


# ------------------------------------------------------------ filtro do terminal
# Regra do dono: o TERMINAL nunca mostra emojis, bolinhas ou travessoes (o video e os posts podem ter emoji).
_TERM_BANNED = {"—": "-", "–": "-", "•": "-", "·": "|", "●": "-"}


def term(s):
    """Limpa um texto antes de ir para o terminal."""
    if isinstance(s, Text):
        cleaned = term(s.plain)
        return s if cleaned == s.plain else Text(cleaned, style=s.style)
    if not isinstance(s, str) or not s:
        return s
    from .util import _EMOJI_RE

    out = s
    for a, b in _TERM_BANNED.items():
        out = out.replace(a, b)
    removed = _EMOJI_RE.sub("", out)
    if removed != out:
        import re

        removed = re.sub(r"(?<=\S) {2,}(?=\S)", " ", removed).rstrip()
    return removed


def rule(title: str = "", color: str = C_CYAN) -> None:
    console.rule(Text(f" {term(title)} ", style=f"bold {color}") if title else "", style=C_DIM)


def ok(msg: str) -> None:
    console.print(Text("  + ", style=f"bold {C_OK}") + Text(term(msg)))
    _log.info(msg)


def info(msg: str) -> None:
    console.print(Text("  > ", style=C_CYAN) + Text(term(msg), style="white"))
    _log.info(msg)


def dim(msg: str) -> None:
    console.print(Text("    " + term(msg), style=C_DIM))


def warn(msg: str) -> None:
    console.print(Text("  ! ", style=f"bold {C_YEL}") + Text(term(msg), style=C_YEL))
    _log.warning(msg)


def err(msg: str) -> None:
    console.print(Text("  x ", style=f"bold {C_RED}") + Text(term(msg), style=C_RED))
    _log.error(msg)


def panel(body: str | Text, title: str = "", color: str = C_CYAN) -> None:
    console.print(Panel(term(body), title=Text(term(title), style=f"bold {color}") if title else None,
                        border_style=color, padding=(1, 2)))


def table(columns: Sequence[str], rows: Iterable[Sequence], title: str | None = None,
          justify: Sequence[str] | None = None, compact: bool = False) -> None:
    """compact=True: uma linha por item (corta com '...' em vez de quebrar)."""
    t = Table(title=term(title), title_style=f"bold {C_CYAN}", header_style=f"bold {C_YEL}",
              border_style=C_DIM, show_lines=False, expand=False)
    cells = [[term(x) if isinstance(x, Text) else term(str(x)) for x in r] for r in rows]
    widths = [max([len(c)] + [len(r[i].plain if isinstance(r[i], Text) else r[i]) for r in cells if i < len(r)])
              for i, c in enumerate(columns)]
    if compact:
        # colunas curtas (numero, nota, duracao) ficam inteiras; as longas dividem o que sobra e cortam com "..."
        short = [w if w <= 16 else 0 for w in widths]
        n_long = sum(1 for w in widths if w > 16) or 1
        room = console.width - 3 * len(columns) - 1 - sum(short)
        long_w = max(10, room // n_long)
        widths = [w if w <= 16 else min(w, long_w) for w in widths]
    for i, c in enumerate(columns):
        t.add_column(term(c), justify=(justify[i] if justify and i < len(justify) else "left"),
                     overflow="ellipsis" if compact else "fold", no_wrap=compact,
                     width=widths[i] if compact else None)
    for r in cells:
        if compact:
            r = [Text(x.plain, style=x.style, overflow="ellipsis", no_wrap=True) if isinstance(x, Text) else x for x in r]
        t.add_row(*r)
    console.print(t)


def score_text(score: float) -> Text:
    s = int(round(score or 0))
    color = C_OK if s >= 75 else (C_YEL if s >= 55 else C_RED)
    bar = "█" * (s // 10) + "░" * (10 - s // 10)
    return Text(f"{bar} {s:3d}", style=color)


# ------------------------------------------------------------------ perguntas
def ask_text(question: str, default: str = "") -> str:
    try:
        import questionary

        ans = questionary.text(term(question), default=default).ask()
        return (ans if ans is not None else "").strip()
    except Exception:
        ans = input(f"{question} [{default}] ").strip()
        return ans or default


def ask_confirm(question: str, default: bool = True) -> bool:
    try:
        import questionary

        ans = questionary.confirm(term(question), default=default).ask()
        return bool(ans) if ans is not None else False
    except Exception:
        ans = input(f"{question} [{'S/n' if default else 's/N'}] ").strip().lower()
        return default if not ans else ans.startswith("s") or ans.startswith("y")


def ask_select(question: str, choices: list[tuple[str, str]], default: str | None = None) -> str | None:
    """choices: lista de (valor, rotulo)."""
    try:
        import questionary

        qc = [questionary.Choice(title=term(label), value=value) for value, label in choices]
        return questionary.select(term(question), choices=qc, default=default, use_shortcuts=len(qc) <= 36,
                                  instruction=" (setas + Enter)").ask()
    except Exception:
        for i, (_, label) in enumerate(choices, 1):
            console.print(f"  {i}) {label}")
        ans = input(f"{question} ").strip()
        try:
            return choices[int(ans) - 1][0]
        except Exception:
            return None


def ask_checkbox(question: str, choices: list[tuple[str, str, bool]]) -> list[str]:
    """choices: (valor, rotulo, marcado)."""
    try:
        import questionary

        qc = [questionary.Choice(title=term(label), value=value, checked=checked) for value, label, checked in choices]
        ans = questionary.checkbox(term(question), choices=qc, instruction=" (espaco marca, a = todos, Enter confirma)").ask()
        return ans or []
    except Exception:
        for i, (_, label, _c) in enumerate(choices, 1):
            console.print(f"  {i}) {label}")
        ans = input(f"{question} (numeros separados por virgula, ou 'todos') ").strip().lower()
        if ans in ("todos", "t", "all"):
            return [v for v, _, _ in choices]
        out = []
        for p in ans.split(","):
            try:
                out.append(choices[int(p.strip()) - 1][0])
            except Exception:
                pass
        return out


def pause(msg: str = "Pressione Enter para voltar ao menu...") -> None:
    try:
        console.input(Text(f"\n  {msg}", style=C_DIM))
    except (EOFError, KeyboardInterrupt):
        pass


# ------------------------------------------------------------------ reporter
class Reporter:
    """Recebe eventos da esteira e mostra no terminal (ou so no log, se quiet)."""

    def __init__(self, quiet: bool = False):
        self.quiet = quiet
        self.t0 = time.time()
        self._status = None

    def _elapsed(self) -> str:
        s = int(time.time() - self.t0)
        return f"{s // 60:02d}:{s % 60:02d}"

    def stage(self, n: int, total: int, title: str) -> None:
        _log.info("ETAPA %s/%s: %s", n, total, title)
        if not self.quiet:
            console.print()
            rule(f"[{n}/{total}] {title}  |  {self._elapsed()}")

    def info(self, msg: str) -> None:
        if self.quiet:
            _log.info(msg)
        else:
            info(msg)

    def ok(self, msg: str) -> None:
        if self.quiet:
            _log.info(msg)
        else:
            ok(msg)

    def warn(self, msg: str) -> None:
        if self.quiet:
            _log.warning(msg)
        else:
            warn(msg)

    def error(self, msg: str) -> None:
        if self.quiet:
            _log.error(msg)
        else:
            err(msg)

    def dim(self, msg: str) -> None:
        if self.quiet:
            _log.debug(msg)
        else:
            dim(msg)

    @contextlib.contextmanager
    def working(self, msg: str):
        """Spinner enquanto algo demorado roda."""
        _log.info("... %s", msg)
        if self.quiet:
            yield
            return
        with console.status(Text(f" {term(msg)}", style="white"), spinner="line", spinner_style=C_CYAN):
            yield
