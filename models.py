"""
models.py
---------
Modelos de domínio do FightIQ, implementados como dataclasses.

Estes objetos representam as entidades centrais do sistema e são usados
por database.py, analysis.py, charts.py e interface.py como o "contrato"
de dados compartilhado entre módulos. Manter os modelos aqui (e não
espalhados pelo resto do código) evita duplicação e deixa explícito quais
campos são realmente suportados pelo sistema — nenhum campo aqui é
inventado; cada um corresponde a uma coluna real do banco de dados,
alimentada a partir de fontes públicas verificadas (ver database.py e
README.md para a proveniência dos dados).

Todos os campos estatísticos são Optional: quando um dado não está
disponível na fonte, o campo fica None e a interface exibe "N/D" em vez
de qualquer valor fabricado.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional

from utils import calculate_age, cm_to_feet_inches, format_record


@dataclass
class Fighter:
    """Representa um lutador e seus dados biográficos/cadastrais."""

    fighter_id: int
    name: str
    nickname: Optional[str] = None
    nationality: Optional[str] = None
    weight_class: Optional[str] = None
    height_cm: Optional[float] = None
    reach_cm: Optional[float] = None
    stance: Optional[str] = None
    birth_date: Optional[date] = None

    wins: int = 0
    losses: int = 0
    draws: int = 0
    no_contests: int = 0

    wins_ko: Optional[int] = None
    wins_sub: Optional[int] = None
    wins_dec: Optional[int] = None

    ranking: Optional[str] = None
    image_url: Optional[str] = None
    local_image_path: Optional[str] = None

    source: Optional[str] = None
    source_url: Optional[str] = None
    last_updated: Optional[str] = None

    # -- Propriedades derivadas (calculadas, nunca inventadas) -----------
    @property
    def age(self) -> Optional[int]:
        return calculate_age(self.birth_date)

    @property
    def height_display(self) -> str:
        return cm_to_feet_inches(self.height_cm)

    @property
    def reach_display(self) -> str:
        return cm_to_feet_inches(self.reach_cm)

    @property
    def record_display(self) -> str:
        return format_record(self.wins, self.losses, self.draws, self.no_contests)

    @property
    def total_fights(self) -> int:
        return self.wins + self.losses + self.draws

    @property
    def finish_rate_pct(self) -> Optional[float]:
        """% de vitórias por finalização (KO + Sub) sobre o total de vitórias."""
        if not self.wins or self.wins_ko is None or self.wins_sub is None:
            return None
        return round(100 * (self.wins_ko + self.wins_sub) / self.wins, 1)

    @property
    def display_name(self) -> str:
        if self.nickname:
            return f'{self.name} "{self.nickname}"'
        return self.name


@dataclass
class FighterStats:
    """
    Estatísticas de desempenho de um lutador (golpes, quedas, etc.).

    Espelha exatamente a terminologia usada por fontes públicas de
    estatísticas de MMA (SLpM, Str. Acc., SApM, Str. Def., TD Avg.,
    TD Acc., TD Def., Sub. Avg.), para que qualquer pessoa possa
    conferir/atualizar os números na fonte original.
    """

    fighter_id: int

    slpm: Optional[float] = None            # golpes significativos landed / min
    str_acc_pct: Optional[float] = None      # precisão de striking (%)
    sapm: Optional[float] = None             # golpes significativos absorvidos / min
    str_def_pct: Optional[float] = None      # defesa de striking (%)

    td_avg: Optional[float] = None           # quedas médias por luta (15 min)
    td_acc_pct: Optional[float] = None       # precisão de quedas (%)
    td_def_pct: Optional[float] = None       # defesa de quedas (%)

    sub_avg: Optional[float] = None          # tentativas de finalização / 15 min
    avg_fight_time: Optional[str] = None     # tempo médio de luta (mm:ss)

    def has_striking_data(self) -> bool:
        return any(v is not None for v in (self.slpm, self.str_acc_pct, self.sapm, self.str_def_pct))

    def has_grappling_data(self) -> bool:
        return any(v is not None for v in (self.td_avg, self.td_acc_pct, self.td_def_pct, self.sub_avg))


@dataclass
class FavoriteEntry:
    """Registro de um lutador marcado como favorito pelo usuário."""

    fighter_id: int
    name: str
    added_at: datetime = field(default_factory=datetime.now)


@dataclass
class SearchHistoryEntry:
    """Registro de uma pesquisa/consulta feita pelo usuário."""

    query: str
    fighter_id: Optional[int]
    searched_at: datetime = field(default_factory=datetime.now)


@dataclass
class ComparisonHighlight:
    """Um único destaque de vantagem entre dois lutadores, para a tela de comparação."""

    category: str          # ex.: "Alcance", "Defesa de Quedas"
    winner_name: str
    value_a: str
    value_b: str
    winner_side: str       # "a" ou "b"


@dataclass
class ComparisonResult:
    """Resultado consolidado da comparação entre dois lutadores."""

    fighter_a: Fighter
    fighter_b: Fighter
    stats_a: FighterStats
    stats_b: FighterStats
    highlights: list[ComparisonHighlight] = field(default_factory=list)
    narrative: str = ""
