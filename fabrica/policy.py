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
    if cfg.get("estrategia.decide_quantidade", True):
        from . import estrategia

        q = (estrategia.state().get("quantidade") or {}).get(platform)
        if q:       # decidido com numeros reais (8+ posts maduros), um passo por vez, dentro do teto
            return max(1, min(int(q), int((cfg.get("estrategia.teto", {"youtube": 3, "tiktok": 6, "instagram": 3}) or {}).get(platform, base))))
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


# Folga depois do fim da janela: PC que acordou um pouco tarde (tampa fechada) ainda posta nela.
FOLGA_S = 20 * 60

# Melhores janelas por rede, em ordem de PRIORIDADE (docs/ideias/benchmark_canais.md, horario de Brasilia):
# YouTube: 22h-24h 1,73x | 10h-12h 1,36x | 20h-22h 1,28x | 18h-20h 0,78x | 8h-10h 0,69x
# TikTok:  20h-22h 2,25x | 10h-12h 1,34x | 14h-16h 1,20x | 18h-20h 0,91x | 6h-8h 0,72x
DEFAULT_SLOTS = {
    "youtube": {"padrao": ["22:00-23:30", "10:00-11:15", "13:30-14:30", "16:30-18:00", "20:00-21:00"],
                "qua": ["22:00-23:30", "13:15-14:15", "10:00-10:50", "16:30-18:00"],
                "sab": ["16:30-17:45", "12:30-13:45", "20:00-21:30", "10:30-12:00"],
                "dom": ["18:30-19:30", "10:30-12:00", "22:00-23:30", "14:00-15:00"]},
    "tiktok": {"padrao": ["20:00-21:45", "10:30-12:00", "14:00-15:30", "22:50-23:50", "17:10-18:10", "08:00-09:15"],
               "sab": ["21:30-23:30", "18:30-20:00", "10:30-12:00", "14:00-15:30", "16:40-17:00", "08:00-09:15"]},
    # sem pesquisa propria: almoco e fim de tarde, longe dos horarios das outras redes; o auditor reordena com numeros reais
    "instagram": {"padrao": ["18:15-19:45", "12:05-13:20", "21:50-22:50", "08:30-09:40"]},
}


def base_windows(platform: str, cfg: Config) -> list[str]:
    """Janelas padrao da rede na ordem da pesquisa/config."""
    table = (cfg.get("autopiloto.janelas_por_rede", {}) or {}).get(platform) or DEFAULT_SLOTS.get(platform) or {}
    return list(table.get("padrao") or [])


def _slot_times(platform: str, cfg: Config, day: date) -> list[tuple[float, float]]:
    """[(horario sorteado, fim da janela)] do dia, por prioridade. O sorteio e fixo por dia/rede/janela."""
    import random

    table = (cfg.get("autopiloto.janelas_por_rede", {}) or {}).get(platform) or DEFAULT_SLOTS.get(platform) or {}
    from . import auditor

    ordem = auditor.get(f"janelas.{platform}")
    if ordem and table.get("padrao") and sorted(ordem) != sorted(table["padrao"]):
        ordem = None        # o config mudou: a ordem antiga nao vale mais
    wins = table.get(_DAYS[day.weekday()]) or ordem or table.get("padrao") or prime_windows(cfg, datetime(day.year, day.month, day.day))
    wins = list(wins)
    rng = random.Random(f"explora{day}{platform}")
    n = daily_limit(platform, cfg)
    if cfg.get("autopiloto.explorar_horarios", True) and 1 < n < len(wins) and rng.random() < 0.15:
        j = rng.randrange(n, len(wins))
        wins[n - 1], wins[j] = wins[j], wins[n - 1]
    out = []
    for i, w in enumerate(wins):
        a, b = (datetime.strptime(x.strip(), "%H:%M") for x in str(w).split("-"))
        ta = datetime(day.year, day.month, day.day, a.hour, a.minute).timestamp()
        tb = datetime(day.year, day.month, day.day, b.hour, b.minute).timestamp()
        rnd = random.Random(f"{day}{platform}{i}{w}").uniform(0.05, 0.75)
        out.append((ta + (tb - ta) * rnd, tb))
    return out


def slots_today(platform: str, cfg: Config) -> list[tuple[float, float]]:
    """Horarios de post que ainda valem hoje (em ordem). Janela perdida ha mais de FOLGA_S (PC desligado) e trocada pela proxima boa."""
    now = time.time()
    limit = effective_limit(platform, cfg)
    left = limit - db.posts_today(platform)
    if left <= 0:
        return []
    last, gap = last_post_ts(platform) or 0.0, min_interval_s(platform, cfg)
    allw = _slot_times(platform, cfg, date.today())
    ok = [(max(t, last + gap), end) for t, end in allw]
    ok = [(t, end) for t, end in ok if t <= end and end + FOLGA_S >= now and last < t]
    chosen: list[tuple[float, float]] = []
    for t, end in ok:                     # prioridade, respeitando o intervalo entre os escolhidos
        if len(chosen) < left and all(abs(t - c) >= gap for c, _ in chosen):
            chosen.append((t, end))
    return sorted(chosen)


def slot_due(platform: str, cfg: Config) -> bool:
    """Esta na hora de postar nesta rede?"""
    return any(t <= time.time() <= end + FOLGA_S for t, end in slots_today(platform, cfg))


def next_slot(platform: str, cfg: Config) -> float:
    """Proximo horario de post desta rede (hoje ou nos proximos dias; 0 = nenhum previsto)."""
    s = slots_today(platform, cfg)
    if s:
        return max(s[0][0], time.time())
    for k in range(1, 8):
        day = date.today() + timedelta(days=k)
        n = _limit_on(platform, cfg, day)
        if n > 0:
            return min(t for t, _ in _slot_times(platform, cfg, day)[:n])
    return 0.0


def _limit_on(platform: str, cfg: Config, day: date) -> int:
    n = 0
    for d, v in plan_steps(platform, cfg):
        if d <= day:
            n = v
    return n


def prime_windows(cfg: Config, when: datetime | None = None) -> list[str]:
    when = when or datetime.now()
    table = cfg.get("autopiloto.horarios_nobres_semana") or DEFAULT_PRIME
    return list(table.get(_DAYS[when.weekday()], []))


def plan_steps(platform: str, cfg: Config) -> list[tuple[date, int]]:
    """Quantos posts por dia, e a partir de quando: [(hoje, 0), (26/11, 1), ...]."""
    base = int((cfg.get("publicacao.max_posts_por_dia", {}) or {}).get(platform, 4))
    age = account_age_days(platform, cfg)
    if cfg.get("estrategia.decide_quantidade", True):
        from . import estrategia

        if (estrategia.state().get("quantidade") or {}).get(platform):
            return [(date.today(), daily_limit(platform, cfg))]
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
