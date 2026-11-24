"""Testes rapidos das partes da esteira que nao dependem de rede."""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fabrica import pipeline  # noqa: E402
from fabrica.models import ClipPlan  # noqa: E402


def plan(i, s, e, score=70):
    return ClipPlan(id=f"c{i}", source_id="youtube:x", start=s, end=e, title=f"t{i}", score=score)


def test_group_plans():
    ps = [plan(1, 100, 160), plan(2, 160, 220), plan(3, 500, 560), plan(4, 563, 600)]
    g = pipeline._group_plans(ps, pad=1.5, dur=590)
    assert len(g) == 2, g
    assert g[0][0] == 98.5 and g[0][1] == 221.5 and len(g[0][2]) == 2
    assert g[1][1] == 590 and len(g[1][2]) == 2  # cortado na duracao do video
    print("ok group_plans")


def test_lock():
    assert pipeline._pid_alive(os.getpid())
    assert not pipeline._pid_alive(999999)
    with pipeline.RunLock():
        try:
            with pipeline.RunLock():
                raise AssertionError("deveria bloquear")
        except RuntimeError:
            pass
    assert not pipeline.LOCK.exists()
    print("ok lock")


def test_publish_order():
    from fabrica.models import RenderedClip

    def rc(i, score, part=None, series=None):
        p = plan(i, 0, 30, score)
        p.part, p.series = part, series
        return RenderedClip(plan=p, path=f"{i}.mp4", duration=30, layout="split")

    clips = [rc(1, 60), rc(2, 70, 2, "s"), rc(3, 90, 1, "s"), rc(4, 80)]
    order = [c.plan.id for c in pipeline.publish_order(clips)]
    assert order == ["c3", "c2", "c4", "c1"], order
    print("ok publish_order")


def test_candidatos():
    f = pipeline.pedir_candidatos
    # limite de 4 por canal (caso real): video longo pede mais do que edita; curto e sem Claude pedem so o que editam
    assert (f(91, 4, "claude"), f(203, 4, "claude"), f(49, 4, "claude")) == (8, 8, 6), (f(91, 4, "claude"), f(49, 4, "claude"))
    assert (f(12, 4, "claude"), f(91, 4, "ollama"), f(91, 10, "claude"), f(91, 1, "claude")) == (4, 4, 10, 8)
    from fabrica.brain import prompts
    assert prompts.candidatos(91, f(91, 4, "claude")) == (5, 8) and prompts.candidatos(49, f(49, 4, "claude")) == (3, 6)

    def c(i, nota, part=None, series=None):
        p = plan(i, i * 100, i * 100 + 40, 50)
        p.editor, p.part, p.series = {"nota": nota}, part, series
        return p

    ps = [c(1, 70), c(2, 80, 1, "s"), c(3, 64, 2, "s"), c(4, 75), c(5, 66), c(6, 90)]
    assert {p.id for p in pipeline.os_melhores(ps, 4)} == {"c6", "c2", "c3", "c4"}
    assert {p.id for p in pipeline.os_melhores(ps, 2)} == {"c6", "c4"}                    # serie so entra inteira
    assert [p.id for p in pipeline.os_melhores(ps, 9)] == [p.id for p in ps]
    serie = [c(1, 80, 1, "s"), c(2, 70, 2, "s"), c(3, 70, 3, "s")]
    assert [p.id for p in pipeline.os_melhores(serie, 2)] == ["c1", "c2"]
    print("ok candidatos")


if __name__ == "__main__":
    test_group_plans()
    test_lock()
    test_publish_order()
    test_candidatos()
    print("TUDO OK")
