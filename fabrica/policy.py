"""Regras de crescimento e seguranca das contas (aquecimento, espacamento, horario nobre).

Baseado na pesquisa em docs/ideias/algoritmo_e_riscos.md:
- conta nova precisa de AQUECIMENTO: poucos posts por dia nas primeiras semanas;
- intervalo minimo entre posts por rede;
- horario nobre (BRT) muda conforme o dia da semana.
"""
from __future__ import annotations

import json
import time
from datetime import date, datetime, timedelta

from . import db, log, paths
from .config import Config

_log = log.get("policy")
ACCOUNTS = paths.STATE / "contas.json"

# (dia_inicial, dia_final, posts_por_dia) - idade da conta em dias
DEFAULT_WARMUP = [[0, 3, 0], [4, 10, 1], [11, 21, 2], [22, 42, 3], [43, 99999, 4]]

# Horario nobre padrao por dia da semana (0 = segunda)
DEFAULT_PRIME = {
    "seg": ["12:00-13:30", "20:30-22:30"],
    "ter": ["12:00-13:30", "20:30-22:30"],
    "qua": ["12:00-13:30", "20:30-22:30"],
    "qui": ["12:00-13:30", "20:30-22:30"],
    "sex": ["12:00-13:30", "18:00-20:00"],
    "sab": ["11:00-13:00", "20:00-23:00"],
    "dom": ["11:00-13:00", "19:00-22:00"],
}
_DAYS = ["seg", "ter", "qua", "qui", "sex", "sab", "dom"]


def _load_accounts() -> dict:
    try:
        return json.loads(ACCOUNTS.read_text(encoding="utf-8"))
    except Exception:
        return {}


def register_login(platform: str) -> None:
    """Na primeira vez que detectamos login numa rede, guardamos a data (inicio do aquecimento)."""
    data = _load_accounts()
    if platform not in data:
        data[platform] = {"primeiro_login": date.today().isoformat()}
        ACCOUNTS.parent.mkdir(parents=True, exist_ok=True)
        ACCOUNTS.write_text(json.dumps(data, indent=2), encoding="utf-8")
        _log.info("Conta %s registrada; aquecimento comeca hoje", platform)


def account_age_days(platform: str, cfg: Config) -> int | None:
    """Idade da conta: config publicacao.contas.<rede>.criada_em (AAAA-MM-DD) ou data do primeiro login."""
    created = cfg.get(f"publicacao.contas.{platform}.criada_em")
    if not created:
        created = _load_accounts().get(platform, {}).get("primeiro_login")
    if not created:
        return None
    try:
        return (date.today() - date.fromisoformat(str(created))).days
    except ValueError:
        return None


def daily_limit(platform: str, cfg: Config) -> int:
    base = int((cfg.get("publicacao.max_posts_por_dia", {}) or {}).get(platform, 4))
    if not cfg.get("publicacao.aquecimento.ativo", True):
        return base
    age = account_age_days(platform, cfg)
    if age is None:
        return base  # sem informacao: usa o configurado
    for a, b, n in cfg.get("publicacao.aquecimento.tabela", DEFAULT_WARMUP):
        if a <= age <= b:
            return min(base, int(n))
    return base


def health(platform: str, cfg: Config) -> dict:
    """Saude da conta pelas views (modulo de metricas). Sem dados ou sem o modulo: normal."""
    try:
        from . import metrics

        return metrics.account_health(platform, cfg) or {"nivel": "normal", "ok": True}
    except Exception:
        return {"nivel": "normal", "ok": True}


def effective_limit(platform: str, cfg: Config) -> int:
    """Limite do dia = aquecimento/teto x fator de saude (1 normal, 0,5 atencao, 0 pausa)."""
    lim = daily_limit(platform, cfg)
    try:
        from . import metrics

        factor = float(metrics.volume_factor(platform, cfg))
    except Exception:
        factor = 1.0
    if factor <= 0:
        return 0
    return max(1, int(lim * factor)) if lim > 0 else 0


def min_interval_s(platform: str, cfg: Config) -> float:
    mins = (cfg.get("publicacao.intervalo_minimo_min", {}) or {}).get(platform, 120)
    return float(mins) * 60


def last_post_ts(platform: str) -> float | None:
    r = db.conn().execute("SELECT MAX(ts) FROM posts WHERE platform=? AND ok=1 AND dry_run=0", (platform,)).fetchone()
    return r[0] if r and r[0] else None


def ready_at(platform: str, cfg: Config) -> float:
    """Quando essa rede pode receber o proximo post (epoch). 0 = ja pode."""
    last = last_post_ts(platform)
    return (last + min_interval_s(platform, cfg)) if last else 0.0


def can_post(platform: str, cfg: Config) -> tuple[bool, str]:
    h = health(platform, cfg)
    if h.get("nivel") == "pausa":
        return False, f"conta em pausa: {h.get('motivo', 'views travadas')}"
    if daily_limit(platform, cfg) <= 0:
        age = account_age_days(platform, cfg)
        return False, f"aquecimento da conta (dia {age}): sem posts ainda"
    lim = effective_limit(platform, cfg)
    if db.posts_today(platform) >= lim:
        return False, f"limite de hoje atingido ({lim})"
    ra = ready_at(platform, cfg)
    if ra > time.time():
        return False, f"intervalo minimo: libera as {datetime.fromtimestamp(ra):%H:%M}"
    return True, "ok"


def prime_windows(cfg: Config, when: datetime | None = None) -> list[str]:
    when = when or datetime.now()
    table = cfg.get("autopiloto.horarios_nobres_semana") or DEFAULT_PRIME
    return list(table.get(_DAYS[when.weekday()], []))


def plan_steps(platform: str, cfg: Config) -> list[tuple[date, int]]:
    """Quantos posts por dia, e a partir de quando: [(hoje, 0), (26/11, 1), ...]."""
    base = int((cfg.get("publicacao.max_posts_por_dia", {}) or {}).get(platform, 4))
    age = account_age_days(platform, cfg)
    if not cfg.get("publicacao.aquecimento.ativo", True) or age is None:
        return [(date.today(), base)]
    steps = [(date.today(), daily_limit(platform, cfg))]
    for a, _b, n in cfg.get("publicacao.aquecimento.tabela", DEFAULT_WARMUP):
        n = min(base, int(n))
        if a > age and n != steps[-1][1]:
            steps.append((date.today() + timedelta(days=int(a) - age), n))
    return steps


def describe(cfg: Config) -> list[str]:
    out = []
    for p in cfg.get("publicacao.plataformas", ["youtube", "tiktok"]):
        age = account_age_days(p, cfg)
        ok, why = can_post(p, cfg)
        out.append(f"{p}: conta com {age if age is not None else '?'} dias | limite hoje {effective_limit(p, cfg)} | "
                   f"postados {db.posts_today(p)} | {'pode postar' if ok else why}")
    return out
