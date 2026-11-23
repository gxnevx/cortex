"""Logging: arquivo diario em logs/ + (opcional) saida bonita no terminal."""
from __future__ import annotations

import logging
from datetime import datetime

from . import paths

_CONFIGURED = False
# Sem isso, avisos sairiam duplicados no terminal quando o log ainda nao foi configurado
logging.getLogger("fabrica").addHandler(logging.NullHandler())


class DailyFile(logging.Handler):
    """logs/fabrica_AAAAMMDD.log: troca de arquivo a meia-noite e apaga os com mais de 14 dias."""

    def __init__(self) -> None:
        super().__init__()
        self._day, self._fh = "", None

    def emit(self, record: logging.LogRecord) -> None:
        try:
            day = f"{datetime.now():%Y%m%d}"
            if day != self._day:
                if self._fh:
                    self._fh.close()
                paths.LOGS.mkdir(parents=True, exist_ok=True)
                self._fh = (paths.LOGS / f"fabrica_{day}.log").open("a", encoding="utf-8")
                self._day = day
                for old in sorted(paths.LOGS.glob("fabrica_*.log"))[:-14]:
                    old.unlink(missing_ok=True)
            self._fh.write(self.format(record) + "\n")
            self._fh.flush()
        except Exception:
            pass


def setup(verbose: bool = False, console: bool = True) -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return
    paths.LOGS.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger("fabrica")
    root.setLevel(logging.DEBUG)
    fh = DailyFile()
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s", "%H:%M:%S"))
    root.addHandler(fh)
    root.propagate = False  # evita o handler padrao do Python imprimir avisos no terminal
    # Sem --verbose, a interface (ui.py) ja mostra o que importa; o log vai so para o arquivo.
    if console and verbose:
        try:
            from rich.logging import RichHandler

            ch: logging.Handler = RichHandler(show_path=False, rich_tracebacks=False, markup=False,
                                              show_time=False, show_level=True)
        except Exception:  # pragma: no cover
            ch = logging.StreamHandler()
        ch.setLevel(logging.DEBUG if verbose else logging.WARNING)
        root.addHandler(ch)
    _CONFIGURED = True


def get(name: str) -> logging.Logger:
    if not name.startswith("fabrica"):
        name = f"fabrica.{name}"
    return logging.getLogger(name)
