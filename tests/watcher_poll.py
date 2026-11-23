"""Teste do vigia da via rapida contra os sites de verdade (sem login, nada baixado em disco).

Uso (na raiz do projeto):
    .venv\\Scripts\\python.exe tests\\watcher_poll.py              # uma leitura com a config real
    .venv\\Scripts\\python.exe tests\\watcher_poll.py --sensivel   # gatilhos baixos (para ver algo disparar)
    .venv\\Scripts\\python.exe tests\\watcher_poll.py --duas       # duas leituras seguidas (dedupe)

Mostra o que achou e por que, o tempo da leitura, e confere os campos que o orquestrador usa.
O modo --sensivel usa um arquivo de estado temporario (nao suja data/estado/vigia.json).
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

from fabrica import watcher  # noqa: E402
from fabrica.config import load_config  # noqa: E402
from fabrica.discovery import historico  # noqa: E402
from fabrica.util import fmt_duration  # noqa: E402

FAILS: list[str] = []


class _Cfg:
    """Config real com algumas chaves trocadas."""

    def __init__(self, base, over: dict):
        self.base, self.over = base, over

    def get(self, key, default=None):
        return self.over[key] if key in self.over else self.base.get(key, default)


def check(cond: bool, msg: str) -> None:
    print(("  ok   " if cond else "  FALHA ") + msg)
    if not cond:
        FAILS.append(msg)


def show(cands) -> None:
    for c in cands:
        ex = c.extra
        jan = ex.get("janela")
        jtxt = f"janela {fmt_duration(jan[0])}-{fmt_duration(jan[1])}" if jan else "janela: o proprio clipe/video"
        print(f"  [{c.platform}] {c.channel} | {c.title[:60]}")
        print(f"      motivo: {ex.get('motivo_via_rapida')} | nota {c.score} | {jtxt}")
        print(f"      {c.id} -> {c.url} | duracao {c.duration} | sat {ex.get('saturacao', {}).get('canais', '-')}")
        check(bool(c.id and c.url and c.platform and c.title is not None and c.channel), f"campos de {c.id}")
        check(ex.get("via_rapida") is True and bool(ex.get("motivo_via_rapida")), f"via_rapida/motivo de {c.id}")
        if jan:
            check(len(jan) == 2 and 0 <= jan[0] < jan[1], f"janela valida em {c.id}")


def main() -> int:
    cfg = load_config()
    if "--sensivel" in sys.argv:
        tmp = ROOT / "work" / "tmp" / "vigia_teste.json"
        tmp.parent.mkdir(parents=True, exist_ok=True)
        tmp.unlink(missing_ok=True)
        watcher.STATE_FILE = tmp
        cfg = _Cfg(cfg, {"busca.via_rapida.twitch_views_min": 150, "busca.via_rapida.twitch_idade_max_h": 24,
                         "busca.via_rapida.kick_views_min": 300, "busca.via_rapida.yt_vph_min": 1500,
                         "busca.via_rapida.yt_idade_max_h": 24, "busca.via_rapida.max_resultados": 8})
        print("modo sensivel: gatilhos baixos e estado temporario")
    rounds = 2 if "--duas" in sys.argv or "--sensivel" in sys.argv else 1
    first_ids: set[str] = set()
    for i in range(rounds):
        print(f"\n=== leitura {i + 1}")
        t = time.time()
        cands = watcher.poll(cfg)
        dt = time.time() - t
        print(f"  {len(cands)} momento(s) em {dt:.1f}s | ultimo: {watcher.last_status()}")
        show(cands)
        check(dt < 75, f"leitura em {dt:.1f}s (< 75 s)")
        ids = {c.extra.get('vigia_ts') and c.id + str(c.extra.get('janela')) for c in cands}
        if i == 0:
            first_ids = ids
        else:
            check(not (ids & first_ids), "segunda leitura nao repete os mesmos momentos")
    d = historico._load()
    print(f"\n  historico de canais: {len(d['canais'])} canais, {len(d['alias'])} apelidos")
    if "--sensivel" in sys.argv:
        watcher.STATE_FILE.unlink(missing_ok=True)
    print("\nRESULTADO:", "tudo ok" if not FAILS else f"{len(FAILS)} falha(s): " + "; ".join(FAILS))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
