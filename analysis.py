"""
analysis.py
-----------
Motor de análise do FightIQ.

Este módulo contém toda a lógica de comparação entre lutadores e a
geração da "Análise Inteligente" em texto. É o módulo mais sensível do
projeto em relação ao requisito de nunca inventar dados: cada frase
gerada aqui é derivada estritamente dos campos numéricos já presentes no
banco (models.Fighter / models.FighterStats). Quando um dado necessário
para uma comparação específica não existe (é None), essa comparação é
simplesmente omitida da análise — o texto nunca "preenche a lacuna" com
uma suposição.
"""

from __future__ import annotations

from typing import List, Optional, Tuple

from models import ComparisonHighlight, ComparisonResult, Fighter, FighterStats
from utils import get_logger

logger = get_logger(__name__)


class FighterAnalyzer:
    """Responsável por comparar dois lutadores e produzir uma análise textual."""

    # Cada entrada: (rótulo, extrator de valor, "maior é melhor?")
    _NUMERIC_CRITERIA: List[Tuple[str, str, bool]] = [
        ("Alcance", "reach_cm", True),
        ("Altura", "height_cm", True),
        ("Experiência (nº de lutas)", "total_fights", True),
    ]

    _STAT_CRITERIA: List[Tuple[str, str, bool]] = [
        ("Volume de Striking (SLpM)", "slpm", True),
        ("Precisão de Striking", "str_acc_pct", True),
        ("Defesa de Striking", "str_def_pct", True),
        ("Golpes Absorvidos por Minuto", "sapm", False),
        ("Média de Quedas", "td_avg", True),
        ("Defesa de Quedas", "td_def_pct", True),
        ("Tentativas de Finalização", "sub_avg", True),
    ]

    def compare(
        self,
        fighter_a: Fighter,
        fighter_b: Fighter,
        stats_a: FighterStats,
        stats_b: FighterStats,
    ) -> ComparisonResult:
        """Constrói o ComparisonResult completo (destaques + narrativa)."""
        highlights = self._build_highlights(fighter_a, fighter_b, stats_a, stats_b)
        narrative = self._build_narrative(fighter_a, fighter_b, stats_a, stats_b, highlights)

        result = ComparisonResult(
            fighter_a=fighter_a,
            fighter_b=fighter_b,
            stats_a=stats_a,
            stats_b=stats_b,
            highlights=highlights,
            narrative=narrative,
        )
        logger.info(
            "Comparação gerada: %s vs %s (%d destaques)",
            fighter_a.name, fighter_b.name, len(highlights),
        )
        return result

    # ------------------------------------------------------------------
    # Destaques (vantagens automáticas)
    # ------------------------------------------------------------------
    def _build_highlights(
        self,
        fighter_a: Fighter,
        fighter_b: Fighter,
        stats_a: FighterStats,
        stats_b: FighterStats,
    ) -> List[ComparisonHighlight]:
        highlights: List[ComparisonHighlight] = []

        for label, attr, higher_is_better in self._NUMERIC_CRITERIA:
            val_a = getattr(fighter_a, attr, None)
            val_b = getattr(fighter_b, attr, None)
            highlight = self._compare_values(
                label, val_a, val_b, fighter_a.name, fighter_b.name, higher_is_better
            )
            if highlight:
                highlights.append(highlight)

        for label, attr, higher_is_better in self._STAT_CRITERIA:
            val_a = getattr(stats_a, attr, None)
            val_b = getattr(stats_b, attr, None)
            highlight = self._compare_values(
                label, val_a, val_b, fighter_a.name, fighter_b.name, higher_is_better
            )
            if highlight:
                highlights.append(highlight)

        return highlights

    @staticmethod
    def _compare_values(
        label: str,
        val_a: Optional[float],
        val_b: Optional[float],
        name_a: str,
        name_b: str,
        higher_is_better: bool,
    ) -> Optional[ComparisonHighlight]:
        # Requisito crítico: só compara quando AMBOS os valores existem.
        if val_a is None or val_b is None:
            return None
        if val_a == val_b:
            return None

        a_wins = (val_a > val_b) if higher_is_better else (val_a < val_b)
        winner_name = name_a if a_wins else name_b
        winner_side = "a" if a_wins else "b"

        return ComparisonHighlight(
            category=label,
            winner_name=winner_name,
            value_a=_format_value(val_a),
            value_b=_format_value(val_b),
            winner_side=winner_side,
        )

    # ------------------------------------------------------------------
    # Narrativa em linguagem natural
    # ------------------------------------------------------------------
    def _build_narrative(
        self,
        fighter_a: Fighter,
        fighter_b: Fighter,
        stats_a: FighterStats,
        stats_b: FighterStats,
        highlights: List[ComparisonHighlight],
    ) -> str:
        """
        Gera um parágrafo descritivo com base exclusivamente nos destaques
        já calculados (ou seja, exclusivamente em dados reais presentes
        no banco). Se não houver destaques suficientes, retorna uma
        mensagem honesta informando a limitação dos dados disponíveis.
        """
        by_a = [h for h in highlights if h.winner_side == "a"]
        by_b = [h for h in highlights if h.winner_side == "b"]

        if not by_a and not by_b:
            return (
                f"Não há estatísticas suficientes cadastradas para {fighter_a.name} "
                f"e {fighter_b.name} para gerar uma análise comparativa neste momento."
            )

        sentence_a = ""
        sentence_b = ""

        if by_a:
            categories = _join_categories([h.category for h in by_a])
            sentence_a = f"{fighter_a.name} apresenta vantagem em {categories}"

        if by_b:
            categories = _join_categories([h.category for h in by_b])
            verb = "enquanto" if by_a else "apresenta vantagem em"
            if by_a:
                sentence_b = f"enquanto {fighter_b.name} se destaca em {categories}"
            else:
                sentence_b = f"{fighter_b.name} apresenta vantagem em {categories}"

        if sentence_a and sentence_b:
            sentence = f"{sentence_a}, {sentence_b}"
        else:
            sentence = sentence_a or sentence_b

        sentence = sentence.strip()
        if not sentence.endswith("."):
            sentence += "."

        return sentence

    def scan_missing_data(self, stats: FighterStats) -> List[str]:
        """Retorna os rótulos de estatísticas ausentes para um lutador (uso na UI)."""
        missing = []
        field_labels = {
            "slpm": "Golpes significativos por minuto",
            "str_acc_pct": "Precisão de golpes",
            "sapm": "Golpes absorvidos por minuto",
            "str_def_pct": "Defesa de golpes",
            "td_avg": "Quedas por luta",
            "td_acc_pct": "Precisão de quedas",
            "td_def_pct": "Defesa de quedas",
            "sub_avg": "Tentativas de finalização",
        }
        for attr, label in field_labels.items():
            if getattr(stats, attr, None) is None:
                missing.append(label)
        return missing


# --------------------------------------------------------------------------
# Helpers privados
# --------------------------------------------------------------------------
def _format_value(value: float) -> str:
    if isinstance(value, int) or float(value).is_integer():
        return str(int(value))
    return f"{value:.1f}"


def _join_categories(categories: List[str]) -> str:
    """Junta uma lista de categorias em português: 'A', 'A e B', 'A, B e C'."""
    if len(categories) == 1:
        return categories[0]
    return ", ".join(categories[:-1]) + " e " + categories[-1]
