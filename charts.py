"""
charts.py
---------
Geração de visualizações (Matplotlib) para o dashboard e a tela de
comparação do FightIQ.

Cada função recebe modelos já carregados do banco de dados (Fighter /
FighterStats) e devolve um objeto `matplotlib.figure.Figure`, pronto para
ser embutido em CustomTkinter via `FigureCanvasTkAgg`
(matplotlib.backends.backend_tkagg). Nenhuma função aqui calcula ou
assume estatísticas: quando um valor necessário está ausente (None), a
categoria correspondente é omitida do gráfico em vez de ser plotada como
zero (o que distorceria a leitura dos dados reais).
"""

from __future__ import annotations

from typing import List, Optional, Tuple

import matplotlib
matplotlib.use("Agg")  # backend não interativo; a interface usa FigureCanvasTkAgg
import matplotlib.pyplot as plt
import numpy as np

from models import Fighter, FighterStats
from utils import Theme, get_logger

logger = get_logger(__name__)

# Paleta usada nos gráficos (combina com Theme, mas em formato matplotlib)
COLOR_A = "#d20a0a"
COLOR_B = "#3a86ff"
COLOR_GRID = "#3a3a3e"
COLOR_TEXT = "#f5f5f7"


def _style_figure(fig: plt.Figure) -> None:
    fig.patch.set_facecolor(Theme.BG_CARD)


def _style_axes(ax: plt.Axes) -> None:
    ax.set_facecolor(Theme.BG_CARD)
    ax.tick_params(colors=COLOR_TEXT, labelsize=8)
    for spine in ax.spines.values():
        spine.set_color(COLOR_GRID)
    ax.title.set_color(COLOR_TEXT)
    ax.xaxis.label.set_color(COLOR_TEXT)
    ax.yaxis.label.set_color(COLOR_TEXT)


class ChartFactory:
    """Fábrica central de gráficos do FightIQ."""

    # Estatísticas usadas no radar (rótulo curto, atributo, valor máximo p/ normalização)
    RADAR_FIELDS: List[Tuple[str, str, float]] = [
        ("SLpM", "slpm", 8.0),
        ("Precisão", "str_acc_pct", 100.0),
        ("Defesa", "str_def_pct", 100.0),
        ("Quedas/luta", "td_avg", 6.0),
        ("Def. Quedas", "td_def_pct", 100.0),
        ("Finalizações", "sub_avg", 3.0),
    ]

    # ------------------------------------------------------------------
    # Radar chart - comparação de estilo de luta entre 2 lutadores
    # ------------------------------------------------------------------
    def radar_comparison(
        self,
        fighter_a: Fighter,
        stats_a: FighterStats,
        fighter_b: Optional[Fighter] = None,
        stats_b: Optional[FighterStats] = None,
    ) -> plt.Figure:
        labels = []
        values_a = []
        values_b = []

        for label, attr, max_value in self.RADAR_FIELDS:
            val_a = getattr(stats_a, attr, None)
            val_b = getattr(stats_b, attr, None) if stats_b else None
            # Só inclui a categoria se ao menos um lutador tiver o dado real.
            if val_a is None and val_b is None:
                continue
            labels.append(label)
            values_a.append(min((val_a or 0) / max_value, 1.0))
            values_b.append(min((val_b or 0) / max_value, 1.0) if stats_b else 0)

        fig = plt.figure(figsize=(5, 5), dpi=100)
        _style_figure(fig)

        if not labels:
            ax = fig.add_subplot(111)
            _style_axes(ax)
            ax.text(0.5, 0.5, "Dados insuficientes\npara o radar",
                    ha="center", va="center", color=COLOR_TEXT, fontsize=11)
            ax.axis("off")
            return fig

        angles = np.linspace(0, 2 * np.pi, len(labels), endpoint=False).tolist()
        angles += angles[:1]
        values_a += values_a[:1]

        ax = fig.add_subplot(111, polar=True)
        ax.set_facecolor(Theme.BG_CARD)
        ax.set_theta_offset(np.pi / 2)
        ax.set_theta_direction(-1)
        ax.set_xticks(angles[:-1])
        ax.set_xticklabels(labels, color=COLOR_TEXT, fontsize=9)
        ax.set_yticklabels([])
        ax.spines["polar"].set_color(COLOR_GRID)
        ax.grid(color=COLOR_GRID)

        ax.plot(angles, values_a, color=COLOR_A, linewidth=2, label=fighter_a.name)
        ax.fill(angles, values_a, color=COLOR_A, alpha=0.25)

        if stats_b and fighter_b:
            values_b += values_b[:1]
            ax.plot(angles, values_b, color=COLOR_B, linewidth=2, label=fighter_b.name)
            ax.fill(angles, values_b, color=COLOR_B, alpha=0.25)

        legend = ax.legend(loc="upper right", bbox_to_anchor=(1.25, 1.1), fontsize=8,
                            facecolor=Theme.BG_CARD, edgecolor=COLOR_GRID)
        for text in legend.get_texts():
            text.set_color(COLOR_TEXT)

        fig.tight_layout()
        return fig

    # ------------------------------------------------------------------
    # Barras - comparação direta de uma métrica entre 2 lutadores
    # ------------------------------------------------------------------
    def bar_comparison(
        self,
        fighter_a: Fighter,
        fighter_b: Fighter,
        stats_a: FighterStats,
        stats_b: FighterStats,
    ) -> plt.Figure:
        fields = [
            ("SLpM", "slpm"),
            ("SApM", "sapm"),
            ("Quedas/luta", "td_avg"),
            ("Sub./15min", "sub_avg"),
        ]

        labels, vals_a, vals_b = [], [], []
        for label, attr in fields:
            va = getattr(stats_a, attr, None)
            vb = getattr(stats_b, attr, None)
            if va is None and vb is None:
                continue
            labels.append(label)
            vals_a.append(va or 0)
            vals_b.append(vb or 0)

        fig = plt.figure(figsize=(6, 4), dpi=100)
        _style_figure(fig)
        ax = fig.add_subplot(111)
        _style_axes(ax)

        if not labels:
            ax.text(0.5, 0.5, "Dados insuficientes para gráfico de barras",
                     ha="center", va="center", color=COLOR_TEXT, fontsize=10, transform=ax.transAxes)
            ax.axis("off")
            return fig

        x = np.arange(len(labels))
        width = 0.35
        ax.bar(x - width / 2, vals_a, width, label=fighter_a.name, color=COLOR_A)
        ax.bar(x + width / 2, vals_b, width, label=fighter_b.name, color=COLOR_B)
        ax.set_xticks(x)
        ax.set_xticklabels(labels)
        ax.set_ylabel("Valor médio por luta")
        legend = ax.legend(facecolor=Theme.BG_CARD, edgecolor=COLOR_GRID, fontsize=8)
        for text in legend.get_texts():
            text.set_color(COLOR_TEXT)
        ax.grid(axis="y", color=COLOR_GRID, alpha=0.4)

        fig.tight_layout()
        return fig

    # ------------------------------------------------------------------
    # Pizza - distribuição das vitórias de um lutador (KO/Sub/Decisão)
    # ------------------------------------------------------------------
    def win_method_pie(self, fighter: Fighter) -> plt.Figure:
        fig = plt.figure(figsize=(4.5, 4.5), dpi=100)
        _style_figure(fig)
        ax = fig.add_subplot(111)

        data = [
            ("Nocaute", fighter.wins_ko),
            ("Finalização", fighter.wins_sub),
            ("Decisão", fighter.wins_dec),
        ]
        data = [(label, value) for label, value in data if value]

        if not data or sum(v for _, v in data) == 0:
            ax.text(0.5, 0.5, "Sem dados de método\nde vitória cadastrados",
                     ha="center", va="center", color=COLOR_TEXT, fontsize=10, transform=ax.transAxes)
            ax.axis("off")
            return fig

        labels = [d[0] for d in data]
        values = [d[1] for d in data]
        colors = [COLOR_A, "#e6a326", COLOR_B][: len(data)]

        wedges, texts, autotexts = ax.pie(
            values, labels=labels, autopct="%1.0f%%", colors=colors,
            textprops={"color": COLOR_TEXT, "fontsize": 9},
            wedgeprops={"edgecolor": Theme.BG_CARD, "linewidth": 1.5},
        )
        ax.set_title(f"Vitórias por método — {fighter.name}", color=COLOR_TEXT, fontsize=10)

        fig.tight_layout()
        return fig

    # ------------------------------------------------------------------
    # Comparação visual simples (altura/alcance lado a lado)
    # ------------------------------------------------------------------
    def physical_comparison_bar(self, fighter_a: Fighter, fighter_b: Fighter) -> plt.Figure:
        fields = [
            ("Altura (cm)", "height_cm"),
            ("Alcance (cm)", "reach_cm"),
        ]
        labels, vals_a, vals_b = [], [], []
        for label, attr in fields:
            va = getattr(fighter_a, attr, None)
            vb = getattr(fighter_b, attr, None)
            if va is None and vb is None:
                continue
            labels.append(label)
            vals_a.append(va or 0)
            vals_b.append(vb or 0)

        fig = plt.figure(figsize=(5, 3.5), dpi=100)
        _style_figure(fig)
        ax = fig.add_subplot(111)
        _style_axes(ax)

        if not labels:
            ax.text(0.5, 0.5, "Dados físicos insuficientes",
                     ha="center", va="center", color=COLOR_TEXT, fontsize=10, transform=ax.transAxes)
            ax.axis("off")
            return fig

        x = np.arange(len(labels))
        width = 0.35
        ax.barh(x - width / 2, vals_a, width, label=fighter_a.name, color=COLOR_A)
        ax.barh(x + width / 2, vals_b, width, label=fighter_b.name, color=COLOR_B)
        ax.set_yticks(x)
        ax.set_yticklabels(labels)
        legend = ax.legend(facecolor=Theme.BG_CARD, edgecolor=COLOR_GRID, fontsize=8)
        for text in legend.get_texts():
            text.set_color(COLOR_TEXT)
        ax.grid(axis="x", color=COLOR_GRID, alpha=0.4)

        fig.tight_layout()
        return fig
