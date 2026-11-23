"""Carrega config.yaml, mescla com os padroes e oferece acesso por caminho pontilhado.

Uso:
    cfg = load_config()
    cfg.get("edicao.legenda.cor", "#FFFFFF")
    cfg["modo_publicacao"]
"""
from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import yaml

from . import paths

DEFAULTS: dict[str, Any] = {
    "modo_publicacao": "auto",
    "conteudo": {"emojis": True},
    "execucao": {
        "videos_por_execucao": 5,
        "cortes_por_video": "auto",
        "max_cortes_por_execucao": 15,
        "horarios": ["09:00", "13:00", "18:00", "22:00"],
    },
    "busca": {
        "modo": "trends",
        "palavras_chave": [],
        "pais": "BR",
        "idioma": "pt",
        "temas": ["politica", "polemica", "games", "humor", "entretenimento", "esportes", "podcast", "noticias"],
        "janela_horas": 48,
        "duracao_min_s": 90,
        "duracao_max_s": 21600,
        "views_minimas": 5000,
        "fontes": {
            "google_trends": True, "google_news": True, "x_trends": True, "reddit": True,
            "youtube": True, "twitch": True, "kick": False, "rumble": False,
        },
        "canais_monitorados": {"youtube": [], "twitch": [], "kick": [], "rumble": []},
        "canais_bloqueados": [],
        "palavras_bloqueadas": [],
    },
    "cerebro": {
        "motor": "auto",
        "claude_modelo": "",
        "ollama_modelo": "qwen3:4b",
        "ollama_url": "http://127.0.0.1:11434",
        "timeout_s": 300,
    },
    "transcricao": {"modelo_whisper": "small", "usar_legendas_da_plataforma": True, "threads": 0},
    "corte": {
        "duracao_min_s": 20, "duracao_max_s": 58, "permitir_series": True,
        "duracao_parte_s": 50, "max_partes": 3, "pontuacao_minima": 55,
    },
    "edicao": {
        "layout": "auto",
        "fundo_categorias": ["gameplay", "satisfying", "asmr", "procedural"],
        "legenda": {
            "estilo": "karaoke", "fonte": "auto", "tamanho": 90, "cor": "#FFFFFF",
            "cor_destaque": "auto", "contorno": "#000000", "palavras_por_tela": 2,
            "maiusculas": True, "posicao": "centro",
        },
        "titulo_no_video": True,
        "duracao_titulo_s": 0,
        "barra_progresso": True,
        "marca_dagua": "",
        "encoder": "auto",
        "qualidade": "alta",
        "normalizar_audio": True,
        "fps": 30,
    },
    "publicacao": {
        "plataformas": ["youtube", "tiktok"],
        "navegador": "chrome",
        "headless": False,
        "intervalo_entre_posts_s": [90, 240],
        "max_posts_por_dia": {"youtube": 4, "tiktok": 4},
        "youtube_visibilidade": "public",
        "tiktok_visibilidade": "everyone",
        "hashtags_fixas": [],
        "descricao_rodape": "",
        "creditar_fonte": True,
    },
    "armazenamento": {
        "limite_gb": 4, "espaco_minimo_livre_gb": 2,
        "apagar_brutos_apos_render": True, "manter_renders_dias": 3,
    },
    "notificacoes": {"windows_toast": True},
}


def _deep_merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


class Config:
    """Envolve o dicionario de configuracao com acesso pontilhado."""

    def __init__(self, data: dict, path: Path | None = None):
        self.data = data
        self.path = path

    def get(self, dotted: str, default: Any = None) -> Any:
        cur: Any = self.data
        for part in dotted.split("."):
            if isinstance(cur, dict) and part in cur:
                cur = cur[part]
            else:
                return default
        return cur

    def set(self, dotted: str, value: Any) -> None:
        """Altera um valor apenas em memoria (ex.: override por argumento de linha de comando)."""
        cur = self.data
        parts = dotted.split(".")
        for part in parts[:-1]:
            cur = cur.setdefault(part, {})
        cur[parts[-1]] = value

    def __getitem__(self, key: str) -> Any:
        return self.get(key)

    def __contains__(self, key: str) -> bool:
        return self.get(key, _MISSING) is not _MISSING

    def as_dict(self) -> dict:
        return copy.deepcopy(self.data)


_MISSING = object()


def _defaults() -> dict:
    """Padroes = dicionario acima + config.exemplo.yaml (copia de referencia completa)."""
    base = DEFAULTS
    ex = paths.CONFIG_EXAMPLE_PATH
    if ex.exists():
        try:
            with open(ex, encoding="utf-8") as f:
                base = _deep_merge(base, yaml.safe_load(f) or {})
        except Exception:
            pass
    return base


_GOOD = paths.STATE / "config_ultima_boa.yaml"
_warned = ""


def _keep_good(path: Path) -> None:
    """Guarda a ultima versao valida (so quando muda)."""
    try:
        txt = path.read_text(encoding="utf-8")
        if not _GOOD.exists() or _GOOD.read_text(encoding="utf-8") != txt:
            _GOOD.parent.mkdir(parents=True, exist_ok=True)
            _GOOD.write_text(txt, encoding="utf-8")
    except OSError:
        pass


def _last_good(path: Path, e: Exception) -> dict:
    global _warned
    if _warned != str(e):
        _warned = str(e)
        import logging

        logging.getLogger("fabrica.config").error("config.yaml com erro (%s): usando a ultima versao valida", str(e)[:200])
    try:
        return yaml.safe_load(_GOOD.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}


def load_config(path: Path | None = None) -> Config:
    path = path or paths.CONFIG_PATH
    user: dict = {}
    if path.exists():
        try:
            with open(path, encoding="utf-8") as f:
                user = yaml.safe_load(f) or {}
            if not isinstance(user, dict):
                raise ValueError("o arquivo nao e uma lista de opcoes")
            if path == paths.CONFIG_PATH:
                _keep_good(path)
        except Exception as e:
            user = _last_good(path, e)
    elif paths.CONFIG_EXAMPLE_PATH.exists():
        import shutil

        shutil.copy2(paths.CONFIG_EXAMPLE_PATH, path)  # primeira execucao: cria o config.yaml
    return Config(_deep_merge(_defaults(), user), path)


def _find_key(lines: list[str], parts: list[str]) -> int | None:
    """Linha da chave aninhada (pela indentacao), ou None."""
    lo, hi, at = 0, len(lines), None
    for part in parts:
        child, at = None, None
        for j in range(lo, hi):
            ln = lines[j]
            if not ln.strip() or ln.lstrip().startswith("#"):
                continue
            ind = len(ln) - len(ln.lstrip())
            child = ind if child is None else child
            if ind < child:
                break
            if ind == child and ln.strip().split(":")[0].strip("\"'") == part and ":" in ln:
                at = j
                break
        if at is None:
            return None
        lo = at + 1
        ind_at = len(lines[at]) - len(lines[at].lstrip())
        nxt = next((j for j in range(lo, hi) if lines[j].strip() and not lines[j].lstrip().startswith("#")
                    and len(lines[j]) - len(lines[j].lstrip()) <= ind_at), hi)
        hi = nxt
    return at


def save_value(dotted: str, value: Any, path: Path | None = None) -> None:
    """Grava um valor no config.yaml mudando so a linha dele (os comentarios ficam)."""
    import re

    path = path or paths.CONFIG_PATH
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    data = yaml.safe_load(text) or {}
    cur = data
    parts = dotted.split(".")
    for part in parts[:-1]:
        cur = cur.setdefault(part, {})
    cur[parts[-1]] = value
    dumped = yaml.safe_dump(value, allow_unicode=True, default_flow_style=True, width=10**6).strip()
    if dumped.endswith("..."):
        dumped = dumped[:-3].strip()
    lines = text.split("\n")
    at = _find_key(lines, parts)
    if at is not None:
        m = re.match(r"^(\s*[^:]+:)\s*.*?(\s+#.*)?$", lines[at])
        lines[at] = f"{m.group(1)} {dumped}{m.group(2) or ''}"
    else:
        up = _find_key(lines, parts[:-1]) if len(parts) > 1 else None
        if up is not None:
            ind = len(lines[up]) - len(lines[up].lstrip())
            lines.insert(up + 1, " " * (ind + 2) + f"{parts[-1]}: {dumped}")
        elif len(parts) == 1:
            lines.append(f"{parts[0]}: {dumped}")
    new = "\n".join(lines)
    try:
        same = yaml.safe_load(new) == data
    except Exception:
        same = False
    path.write_text(new if same else yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
