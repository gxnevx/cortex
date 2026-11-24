"""Estruturas de dados compartilhadas entre os modulos (contratos)."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class Trend:
    """Um assunto em alta descoberto em alguma fonte."""
    topic: str
    source: str                     # google_trends | google_news | x_trends | reddit | youtube | twitch | keyword
    score: float = 0.0              # 0-100 (normalizado pela fonte; o cerebro pode reordenar)
    traffic: str | None = None      # ex.: "200 mil+" (Google Trends)
    related: list[str] = field(default_factory=list)   # manchetes/consultas relacionadas
    url: str | None = None
    category: str | None = None     # politica, games, humor... (preenchido pelo cerebro se possivel)
    queries: list[str] = field(default_factory=list)   # buscas a fazer nas plataformas de video
    reason: str = ""                # por que e interessante (cerebro)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Candidate:
    """Um video bruto (fonte) que pode virar cortes."""
    id: str                         # "<plataforma>:<id do video>"  ex.: "youtube:dQw4w9WgXcQ"
    platform: str                   # youtube | twitch | kick | rumble | outro
    url: str
    title: str
    channel: str = ""
    channel_url: str | None = None
    duration: float | None = None   # segundos
    views: int | None = None
    likes: int | None = None
    comments: int | None = None
    upload_ts: float | None = None  # epoch (segundos)
    is_live: bool = False
    was_live: bool = False
    thumbnail: str | None = None
    description: str = ""
    topic: str | None = None        # trend / palavra-chave que levou a ele
    score: float = 0.0              # 0-100 pontuacao de potencial
    reasons: list[str] = field(default_factory=list)
    has_subtitles: bool = False
    extra: dict[str, Any] = field(default_factory=dict)   # heatmap, capitulos, clipes da twitch etc.

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Candidate":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class Word:
    start: float
    end: float
    text: str


@dataclass
class Segment:
    start: float
    end: float
    text: str
    words: list[Word] = field(default_factory=list)


@dataclass
class Transcript:
    segments: list[Segment] = field(default_factory=list)
    language: str = "pt"
    source: str = "whisper"         # whisper | youtube_subs | vazio

    @property
    def duration(self) -> float:
        return self.segments[-1].end if self.segments else 0.0

    @property
    def text(self) -> str:
        return " ".join(s.text.strip() for s in self.segments).strip()

    def words(self) -> list[Word]:
        out: list[Word] = []
        for s in self.segments:
            out.extend(s.words)
        return out

    def slice(self, start: float, end: float, rebase: bool = True) -> "Transcript":
        """Trecho [start, end]. Se rebase=True, os tempos passam a comecar em 0."""
        off = start if rebase else 0.0
        segs: list[Segment] = []
        for s in self.segments:
            if s.end <= start or s.start >= end:
                continue
            words = [Word(max(w.start, start) - off, min(w.end, end) - off, w.text)
                     for w in s.words if w.end > start and w.start < end]
            segs.append(Segment(max(s.start, start) - off, min(s.end, end) - off, s.text, words))
        return Transcript(segs, self.language, self.source)

    def text_with_timestamps(self, max_chars: int | None = None, every_s: float = 0.0) -> str:
        """Texto com marcas [mm:ss] para o cerebro escolher trechos."""
        lines = []
        last = -1e9
        for s in self.segments:
            if s.start - last >= every_s:
                m, sec = divmod(int(s.start), 60)
                h, m = divmod(m, 60)
                stamp = f"{h}:{m:02d}:{sec:02d}" if h else f"{m:02d}:{sec:02d}"
                lines.append(f"[{stamp}] {s.text.strip()}")
                last = s.start
            else:
                lines[-1] += " " + s.text.strip()
        out = "\n".join(lines)
        if max_chars and len(out) > max_chars:
            out = out[:max_chars]
        return out

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Transcript":
        segs = [Segment(s["start"], s["end"], s["text"], [Word(**w) for w in s.get("words", [])])
                for s in d.get("segments", [])]
        return cls(segs, d.get("language", "pt"), d.get("source", "whisper"))


@dataclass
class ClipPlan:
    """Um corte planejado pelo cerebro (tempos na linha do tempo do video ORIGINAL)."""
    id: str                         # unico: "<slug-do-video>-c<n>"
    source_id: str                  # Candidate.id
    start: float
    end: float
    title: str                      # titulo chamativo com emojis (vai no post)
    hook: str = ""                  # frase curta que aparece no topo do video
    description: str = ""
    hashtags: list[str] = field(default_factory=list)
    score: float = 0.0              # 0-100 chance de viralizar
    reason: str = ""                # por que deve viralizar
    category: str | None = None
    series: str | None = None       # nome da serie quando e "Parte X"
    part: int | None = None
    parts_total: int | None = None
    layout: str | None = None       # sugestao de layout (split/blur/full) ou None
    # Gancho de abertura (cold open): trecho mais polemico do proprio corte, repetido nos 1,5-3 s iniciais.
    # Tempos na linha do tempo do video ORIGINAL, dentro de [start, end].
    teaser_start: float | None = None
    teaser_end: float | None = None
    teaser_text: str = ""
    idioma_origem: str | None = None  # "en", "es"... quando o corte foi traduzido (LEGENDADO)
    fala: str = ""                    # o que e dito no corte (o editor-chefe le antes de postar)
    exp: dict = field(default_factory=dict)   # lado sorteado em cada teste A/B (experimentos.py)
    editor: dict = field(default_factory=dict)    # nota do editor-chefe dada ANTES de editar (bordas.fino)
    imagens: list[dict] = field(default_factory=list)   # o que ilustrar (palavra dita + busca); depois de editar, as usadas com credito
    titulo_alt: str = ""              # o outro titulo (com aspas x direto), para o teste A/B
    tipo: str = ""                    # fala | reacao | curiosidade | tutorial | noticia (decide o estilo do titulo)
    context: str = ""                 # linha de contexto (ate ~60 caracteres) para o cartao de abertura
    # Versao estendida para o TikTok (>= 61 s, monetizavel nas Recompensas). Linha do tempo ORIGINAL,
    # contem [start, end]. None = o TikTok recebe a mesma versao curta do YouTube.
    ext_start: float | None = None
    ext_end: float | None = None

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "ClipPlan":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class RenderedClip:
    plan: ClipPlan
    path: str                       # mp4 final 1080x1920
    duration: float
    layout: str
    thumbnail: str | None = None    # jpg (para relatorio)
    background: str | None = None   # arquivo de fundo usado
    # versoes por rede (logo + @ diferente em cada uma): {"youtube": caminho, "tiktok": caminho}
    variants: dict[str, str] = field(default_factory=dict)

    def path_for(self, platform: str) -> str:
        """Arquivo certo para a rede (cai no principal se nao houver versao propria)."""
        v = self.variants or {}
        p = v.get(platform) or (v.get("tiktok") if platform == "instagram" else None)   # mesmo @ do TikTok: mesma versao
        return p if p else self.path

    def all_files(self) -> list[str]:
        files = [self.path] + [v for v in (self.variants or {}).values() if v and v != self.path]
        return list(dict.fromkeys(files))

    def to_dict(self) -> dict:
        d = asdict(self)
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "RenderedClip":
        d = dict(d)
        d["plan"] = ClipPlan.from_dict(d["plan"])
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class PostResult:
    clip_id: str
    platform: str                   # youtube | tiktok
    ok: bool
    url: str | None = None
    error: str | None = None
    screenshot: str | None = None
    ts: float = 0.0
    dry_run: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


class NeedsUserAction(Exception):
    """Algo exige acao humana (login, captcha, verificacao). A mensagem explica o que fazer."""


class CaptchaAppeared(NeedsUserAction):
    """A rede mostrou um CAPTCHA: so o dono resolve (publish/ajuda.py mostra a janela e espera)."""
