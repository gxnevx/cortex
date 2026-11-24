"""Instagram: cortes so dele, cronograma, regras e leitura de numeros. Sem navegador e sem internet.

Roda:  .venv\\Scripts\\python.exe tests\\instagram_unit.py
"""
from __future__ import annotations

import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from fabrica import paths  # noqa: E402

TMP = Path(tempfile.mkdtemp(prefix="cortex_ig_"))
paths.DB_PATH = TMP / "t.db"
paths.STATE = TMP
from fabrica import autopilot, cronograma, db, exclusivas, metrics, numeros, policy, revisao, storage  # noqa: E402
from fabrica.config import Config  # noqa: E402
from fabrica.models import ClipPlan, PostResult, RenderedClip  # noqa: E402
from fabrica.publish import captions, guard, instagram  # noqa: E402
import fabrica.pipeline as pipeline  # noqa: E402
import fabrica.publish as publish  # noqa: E402

guard._state_dir = lambda: TMP
storage.release_published = lambda *a, **k: "mantido"
revisao.filtrar = lambda clips, cfg: (clips, False)     # a revisao tem o teste dela (revisao_unit.py)
fails: list[str] = []


def check(name: str, cond: bool, extra: object = "") -> None:
    print(("ok    " if cond else "FALHA ") + name + (f"  [{extra}]" if extra and not cond else ""))
    if not cond:
        fails.append(name)


cfg = Config({"publicacao": {"plataformas": ["youtube", "tiktok", "instagram"], "redes_exclusivas": ["instagram"],
                             "max_posts_por_dia": {"youtube": 3, "tiktok": 3, "instagram": 2}, "aquecimento": {"ativo": False},
                             "intervalo_minimo_min": {"youtube": 150, "tiktok": 90, "instagram": 240},
                             "contas": {"instagram": {"handle": "@canal.teste"}}, "creditar_fonte": True},
              "estrategia": {"decide_quantidade": False}, "autopiloto": {"fila_maxima": 12, "estoque_dias": 2.5}})


def clip(i: int, score: float = 70, cat: str = "podcast", part: int | None = None, dur: float = 50, src: str | None = None) -> RenderedClip:
    f = TMP / f"c{i}.mp4"
    f.write_bytes(b"x")
    p = ClipPlan(id=f"c{i}", source_id=src or f"s{i}", start=0, end=dur, title=f"Corte {i}", hook="", description="", hashtags=["games"])
    p.score, p.category, p.part, p.parts_total, p.series = score, cat, part, (3 if part else None), ("x" if part else None)
    return RenderedClip(plan=p, path=str(f), duration=dur, layout="full", variants={"youtube": str(f), "tiktok": str(TMP / "tt.mp4")})


# ------------------------------------------------------------------ arquivo e texto
c = clip(0)
check("Instagram usa a versao com o @ do TikTok", c.path_for("instagram").endswith("tt.mp4") and c.path_for("youtube").endswith("c0.mp4"))
c.variants["instagram"] = "ig.mp4"
check("versao propria vale mais", c.path_for("instagram") == "ig.mp4")
_, leg = captions.build_post_text(clip(1).plan, "instagram", cfg, video_title="x", channel="@canalfonte")
check("legenda sem marcar @ de outra rede", "@" not in leg, leg)
check("legenda com no maximo 2200", len(leg) <= 2200)

# ------------------------------------------------------------------ escolha
fila = [clip(1, 82, "entretenimento", part=2), clip(2, 80, "politica"), clip(3, 74, "games"), clip(4, 74, "polemica"), clip(5, 70, "noticias")]
vazio = {x.plan.id: set() for x in fila}
e = exclusivas.escolher("instagram", cfg, fila, ja=vazio, fontes=[])
check("pega avulso do jeito da rede, nunca parte de serie", e.plan.id == "c3", e and e.plan.id)
check("nao pega quando so sobra o das outras redes", exclusivas.escolher("instagram", cfg, fila[:3], ja=vazio, fontes=[]) is None)
ja = dict(vazio, c3={"youtube"})
check("nao repete o que ja saiu em outra rede", exclusivas.escolher("instagram", cfg, fila, ja=ja, fontes=[]).plan.id != "c3")
check("varia a fonte", exclusivas.nota(fila[2], ["s3"]) < exclusivas.nota(fila[2], []))
falso = clip(6, 74, "games")
falso.plan.title = "STM gastou 1 milhão no Japão"
check("assunto politico com categoria errada perde", exclusivas.nota(falso) < exclusivas.nota(clip(7, 70, "podcast")), exclusivas.nota(falso))
check("conjunto e exclusivas", exclusivas.conjunto(cfg) == ["youtube", "tiktok"] and exclusivas.redes(cfg) == ["instagram"])
check("capacidade soma a rede exclusiva", autopilot.capacity(cfg) == 5, autopilot.capacity(cfg))
guard.pause_platform("instagram", "teste", hours=1)
check("rede parada nao puxa producao", autopilot.capacity(cfg) == 3)
guard.clear_pause("instagram")

# ------------------------------------------------------------------ cronograma
grande = [clip(i, 90 - i, ["games", "polemica", "humor", "podcast"][i % 4], src=f"f{i % 5}") for i in range(10, 24)]
cr = cronograma.montar(cfg, 4, fila=grande)
fut = [x for x in cr if not x["feito"]]
ig = {x["clip_id"] for x in fut if x["rede"] == "instagram" and x["clip_id"]}
ou = {x["clip_id"] for x in fut if x["rede"] != "instagram" and x["clip_id"]}
check("cronograma: nenhum corte repetido entre Instagram e as outras", ig and ou and not (ig & ou), (ig, ou))
check("cronograma: cada rede no maximo uma vez por corte", len({(x["rede"], x["clip_id"]) for x in fut if x["clip_id"]}) == sum(bool(x["clip_id"]) for x in fut))
dias: dict = {}
for x in fut:
    dias.setdefault((time.strftime("%d", time.localtime(x["ts"])), x["rede"]), []).append(x["ts"])
amanha = {r: len(v) for (d, r), v in dias.items() if d == time.strftime("%d", time.localtime(time.time() + 86400))}
check("cronograma: 3 YouTube, 3 TikTok e 2 Instagram por dia", amanha == {"youtube": 3, "tiktok": 3, "instagram": 2}, amanha)
check("cronograma: respeita o intervalo", all(b - a >= policy.min_interval_s(r, cfg) - 1 for (d, r), v in dias.items() for a, b in zip(sorted(v), sorted(v)[1:])))

# ------------------------------------------------------------------ o corte do Instagram nao vai para as outras redes
status: dict[str, str] = {}
db.set_clip_status = lambda i, s: status.__setitem__(i, s)
mandou: list = []


class Rep:
    def __getattr__(self, n):
        return lambda *a, **k: None


publish.check_login = lambda p, cfg=None, deep=False: True
resposta = {"ok": True, "error": None}


def lote(clips, cfg, platforms=None, dry_run=False, on_event=None):
    out = []
    for x in clips:
        for p in platforms:
            mandou.append((x.plan.id, p))
            r = PostResult(x.plan.id, p, resposta["ok"], url="u", error=resposta["error"], ts=time.time())
            db.save_post(r)
            out.append(r)
    return out


publish.publish_batch = lote
pipeline.publish_clips(cfg, [fila[2]], False, Rep(), only=["instagram"])
check("saiu no Instagram: terminou ali", mandou == [("c3", "instagram")] and status.get("c3") == "publicado", (mandou, status))
check("e de exclusiva: as outras redes pulam", exclusivas.e_de_exclusiva("c3", cfg) and not exclusivas.e_de_exclusiva("c4", cfg))
mandou.clear()
db.conn().execute("DELETE FROM posts")
pipeline.publish_clips(cfg, [fila[3]], False, Rep())
check("sem pedir rede: so YouTube e TikTok", {p for _, p in mandou} == {"youtube", "tiktok"} and status.get("c4") == "publicado", (mandou, status))
resposta.update(ok=False, error="Falha no Instagram: x")
pipeline.publish_clips(cfg, [fila[4]], False, Rep(), only=["instagram"])
check("falhou no Instagram: volta para a fila", "c5" not in status, status)
check("falhou: nao conta como do Instagram", not exclusivas.e_de_exclusiva("c5", cfg))
resposta.update(ok=True, error="INCERTO: cliquei")
pipeline.publish_clips(cfg, [fila[1]], False, Rep(), only=["instagram"])
check("sem confirmacao: sai da fila e nao vai para as outras", status.get("c2") == "publicado" and exclusivas.e_de_exclusiva("c2", cfg))

# ------------------------------------------------------------------ pausa, numeros e links
a = guard.pause_platform("instagram", "aviso", hours=168)
b = guard.pause_platform("instagram", "outra", hours=24)
check("pausa longa nao encurta", abs(a - b) < 2 and "aviso" in guard.paused_until("instagram")[1])
guard.clear_pause("instagram")
check("numeros do cartao", numeros.parse_instagram("42,4 M", "120\xa0mil\n2391") == {"views": 42.4e6, "likes": 120e3, "comments": 2391.0},
      numeros.parse_instagram("42,4 M", "120\xa0mil\n2391"))
check("sem numero ainda", numeros.parse_instagram("", "")["views"] is None)
u = instagram.reel_link("canal.teste", "DgF28H6PcXh")
check("id pelo link", metrics.video_id_from_url("instagram", u) == "DgF28H6PcXh" and metrics.normalize_video_url("instagram", u).endswith("/reel/DgF28H6PcXh/"))
db.conn().execute("DELETE FROM posts")
db.save_post(PostResult("c3", "instagram", True, url=u, ts=time.time() - 3 * 3600))
check("yt-dlp nao tenta ler o Instagram", all(x["platform"] != "instagram" for x in metrics.due_items(cfg)))
check("leitura do perfil pega o post", [x["platform"] for x in numeros.due(cfg)] == ["instagram"])

# ------------------------------------------------------------------ avisos da rede
check("aviso de automacao", bool(instagram.AUTO_RE.search("Suspeitamos de comportamento automatizado na tua conta")
                                 and instagram.AUTO_RE.search("We suspect automated behavior on your account")))
check("confirmacao em 3 idiomas", all(instagram.SUCCESS_RE.search(t) for t in
      ("O teu reel foi partilhado.", "Seu reel foi compartilhado.", "Your reel has been shared.", "Reel partilhado")))
check("aviso antes do envio nao e confirmacao", not instagram.SUCCESS_RE.search("O teu reel vai ser partilhado com os teus seguidores"))
check("limite da rede", bool(instagram.RATE_RE.search("Tenta novamente mais tarde") and instagram.RATE_RE.search("Ação bloqueada")))

# ------------------------------------------------------------------ PC que acorda tarde: folga de 20 min depois da janela (caso real de 24/11)
from datetime import date, datetime  # noqa: E402
from types import SimpleNamespace  # noqa: E402


def em(hm: str) -> float:
    h, m = hm.split(":")
    d = date.today()
    return datetime(d.year, d.month, d.day, int(h), int(m)).timestamp()


guarda = (policy._slot_times, policy.last_post_ts, policy.time, policy.db.posts_today, policy.effective_limit, cronograma.time)
policy._slot_times = lambda p, c, d: [(em(x), em(y)) for x, y in (("20:15", "21:45"), ("10:46", "12:00"), ("14:47", "15:30"), ("23:17", "23:50"), ("17:20", "18:10"))]
policy.effective_limit = lambda p, c: 3


def agora(hm: str, ultimo: str, feitos: int) -> tuple[bool, list[str]]:
    policy.time = cronograma.time = SimpleNamespace(time=lambda: em(hm))
    policy.last_post_ts = lambda p: em(ultimo)
    policy.db.posts_today = lambda p: feitos
    return policy.slot_due("tiktok", cfg), [datetime.fromtimestamp(x).strftime("%H:%M") for x in cronograma.horarios("tiktok", cfg, date.today())]


try:
    for hm, feitos, quer in (("14:30", 1, (False, ["14:47", "20:15"])), ("15:10", 1, (True, ["15:10", "20:15"])),
                             ("15:41", 1, (True, ["15:41", "20:15"])), ("15:51", 1, (False, ["20:15", "23:17"]))):
        r = agora(hm, "10:47", feitos)
        check(f"folga: as {hm} com o horario das 14:47 pendente", r == quer, r)
    r = agora("15:43", "15:42", 2)
    check("folga: postou atrasado, nao posta de novo na mesma janela", r == (False, ["20:15"]), r)
    r = agora("15:43", "15:42", 3)
    check("folga: limite do dia continua valendo", r == (False, []), r)
finally:
    policy._slot_times, policy.last_post_ts, policy.time, policy.db.posts_today, policy.effective_limit, cronograma.time = guarda

print("\n" + ("TUDO OK" if not fails else "FALHAS: " + ", ".join(fails)))
sys.exit(1 if fails else 0)
