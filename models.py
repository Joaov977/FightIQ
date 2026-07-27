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

from utils import calculate_age, cm_to_feet_inches, cm_to_meters_br, format_record


@dataclass
class Fighter:
    """Representa um lutador e seus dados biográficos/cadastrais."""

    # ID estável derivado do slug da URL de origem (ex.: "jon_jones"), não
    # um índice sequencial — isso evita que favoritos/histórico/overrides
    # apontem pro lutador errado se a ordem do scraping mudar entre execuções.
    fighter_id: str
    name: str
    nickname: Optional[str] = None
    nationality: Optional[str] = None
    weight_class: Optional[str] = None
    height_cm: Optional[float] = None
    reach_cm: Optional[float] = None
    stance: Optional[str] = None
    birth_date: Optional[date] = None
    age_reported: Optional[int] = None  # idade publicada diretamente pela fonte (sem DOB por trás)

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
    image_license: Optional[str] = None
    image_attribution: Optional[str] = None
    image_source_url: Optional[str] = None

    source: Optional[str] = None
    source_url: Optional[str] = None
    last_updated: Optional[str] = None
    manually_overridden_fields: Optional[str] = None  # campos ajustados via manual_overrides.csv, separados por vírgula

    # -- Propriedades derivadas (calculadas, nunca inventadas) -----------
    @property
    def age(self) -> Optional[int]:
        """
        Idade do lutador. Prioriza calcular a partir de birth_date (mais
        preciso, dia exato); se não houver data de nascimento disponível
        na fonte, usa age_reported — a idade publicada diretamente pela
        fonte (caso do GIDStats.com, que mostra "Age NN" em vez de uma
        data de nascimento). Isso é necessário porque, nesse caso, a
        idade pode ficar até ~1 ano desatualizada entre uma coleta e
        outra — ver `age_is_estimated` para sinalizar isso na interface.
        """
        computed = calculate_age(self.birth_date)
        return computed if computed is not None else self.age_reported

    @property
    def age_is_estimated(self) -> bool:
        """True quando a idade exibida vem de age_reported (não de birth_date exato)."""
        return self.birth_date is None and self.age_reported is not None

    @property
    def height_display(self) -> str:
        return cm_to_feet_inches(self.height_cm)

    @property
    def reach_display(self) -> str:
        return cm_to_feet_inches(self.reach_cm)

    @property
    def height_display_metric(self) -> str:
        """Altura em metros, padrão brasileiro (ex.: '1,93 m')."""
        return cm_to_meters_br(self.height_cm)

    @property
    def reach_display_metric(self) -> str:
        """Alcance em metros, padrão brasileiro (ex.: '2,15 m')."""
        return cm_to_meters_br(self.reach_cm)

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

    fighter_id: str  # mesmo slug estável usado em Fighter.fighter_id

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

    fighter_id: str
    name: str
    added_at: datetime = field(default_factory=datetime.now)


@dataclass
class SearchHistoryEntry:
    """Registro de uma pesquisa/consulta feita pelo usuário."""

    query: str
    fighter_id: Optional[str]
    searched_at: datetime = field(default_factory=datetime.now)


@dataclass
class FightRecord:
    """
    Um único registro de luta no histórico de um lutador.

    Representa exatamente os campos pedidos para o histórico completo:
    data, evento, adversário, resultado, método, round, tempo e
    categoria — mais campos de proveniência (fonte, URL, referee como
    bônus quando disponível) para nunca perder de onde o dado veio.

    `result` usa um vocabulário fixo (não string livre): "win", "loss",
    "draw", "no_contest", ou None quando a fonte não deixou claro —
    nunca inventamos um resultado que não pudemos confirmar.
    """

    fighter_id: str
    opponent_name: str
    fight_date: Optional[date] = None
    event_name: Optional[str] = None
    event_source_url: Optional[str] = None
    opponent_source_url: Optional[str] = None
    result: Optional[str] = None          # "win" | "loss" | "draw" | "no_contest"
    method: Optional[str] = None          # "KO/TKO" | "Submission" | "Decision" | "DQ" | ...
    method_detail: Optional[str] = None   # ex.: "Unanimous", "Rear-Naked Choke", "Head Kick"
    round: Optional[int] = None
    time: Optional[str] = None            # "mm:ss"
    weight_class: Optional[str] = None
    referee: Optional[str] = None
    source: Optional[str] = None
    source_url: Optional[str] = None
    last_updated: Optional[str] = None

    @property
    def result_display(self) -> str:
        return {
            "win": "Vitória", "loss": "Derrota",
            "draw": "Empate", "no_contest": "No Contest",
        }.get(self.result or "", "N/D")

    @property
    def method_display(self) -> str:
        if self.method and self.method_detail:
            return f"{self.method} ({self.method_detail})"
        return self.method or "N/D"


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
