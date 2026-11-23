"""Descoberta: assuntos em alta (Google Trends, Google Noticias, X, Reddit) e videos-fonte
(YouTube, Twitch, Kick, Rumble) sem API key - so paginas publicas, RSS e yt-dlp.

    collect_trends(cfg) -> list[Trend]
    find_candidates(cfg, trends=None, keywords=None, limit=15, exclude_ids=None) -> list[Candidate]
"""
from __future__ import annotations


def collect_trends(cfg):
    from .trends import collect_trends as _ct

    return _ct(cfg)


def find_candidates(cfg, trends=None, keywords=None, limit=15, exclude_ids=None):
    from .candidates import find_candidates as _fc

    return _fc(cfg, trends=trends, keywords=keywords, limit=limit, exclude_ids=exclude_ids)


__all__ = ["collect_trends", "find_candidates"]
