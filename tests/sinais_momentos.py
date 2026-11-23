"""Teste dos sinais de momento contra os sites de verdade (sem login).

Uso (na raiz do projeto):
    .venv\\Scripts\\python.exe tests\\sinais_momentos.py                 # escolhe videos sozinho
    .venv\\Scripts\\python.exe tests\\sinais_momentos.py --yt <id> --twitch <vod_id> --ytlive <id>
    .venv\\Scripts\\python.exe tests\\sinais_momentos.py --offline        # so parser/cluster/picos

Faz: parser de horarios (offline) -> comentarios top de um podcast popular (comment_marks) ->
chat de um VOD da Twitch (chat_spikes) -> chat de uma live gravada do YouTube -> resumo de sinais
para o prompt -> janelas do cerebro heuristico (sem transcricao) . Nada e baixado em disco.
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

from fabrica import download, signals  # noqa: E402
from fabrica.config import load_config  # noqa: E402
from fabrica.discovery import momentos, twitch_gql  # noqa: E402
from fabrica.discovery import youtube as yt  # noqa: E402
from fabrica.models import Candidate  # noqa: E402

FAILS: list[str] = []


def check(cond: bool, msg: str) -> None:
    print(("  ok   " if cond else "  FALHA ") + msg)
    if not cond:
        FAILS.append(msg)


def arg(name: str) -> str | None:
    if name in sys.argv:
        i = sys.argv.index(name)
        return sys.argv[i + 1] if i + 1 < len(sys.argv) else None
    return None


def offline() -> None:
    print("\n=== parser de horarios e cluster (offline)")
    p = momentos.parse_timestamps
    check([t for t, _ in p("19:27 a transicao kkkk")] == [1167.0], "19:27")
    check([t for t, _ in p("1:02:03 melhor parte")] == [3723.0], "1:02:03")
    check(p("dia 12/11 as 20h") == [], "data e hora nao contam")
    check(abs(p("aos 5 minutos ele chorou")[0][0] - 330) < 1, "aos 5 minutos")
    check(abs(p("no minuto 12 kkkk")[0][0] - 750) < 1, "no minuto 12")
    check([t for t, _ in p("1h02 que isso")] == [3720.0], "1h02")
    check(p("99:99") == [], "horario invalido")
    ms = [(100, 1.0, "a"), (120, 2.0, "b"), (150, 1.0, "c"), (900, 1.0, "d"), (2000, 6.0, "e")]
    cl = momentos.cluster_marks(ms)
    check(len(cl) == 2 and {round(c["t"]) for c in cl} >= {2000}, f"clusters {cl}")
    samples = [{"t": i * 30.0, "msgs": 10.0 + (i % 3), "riso": 0.05} for i in range(60)]
    samples[20] = {"t": 600.0, "msgs": 45.0, "riso": 0.6}
    sp, st = momentos.find_spikes(samples)
    check(bool(sp) and sp[0]["t"] == 600.0 and sp[0]["z"] >= 3, f"pico de chat {sp[:1]} base {st}")


def pick_youtube_podcast() -> str | None:
    for h in ("@flowpodcast", "@podpah", "@InteligenciaLtda"):
        items, _ = yt.channel_tab(h, "videos", 12)
        items = [i for i in items if (i.get("duration") or 0) > 1200 and (i.get("views") or 0) > 100_000]
        if items:
            best = max(items, key=lambda i: i.get("views") or 0)
            print(f"  podcast escolhido: {best['channel']} | {best['title'][:60]} ({best['views']} views)")
            return best["id"]
    return None


def comments(vid: str) -> Candidate | None:
    print(f"\n=== comentarios top do YouTube ({vid})")
    cfg = load_config()
    c = Candidate(id=f"youtube:{vid}", platform="youtube", url=f"https://www.youtube.com/watch?v={vid}", title="")
    t = time.time()
    download.enrich_candidate(c, cfg)
    dt = time.time() - t
    ci = c.extra.get("comentarios_info") or {}
    print(f"  {c.title[:70]} | {c.duration}s | heatmap: {len(c.extra.get('heatmap') or [])} pontos")
    print(f"  comentarios lidos {ci.get('lidos')}, com horario {ci.get('com_tempo')}, em {ci.get('tempo_s')}s "
          f"(enriquecimento total {dt:.1f}s)")
    for m in c.extra.get("comment_marks") or []:
        print(f"   [{signals._fmt(m['t'])}] peso {m['peso']:.1f}, {m['n']} mencoes: {m['exemplo'][:80]}")
    check("comment_marks" in c.extra, "comment_marks preenchido")
    check(dt < 40, f"tempo do enriquecimento {dt:.1f}s < 40s")
    return c


def twitch(vod: str | None) -> Candidate | None:
    cfg = load_config()
    if not vod:
        info = twitch_gql.channels_clips(["cellbit", "felps", "gaules"])
        for lg, d in info.items():
            for cl in d["clipes_dia"]:
                if cl.get("vod_id"):
                    vod = cl["vod_id"]
                    print(f"  VOD escolhido de {lg}: {vod}")
                    break
            if vod:
                break
    if not vod:
        print("  nenhum VOD recente encontrado; pulando")
        return None
    print(f"\n=== chat do VOD da Twitch ({vod})")
    acc = twitch_gql.vod_accessible(vod)
    print(f"  VOD baixa sem login? {acc}")
    c = Candidate(id=f"twitch:v{vod}", platform="twitch", url=f"https://www.twitch.tv/videos/{vod}", title="")
    t = time.time()
    try:
        download.enrich_candidate(c, cfg)
    except Exception as e:  # noqa: BLE001  VOD so para inscritos: o chat continua legivel
        print(f"  enriquecimento falhou ({str(e)[:90]}); lendo so o chat")
        q = 'query { video(id: "%s") { title lengthSeconds } }' % vod
        data, _ = twitch_gql.gql(q)
        v = (data or {}).get("video") or {}
        c.title, c.duration = v.get("title") or "", float(v.get("lengthSeconds") or 0)
        r = momentos.chat_spikes(c, cfg, {"id": f"v{vod}", "duration": c.duration})
        if r is not None:
            c.extra["chat_spikes"] = r["spikes"]
            c.extra["chat_info"] = {k: x for k, x in r.items() if k != "spikes"}
    dt = time.time() - t
    ch = c.extra.get("chat_info") or {}
    print(f"  {c.title[:70]} | {c.duration}s")
    print(f"  chat: {ch}")
    for s in c.extra.get("chat_spikes") or []:
        print(f"   [{signals._fmt(s['t'])}] z {s['z']}, {s['msgs']} msgs/10s, riso {s['riso']}")
    check("chat_spikes" in c.extra, "chat_spikes preenchido")
    check(dt < 40, f"tempo {dt:.1f}s < 40s")
    check((ch.get("mb") or 0) <= 30, "baixou no maximo 30 MB")
    return c


def ytlive(vid: str | None) -> Candidate | None:
    cfg = load_config()
    if not vid:
        for h in ("@podpah", "@flowpodcast", "@CellbitLives"):
            items, _ = yt.channel_tab(h, "streams", 8)
            items = [i for i in items if i.get("was_live") and (i.get("duration") or 0) > 1800]
            if items:
                vid = items[0]["id"]
                print(f"  live escolhida: {items[0]['channel']} | {items[0]['title'][:60]}")
                break
    if not vid:
        print("  nenhuma live gravada encontrada; pulando")
        return None
    print(f"\n=== chat de live gravada do YouTube ({vid})")
    c = Candidate(id=f"youtube:{vid}", platform="youtube", url=f"https://www.youtube.com/watch?v={vid}", title="")
    t = time.time()
    download.enrich_candidate(c, cfg)
    dt = time.time() - t
    print(f"  {c.title[:70]} | {c.duration}s | chat: {c.extra.get('chat_info')}")
    for s in c.extra.get("chat_spikes") or []:
        print(f"   [{signals._fmt(s['t'])}] z {s['z']}, {s['msgs']} msgs/10s, riso {s['riso']}")
    for m in (c.extra.get("comment_marks") or [])[:5]:
        print(f"   comentario [{signals._fmt(m['t'])}] peso {m['peso']:.1f}, {m['n']}x: {m['exemplo'][:70]}")
    check("chat_spikes" in c.extra, "chat_spikes (YouTube) preenchido")
    check(dt < 45, f"tempo {dt:.1f}s < 45s")
    return c


def use_signals(c: Candidate) -> None:
    print(f"\n=== sinais no prompt / cerebro heuristico ({c.id})")
    from fabrica.brain.heuristic import HeuristicBrain
    from fabrica.models import Segment, Transcript

    sig = signals.compute_signals(c, None, duration=c.duration)
    print("  " + signals.summarize_for_prompt(sig, max_items=6).replace("\n", "\n  "))
    marks = (c.extra.get("comment_marks") or []) + (c.extra.get("chat_spikes") or [])
    if marks:
        check(any(k in sig.available for k in ("comentarios", "chat")), "comentarios/chat entram nos sinais")
        # transcricao falsa (fala continua) so para ver se as janelas caem nos momentos citados
        dur = float(c.duration or 600)
        segs = [Segment(t, t + 4.5, "e ai mano olha isso que coisa") for t in range(0, int(dur) - 5, 5)]
        cfg = load_config()
        wins = HeuristicBrain(cfg).candidate_windows(c, Transcript(segs, "pt", "whisper"), cfg, max_clips=3)
        for w in wins[:5]:
            print(f"   janela {signals._fmt(w['start'])}-{signals._fmt(w['end'])} nota {w['score']}: {w['reason'][:90]}")
        tops = [m["t"] for m in marks]
        hit = any(any(w["start"] - 40 <= t <= w["end"] + 40 for t in tops) for w in wins[:3])
        check(hit, "o cerebro heuristico escolheu janela perto de um momento citado/pico de chat")


def main() -> int:
    offline()
    if "--offline" in sys.argv:
        return 1 if FAILS else 0
    yid = arg("--yt") or pick_youtube_podcast()
    c1 = comments(yid) if yid else None
    c2 = twitch(arg("--twitch"))
    c3 = ytlive(arg("--ytlive")) if "--sem-ytlive" not in sys.argv else None
    for c in (c1, c2, c3):
        if c is not None:
            use_signals(c)
    print("\nRESULTADO:", "tudo ok" if not FAILS else f"{len(FAILS)} falha(s): " + "; ".join(FAILS))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
