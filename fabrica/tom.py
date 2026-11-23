"""Volume da polemica: 5 niveis de tom para titulos, ganchos, legendas de post e edicao.

    neutro          informativo, sem provocacao
    polemico        palavra de conflito, citacao entre aspas
    malicioso       duplo sentido, insinua sem afirmar (padrao)
    super_polemico  malicioso + verbos agressivos, caixa alta, provocacao direta
    modo_besta      tudo no maximo: palavrao sem mascara, gancho e citacao em 100%, ragebait

Piso fixo em TODOS os niveis (nao e estilo, e o que gera processo e banimento):
a insinuacao precisa estar no corte; nunca inventar crime, traicao, caso ou ato sexual de pessoa real;
nada sexual com menores; nada de odio contra grupos; nada de informacao falsa.
"""
from __future__ import annotations

from .config import Config

LEVELS = ["neutro", "polemico", "malicioso", "super_polemico", "modo_besta"]

_ALIASES = {
    "neutral": "neutro", "leve": "neutro",
    "polemica": "polemico", "medio": "polemico",
    "malicia": "malicioso", "caliente": "malicioso",
    "super": "super_polemico", "superpolemico": "super_polemico", "super polemico": "super_polemico",
    "besta": "modo_besta", "modo besta": "modo_besta", "sem_limites": "modo_besta", "sem limites": "modo_besta",
    "extremo": "modo_besta", "maximo": "modo_besta",
}

LABELS = {
    "neutro": "Neutro (informativo)",
    "polemico": "Polemico (conflito e citacao entre aspas)",
    "malicioso": "Malicioso (duplo sentido, insinua sem afirmar)",
    "super_polemico": "Super polemico (agressivo, caixa alta, provocacao)",
    "modo_besta": "MODO BESTA (tudo no maximo, palavrao sem mascara)",
}

# O que cada nivel muda na esteira. Valores None = usa o que estiver no config.yaml.
_SETTINGS = {
    "neutro":         {"intensidade": 0, "palavroes": "remover", "cold_open_proporcao": 0.0,
                       "citacao_proporcao": 0.0, "caps_gancho": False, "max_emojis": 1},
    "polemico":       {"intensidade": 1, "palavroes": None, "cold_open_proporcao": None,
                       "citacao_proporcao": None, "caps_gancho": True, "max_emojis": 2},
    "malicioso":      {"intensidade": 2, "palavroes": None, "cold_open_proporcao": None,
                       "citacao_proporcao": None, "caps_gancho": True, "max_emojis": 2},
    "super_polemico": {"intensidade": 3, "palavroes": None, "cold_open_proporcao": 0.9,
                       "citacao_proporcao": 0.9, "caps_gancho": True, "max_emojis": 2},
    "modo_besta":     {"intensidade": 4, "palavroes": "mostrar", "cold_open_proporcao": 1.0,
                       "citacao_proporcao": 1.0, "caps_gancho": True, "max_emojis": 3},
}

# Guia de escrita por nivel (vai para os prompts da IA e para quem gera texto)
GUIDE = {
    "neutro": "Tom informativo e curioso, sem provocacao e sem palavrao.",
    "polemico": "Destaque o conflito: palavras de briga/acusacao, nome das pessoas, a frase mais forte entre aspas.",
    "malicioso": ("Duplo sentido e curiosidade: insinue sem afirmar ('Ela nao negou', 'Ficou claro o que ele quis "
                  "dizer', 'O silencio dele disse tudo'), tom caliente e provocador."),
    "super_polemico": ("Malicioso no talo: verbos agressivos (HUMILHOU, DESTRUIU, EXPOS, PERDEU A LINHA), caixa alta "
                       "nas palavras-chave, provocacao direta ao espectador, chamada para briga nos comentarios."),
    "modo_besta": ("Tudo no maximo: o mais agressivo, debochado e provocador possivel, palavrao sem mascara quando "
                   "foi dito, caixa alta, ragebait que divide opiniao ('se discordar comenta'), duplo sentido pesado, "
                   "sem suavizar nada."),
}

FLOOR = ("Limite fixo em qualquer nivel: a insinuacao precisa estar no que acontece no corte; nunca inventar ou "
         "insinuar crime, traicao, caso ou ato sexual de pessoa real que nao foi falado no video; nada sexual "
         "envolvendo menores; nada de odio ou ataque a grupos; nada de informacao falsa.")


def level(cfg: Config | None) -> str:
    raw = str((cfg.get("conteudo.tom_titulo", "malicioso") if cfg else "malicioso") or "malicioso")
    raw = raw.strip().lower().replace("-", "_")
    raw = _ALIASES.get(raw, _ALIASES.get(raw.replace("_", " "), raw))
    return raw if raw in LEVELS else "malicioso"


def settings(cfg: Config | None) -> dict:
    """Configuracao efetiva do nivel atual (o nivel tem prioridade sobre as chaves soltas do config)."""
    lv = level(cfg)
    s = dict(_SETTINGS[lv])
    if s["palavroes"] is None:
        s["palavroes"] = str(cfg.get("conteudo.palavroes", "mascarar")) if cfg else "mascarar"
    if s["cold_open_proporcao"] is None:
        s["cold_open_proporcao"] = float(cfg.get("edicao.cold_open_proporcao", 0.7)) if cfg else 0.7
    if s["citacao_proporcao"] is None:
        s["citacao_proporcao"] = float(cfg.get("conteudo.titulo_com_citacao_proporcao", 0.7)) if cfg else 0.7
    s["nivel"] = lv
    s["guia"] = GUIDE[lv]
    s["piso"] = FLOOR
    return s


def prompt_block(cfg: Config | None) -> str:
    """Trecho pronto para colar nos prompts da IA."""
    s = settings(cfg)
    return f"TOM ({s['nivel']}): {s['guia']}\n{FLOOR}"
