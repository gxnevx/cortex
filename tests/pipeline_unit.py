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


if __name__ == "__main__":
    test_group_plans()
    test_lock()
    test_publish_order()
    print("TUDO OK")
