"""collect_trends: roda as fontes em paralelo, junta assuntos parecidos e da uma nota 0-100."""
from __future__ import annotations

import concurrent.futures as cf
import time
from dataclasses import dataclass, field

from .. import log
from ..models import Trend
from . import sources as S
from .text import contains_topic, norm, short_query, similarity, tokens


def _key(s: str) -> str:
    """Chave canonica: palavras relevantes (sem 'x', 'vs', 'de'...)."""
    return " ".join(tokens(s)) or norm(s)

_log = log.get(__name__)


@dataclass
class _Cluster:
    items: list[S.RawTrend] = field(default_factory=list)
    keys: set[str] = field(default_factory=set)        # topicos normalizados (+ relacionados do Google)
    headlines: list[S.RawTrend] = field(default_factory=list)

    @property
    def main(self) -> S.RawTrend:
        return max(self.items, key=lambda t: S.SOURCE_WEIGHT.get(t.source, 0.5) * t.s)

    def all_items(self) -> list[S.RawTrend]:
        return self.items + self.headlines


def _enabled_sources(cfg) -> list[str]:
    fontes = cfg.get("busca.fontes", {}) or {}
    return [name for name in S.SOURCES if fontes.get(name, True)]


def _run_sources(cfg, names: list[str]) -> dict[str, list[S.RawTrend]]:
    out: dict[str, list[S.RawTrend]] = {}
    timeout = float(cfg.get("busca.timeout_fontes_s", 60))
    ex = cf.ThreadPoolExecutor(max_workers=min(4, max(1, len(names))), thread_name_prefix="trend")
    futs = {ex.submit(S.SOURCES[n], cfg): n for n in names}
    try:
        for fut in cf.as_completed(futs, timeout=timeout):
            name = futs[fut]
            try:
                out[name] = fut.result() or []
            except Exception as e:  # noqa: BLE001 (fontes ja nao levantam, mas por garantia)
                _log.warning("fonte %s falhou: %s", name, e)
                out[name] = []
    except cf.TimeoutError:
        late = [futs[f] for f in futs if not f.done()]
        _log.warning("fontes demoraram demais e foram ignoradas: %s", ", ".join(late))
    finally:
        ex.shutdown(wait=False, cancel_futures=True)
    return out


def _cluster_short(items: list[S.RawTrend]) -> list[_Cluster]:
    clusters: list[_Cluster] = []
    for it in sorted(items, key=lambda t: -S.SOURCE_WEIGHT.get(t.source, 0.5) * t.s):
        k = _key(it.topic)
        if not k:
            continue
        rel = {_key(r) for r in it.related if r}
        best, best_sim = None, 0.0
        for c in clusters:
            if k in c.keys or (rel & {_key(x.topic) for x in c.items}):
                best, best_sim = c, 1.0
                break
            sim = max(similarity(it.topic, x.topic) for x in c.items)
            if sim > best_sim:
                best, best_sim = c, sim
        if best is not None and best_sim >= 0.82:
            best.items.append(it)
            best.keys.add(k)
            best.keys.update(rel if it.source == "google_trends" else set())
        else:
            c = _Cluster(items=[it], keys={k} | (rel if it.source == "google_trends" else set()))
            clusters.append(c)
    return clusters


def _attach_headlines(clusters: list[_Cluster], heads: list[S.RawTrend]) -> list[_Cluster]:
    """Manchetes/posts que citam um assunto curto reforcam aquele assunto; o resto vira assunto proprio."""
    extra: list[_Cluster] = []
    for h in sorted(heads, key=lambda t: -S.SOURCE_WEIGHT.get(t.source, 0.5) * t.s):
        target, best_len = None, 0
        for c in clusters:
            for x in c.items:
                if S.topic_is_specific(x.topic) and contains_topic(h.topic, x.topic):
                    ln = len(norm(x.topic))
                    if ln > best_len:
                        target, best_len = c, ln
        if target is not None:
            target.headlines.append(h)
            continue
        # junta manchetes parecidas entre si (mesma historia em varias fontes/secoes)
        best, best_sim = None, 0.0
        ht = set(tokens(h.topic))
        for c in extra:
            for x in c.items:
                xt = set(tokens(x.topic))
                if not ht or not xt:
                    continue
                jac = len(ht & xt) / len(ht | xt)
                if jac > best_sim:
                    best, best_sim = c, jac
        if best is not None and best_sim >= 0.5:
            best.headlines.append(h)
        else:
            extra.append(_Cluster(items=[h], keys={norm(h.topic)}))
    return clusters + extra


def _score_cluster(c: _Cluster) -> tuple[float, list[str]]:
    per_src: dict[str, float] = {}
    for it in c.all_items():
        v = S.SOURCE_WEIGHT.get(it.source, 0.5) * it.s
        per_src[it.source] = max(per_src.get(it.source, 0.0), v)
    srcs = sorted(per_src, key=lambda k: -per_src[k])
    base = max(per_src.values()) if per_src else 0.0
    agreement = len(srcs) - 1
    members = len(c.all_items())
    score = 100.0 * (0.78 * base + 0.13 * agreement + 0.02 * min(5, members - 1))
    return max(0.0, min(100.0, score)), srcs


_PUNCT = str.maketrans({"\u2014": "-", "\u2013": "-", "\u00b7": "|", "\u2022": "|"})


def _clean(s: str) -> str:
    """Sem travessoes/pontos medios nos textos mostrados ao usuario."""
    return (s or "").translate(_PUNCT).strip()


def _to_trend(c: _Cluster) -> Trend:
    score, srcs = _score_cluster(c)
    main = c.main
    topic = main.topic.strip()
    if main.kind == "headline" and len(topic) > 110:
        topic = topic[:107].rsplit(" ", 1)[0] + "..."
    related: list[str] = []
    seen = {norm(topic)}
    for it in sorted(c.all_items(), key=lambda t: -t.s):
        cand = ([it.topic] if it is not main else []) + list(it.related)
        for r in cand:
            n = norm(r)
            if r and n and n not in seen:
                seen.add(n)
                related.append(r.strip())
    by_src = {s: max((x for x in c.all_items() if x.source == s), key=lambda x: x.s) for s in srcs}
    traffic = next((by_src[s].traffic for s in ("google_trends", "x_trends") if s in by_src and by_src[s].traffic),
                   None) or main.traffic
    reason_parts = []
    if "google_trends" in by_src and by_src["google_trends"].traffic:
        reason_parts.append(f"Google: {by_src['google_trends'].traffic}")
    if "x_trends" in by_src:
        reason_parts.append(f"X: {by_src['x_trends'].traffic or 'em alta'}")
    n_news = sum(1 for x in c.all_items() if x.source == "google_news")
    if n_news:
        reason_parts.append(f"{n_news} manchete(s)")
    n_red = sum(1 for x in c.all_items() if x.source == "reddit")
    if n_red:
        reason_parts.append(f"Reddit: {n_red} post(s) quente(s)")
    category = next((x.category for x in sorted(c.all_items(), key=lambda x: x.source != "google_trends")
                     if x.category), None)
    query = short_query(topic) if main.kind == "headline" else topic
    topic = _clean(topic)
    related = [_clean(r) for r in related]
    return Trend(
        topic=topic,
        source="+".join(srcs) if srcs else main.source,
        score=round(score, 1),
        traffic=traffic,
        related=related[:10],
        url=main.url or next((x.url for x in c.all_items() if x.url), None),
        category=category,
        queries=[_clean(query)],
        reason=" | ".join(reason_parts),
    )


def merge_trends(raw: list[S.RawTrend], blocked_words: list[str] | None = None) -> list[Trend]:
    short = [t for t in raw if t.kind == "short"]
    heads = [t for t in raw if t.kind != "short"]
    clusters = _cluster_short(short)
    clusters = _attach_headlines(clusters, heads)
    trends = [_to_trend(c) for c in clusters]
    bw = [norm(w) for w in (blocked_words or []) if norm(w)]
    if bw:
        trends = [t for t in trends if not any(f" {w} " in f" {norm(t.topic)} " for w in bw)]
    trends.sort(key=lambda t: -t.score)
    return trends


def collect_trends(cfg) -> list[Trend]:
    """Assuntos em alta no Brasil agora (Google Trends, Google Noticias, X, Reddit), ja mesclados e pontuados."""
    t0 = time.time()
    names = _enabled_sources(cfg)
    if not names:
        _log.warning("nenhuma fonte de tendencias ativa em busca.fontes")
        return []
    results = _run_sources(cfg, names)
    raw: list[S.RawTrend] = []
    for n in names:
        raw.extend(results.get(n, []))
    trends = merge_trends(raw, cfg.get("busca.palavras_bloqueadas", []) or [])
    limit = int(cfg.get("busca.max_trends", 60))
    _log.info("collect_trends: %d brutos -> %d assuntos em %.1fs (%s)", len(raw), len(trends), time.time() - t0,
              ", ".join(f"{n}={len(results.get(n, []))}" for n in names))
    return trends[:limit]
