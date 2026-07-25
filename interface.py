"""
interface.py
------------
Interface gráfica do FightIQ, construída com CustomTkinter.

Estrutura:
    - FightIQApp: janela principal (CTk), monta a sidebar e alterna
      entre "páginas" (frames) — Início, Buscar, Comparar, Dashboard,
      Favoritos, Histórico e Sobre.
    - Cada página é uma classe própria (ctk.CTkFrame), responsável só
      pela sua própria montagem e comportamento.
    - Toda leitura/escrita de dados passa pelo DatabaseManager
      (database.py); toda lógica de comparação passa pelo
      FighterAnalyzer (analysis.py); todo gráfico vem de ChartFactory
      (charts.py). Este módulo não contém lógica de negócio — apenas
      apresentação e orquestração de eventos de UI.
"""

from __future__ import annotations

import io
import os
from typing import Optional

import customtkinter as ctk
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from PIL import Image
import requests

from analysis import FighterAnalyzer
from charts import ChartFactory
from database import DatabaseManager
from models import ComparisonResult, Fighter, FighterStats
from utils import Theme, get_logger, safe_number, safe_percent

logger = get_logger(__name__)

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("dark-blue")

APP_TITLE = "FightIQ — UFC Performance Analyzer"
NAV_ITEMS = [
    ("home", "🏠  Início"),
    ("search", "🔍  Buscar Lutador"),
    ("compare", "⚖️  Comparar"),
    ("dashboard", "📊  Dashboard"),
    ("favorites", "⭐  Favoritos"),
    ("history", "🕓  Histórico"),
    ("about", "ℹ️  Sobre"),
]


class FightIQApp(ctk.CTk):
    """Janela principal do FightIQ."""

    def __init__(self) -> None:
        super().__init__()

        self.db = DatabaseManager()
        self.db.initialize()
        self.analyzer = FighterAnalyzer()
        self.charts = ChartFactory()

        self.title(APP_TITLE)
        self.geometry("1180x760")
        self.minsize(980, 640)
        self.configure(fg_color=Theme.BG_PRIMARY)

        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self._nav_buttons: dict[str, ctk.CTkButton] = {}
        self._pages: dict[str, ctk.CTkFrame] = {}
        self._current_page: Optional[str] = None

        self._build_sidebar()
        self._build_pages()
        self.show_page("home")

    # ------------------------------------------------------------------
    # Sidebar
    # ------------------------------------------------------------------
    def _build_sidebar(self) -> None:
        sidebar = ctk.CTkFrame(self, width=230, corner_radius=0, fg_color=Theme.BG_SIDEBAR)
        sidebar.grid(row=0, column=0, sticky="nsw")
        sidebar.grid_propagate(False)
        sidebar.grid_rowconfigure(len(NAV_ITEMS) + 2, weight=1)

        logo_frame = ctk.CTkFrame(sidebar, fg_color="transparent")
        logo_frame.grid(row=0, column=0, sticky="ew", padx=20, pady=(28, 8))
        ctk.CTkLabel(
            logo_frame, text="FIGHT", font=(Theme.FONT_FAMILY_BOLD, 22, "bold"),
            text_color=Theme.TEXT_PRIMARY,
        ).pack(side="left")
        ctk.CTkLabel(
            logo_frame, text="IQ", font=(Theme.FONT_FAMILY_BOLD, 22, "bold"),
            text_color=Theme.ACCENT,
        ).pack(side="left")

        ctk.CTkLabel(
            sidebar, text="UFC PERFORMANCE ANALYZER",
            font=(Theme.FONT_FAMILY, 10), text_color=Theme.TEXT_MUTED,
        ).grid(row=1, column=0, sticky="w", padx=22, pady=(0, 20))

        for i, (key, label) in enumerate(NAV_ITEMS, start=2):
            btn = ctk.CTkButton(
                sidebar, text=label, anchor="w", height=42, corner_radius=8,
                fg_color="transparent", hover_color=Theme.BG_CARD,
                text_color=Theme.TEXT_SECONDARY,
                font=(Theme.FONT_FAMILY, 13),
                command=lambda k=key: self.show_page(k),
            )
            btn.grid(row=i, column=0, sticky="ew", padx=12, pady=3)
            self._nav_buttons[key] = btn

        version_label = ctk.CTkLabel(
            sidebar, text="v1.0.0 · dados reais",
            font=(Theme.FONT_FAMILY, 10), text_color=Theme.TEXT_MUTED,
        )
        version_label.grid(row=len(NAV_ITEMS) + 3, column=0, sticky="sw", padx=20, pady=16)

    def _set_active_nav(self, key: str) -> None:
        for k, btn in self._nav_buttons.items():
            if k == key:
                btn.configure(fg_color=Theme.ACCENT_SOFT, text_color=Theme.TEXT_PRIMARY)
            else:
                btn.configure(fg_color="transparent", text_color=Theme.TEXT_SECONDARY)

    # ------------------------------------------------------------------
    # Páginas
    # ------------------------------------------------------------------
    def _build_pages(self) -> None:
        container = ctk.CTkFrame(self, fg_color=Theme.BG_PRIMARY)
        container.grid(row=0, column=1, sticky="nsew")
        container.grid_rowconfigure(0, weight=1)
        container.grid_columnconfigure(0, weight=1)
        self._container = container

        self._pages["home"] = HomePage(container, self)
        self._pages["search"] = SearchPage(container, self)
        self._pages["compare"] = ComparePage(container, self)
        self._pages["dashboard"] = DashboardPage(container, self)
        self._pages["favorites"] = FavoritesPage(container, self)
        self._pages["history"] = HistoryPage(container, self)
        self._pages["about"] = AboutPage(container, self)

        for page in self._pages.values():
            page.grid(row=0, column=0, sticky="nsew")

    def show_page(self, key: str, **kwargs) -> None:
        page = self._pages.get(key)
        if page is None:
            return
        self._set_active_nav(key)
        if hasattr(page, "on_show"):
            page.on_show(**kwargs)
        page.tkraise()
        self._current_page = key

    def open_fighter_profile(self, fighter_id: str) -> None:
        """Atalho usado por outras páginas para abrir um lutador na busca."""
        self.show_page("search", fighter_id=fighter_id)

    def notify(self, message: str, kind: str = "info") -> None:
        """Exibe uma notificação simples (toast) no canto da janela."""
        colors = {
            "success": Theme.SUCCESS,
            "error": Theme.ERROR,
            "info": Theme.INFO,
            "warning": Theme.WARNING,
        }
        toast = ctk.CTkFrame(self, fg_color=colors.get(kind, Theme.INFO), corner_radius=8)
        label = ctk.CTkLabel(toast, text=message, text_color="#ffffff",
                              font=(Theme.FONT_FAMILY, 12, "bold"))
        label.pack(padx=16, pady=10)
        toast.place(relx=0.98, rely=0.04, anchor="ne")
        self.after(2600, toast.destroy)


# ==========================================================================
# Componentes reutilizáveis
# ==========================================================================
class Card(ctk.CTkFrame):
    """Cartão base usado em várias telas."""

    def __init__(self, master, **kwargs):
        kwargs.setdefault("fg_color", Theme.BG_CARD)
        kwargs.setdefault("corner_radius", 12)
        super().__init__(master, **kwargs)


class StatRow(ctk.CTkFrame):
    """Linha 'rótulo: valor' usada em cards de estatísticas."""

    def __init__(self, master, label: str, value: str, **kwargs):
        super().__init__(master, fg_color="transparent", **kwargs)
        ctk.CTkLabel(self, text=label, text_color=Theme.TEXT_SECONDARY,
                     font=(Theme.FONT_FAMILY, 12), anchor="w").pack(side="left")
        ctk.CTkLabel(self, text=value, text_color=Theme.TEXT_PRIMARY,
                     font=(Theme.FONT_FAMILY, 12, "bold"), anchor="e").pack(side="right")


def load_fighter_image(fighter: Fighter, size=(140, 140)) -> Optional[ctk.CTkImage]:
    """
    Carrega a foto de um lutador. Prioriza a foto local já baixada e
    verificada por scripts/fetch_fighter_photos.py (com licença livre
    confirmada no Wikimedia Commons); só tenta a `image_url` remota
    como plano B. Retorna None (placeholder na UI) se nenhuma das duas
    existir — nunca gera uma imagem falsa.
    """
    if fighter.local_image_path and os.path.isfile(fighter.local_image_path):
        try:
            img = Image.open(fighter.local_image_path).convert("RGB")
            return ctk.CTkImage(light_image=img, dark_image=img, size=size)
        except Exception:
            logger.warning("Não foi possível abrir a foto local de %s", fighter.name)

    if not fighter.image_url:
        return None
    try:
        response = requests.get(fighter.image_url, timeout=6)
        response.raise_for_status()
        img = Image.open(io.BytesIO(response.content)).convert("RGB")
        return ctk.CTkImage(light_image=img, dark_image=img, size=size)
    except Exception:
        logger.warning("Não foi possível carregar imagem de %s", fighter.name)
        return None


def placeholder_avatar(master, size=140) -> ctk.CTkFrame:
    frame = ctk.CTkFrame(master, width=size, height=size, corner_radius=size // 2,
                          fg_color=Theme.BG_SECONDARY, border_width=2, border_color=Theme.BORDER)
    frame.pack_propagate(False)
    ctk.CTkLabel(frame, text="🥊", font=(Theme.FONT_FAMILY, 40)).pack(expand=True)
    return frame


# ==========================================================================
# Página: Início
# ==========================================================================
class HomePage(ctk.CTkFrame):
    def __init__(self, master, app: FightIQApp):
        super().__init__(master, fg_color=Theme.BG_PRIMARY)
        self.app = app

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=36, pady=(32, 8))
        ctk.CTkLabel(header, text="Bem-vindo ao FightIQ", font=(Theme.FONT_FAMILY_BOLD, 26, "bold"),
                     text_color=Theme.TEXT_PRIMARY).pack(anchor="w")
        ctk.CTkLabel(header, text="Análise de desempenho de atletas do UFC com dados reais.",
                     font=(Theme.FONT_FAMILY, 13), text_color=Theme.TEXT_SECONDARY).pack(anchor="w", pady=(4, 0))

        cards_frame = ctk.CTkFrame(self, fg_color="transparent")
        cards_frame.pack(fill="x", padx=36, pady=20)
        for i in range(4):
            cards_frame.grid_columnconfigure(i, weight=1)

        actions = [
            ("🔍", "Buscar Lutador", "Pesquise qualquer atleta cadastrado", "search"),
            ("⚖️", "Comparar", "Compare dois lutadores lado a lado", "compare"),
            ("📊", "Dashboard", "Visualize gráficos de desempenho", "dashboard"),
            ("⭐", "Favoritos", "Acesse seus lutadores salvos", "favorites"),
        ]
        for i, (icon, title, desc, target) in enumerate(actions):
            card = Card(cards_frame, cursor="hand2")
            card.grid(row=0, column=i, sticky="nsew", padx=8)
            ctk.CTkLabel(card, text=icon, font=(Theme.FONT_FAMILY, 28)).pack(pady=(20, 4))
            ctk.CTkLabel(card, text=title, font=(Theme.FONT_FAMILY_BOLD, 14, "bold"),
                         text_color=Theme.TEXT_PRIMARY).pack()
            ctk.CTkLabel(card, text=desc, font=(Theme.FONT_FAMILY, 11), text_color=Theme.TEXT_SECONDARY,
                         wraplength=180, justify="center").pack(pady=(4, 20), padx=10)
            for widget in (card, *card.winfo_children()):
                widget.bind("<Button-1>", lambda e, t=target: self.app.show_page(t))

        # Lista rápida de lutadores no banco
        list_frame = ctk.CTkFrame(self, fg_color="transparent")
        list_frame.pack(fill="both", expand=True, padx=36, pady=(10, 24))
        ctk.CTkLabel(list_frame, text="Lutadores no banco de dados", font=(Theme.FONT_FAMILY_BOLD, 15, "bold"),
                     text_color=Theme.TEXT_PRIMARY).pack(anchor="w", pady=(0, 10))

        self.roster_container = ctk.CTkScrollableFrame(list_frame, fg_color="transparent", height=220)
        self.roster_container.pack(fill="both", expand=True)

    def on_show(self, **kwargs) -> None:
        for widget in self.roster_container.winfo_children():
            widget.destroy()
        fighters = self.app.db.list_all_fighters()
        if not fighters:
            ctk.CTkLabel(self.roster_container, text="Nenhum lutador cadastrado ainda.",
                         text_color=Theme.TEXT_MUTED).pack(pady=20)
            return
        for fighter in fighters:
            row = Card(self.roster_container, corner_radius=8)
            row.pack(fill="x", pady=4)
            ctk.CTkLabel(row, text=fighter.display_name, font=(Theme.FONT_FAMILY, 13, "bold"),
                         text_color=Theme.TEXT_PRIMARY).pack(side="left", padx=16, pady=10)
            ctk.CTkLabel(row, text=fighter.weight_class or "Categoria N/D",
                         text_color=Theme.TEXT_SECONDARY, font=(Theme.FONT_FAMILY, 11)).pack(side="left", padx=10)
            ctk.CTkButton(row, text="Ver perfil", width=90, height=28, fg_color=Theme.ACCENT,
                          hover_color=Theme.ACCENT_HOVER,
                          command=lambda fid=fighter.fighter_id: self.app.open_fighter_profile(fid)
                          ).pack(side="right", padx=16, pady=8)


# ==========================================================================
# Página: Buscar Lutador
# ==========================================================================
class SearchPage(ctk.CTkFrame):
    def __init__(self, master, app: FightIQApp):
        super().__init__(master, fg_color=Theme.BG_PRIMARY)
        self.app = app
        self.current_fighter: Optional[Fighter] = None

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=36, pady=(32, 12))
        ctk.CTkLabel(header, text="Buscar Lutador", font=(Theme.FONT_FAMILY_BOLD, 22, "bold"),
                     text_color=Theme.TEXT_PRIMARY).pack(anchor="w")

        search_bar = ctk.CTkFrame(self, fg_color="transparent")
        search_bar.pack(fill="x", padx=36, pady=(0, 10))
        self.entry = ctk.CTkEntry(search_bar, placeholder_text="Digite o nome do lutador...",
                                   height=40, font=(Theme.FONT_FAMILY, 13))
        self.entry.pack(side="left", fill="x", expand=True)
        self.entry.bind("<Return>", lambda e: self._do_search())
        ctk.CTkButton(search_bar, text="Buscar", height=40, width=110, fg_color=Theme.ACCENT,
                      hover_color=Theme.ACCENT_HOVER, command=self._do_search).pack(side="left", padx=(10, 0))

        filters_bar = ctk.CTkFrame(self, fg_color="transparent")
        filters_bar.pack(fill="x", padx=36, pady=(0, 16))
        ctk.CTkLabel(filters_bar, text="Filtros:", text_color=Theme.TEXT_SECONDARY,
                     font=(Theme.FONT_FAMILY, 12)).pack(side="left", padx=(0, 8))
        self.weight_class_filter = ctk.CTkComboBox(
            filters_bar, values=["Todas as categorias"], width=200, height=32,
            command=lambda _v: self._do_search(),
        )
        self.weight_class_filter.pack(side="left", padx=(0, 8))
        self.nationality_filter = ctk.CTkComboBox(
            filters_bar, values=["Todas as nacionalidades"], width=200, height=32,
            command=lambda _v: self._do_search(),
        )
        self.nationality_filter.pack(side="left", padx=(0, 8))
        ctk.CTkButton(filters_bar, text="Limpar filtros", width=110, height=32,
                      fg_color=Theme.BG_SECONDARY, hover_color=Theme.BORDER,
                      command=self._clear_filters).pack(side="left")

        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=36, pady=(0, 24))
        body.grid_columnconfigure(0, weight=1)
        body.grid_columnconfigure(1, weight=2)
        body.grid_rowconfigure(0, weight=1)

        # Coluna de resultados
        self.results_frame = ctk.CTkScrollableFrame(body, fg_color="transparent", width=280)
        self.results_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 12))

        # Coluna de perfil
        self.profile_frame = ctk.CTkScrollableFrame(body, fg_color=Theme.BG_CARD, corner_radius=12)
        self.profile_frame.grid(row=0, column=1, sticky="nsew")
        self._render_empty_profile()

    def on_show(self, fighter_id: Optional[str] = None, **kwargs) -> None:
        weight_classes = ["Todas as categorias"] + self.app.db.list_weight_classes()
        nationalities = ["Todas as nacionalidades"] + self.app.db.list_nationalities()
        self.weight_class_filter.configure(values=weight_classes)
        self.nationality_filter.configure(values=nationalities)
        if not self.weight_class_filter.get():
            self.weight_class_filter.set("Todas as categorias")
        if not self.nationality_filter.get():
            self.nationality_filter.set("Todas as nacionalidades")

        if fighter_id is not None:
            fighter = self.app.db.get_fighter(fighter_id)
            if fighter:
                self._show_profile(fighter)

    def _clear_filters(self) -> None:
        self.weight_class_filter.set("Todas as categorias")
        self.nationality_filter.set("Todas as nacionalidades")
        self._do_search()

    def _do_search(self) -> None:
        query = self.entry.get().strip()
        weight_class = self.weight_class_filter.get()
        nationality = self.nationality_filter.get()
        weight_class = None if weight_class in ("", "Todas as categorias") else weight_class
        nationality = None if nationality in ("", "Todas as nacionalidades") else nationality

        for widget in self.results_frame.winfo_children():
            widget.destroy()

        if not query and not weight_class and not nationality:
            ctk.CTkLabel(self.results_frame, text="Digite um nome ou escolha um filtro para pesquisar.",
                         text_color=Theme.TEXT_MUTED, wraplength=240).pack(pady=20)
            return

        results = self.app.db.filter_fighters(query=query or None, weight_class=weight_class,
                                                nationality=nationality)
        if query:
            self.app.db.log_search(query, results[0].fighter_id if results else None)

        if not results:
            ctk.CTkLabel(self.results_frame, text="Nenhum lutador encontrado com esses filtros.",
                         text_color=Theme.TEXT_MUTED, wraplength=240).pack(pady=20)
            return

        ctk.CTkLabel(self.results_frame, text=f"{len(results)} encontrado(s)",
                     text_color=Theme.TEXT_MUTED, font=(Theme.FONT_FAMILY, 11)).pack(anchor="w", pady=(0, 4))

        for fighter in results:
            item = Card(self.results_frame, corner_radius=8, cursor="hand2")
            item.pack(fill="x", pady=4)
            ctk.CTkLabel(item, text=fighter.display_name, font=(Theme.FONT_FAMILY, 13, "bold"),
                         text_color=Theme.TEXT_PRIMARY, anchor="w").pack(fill="x", padx=14, pady=(10, 0))
            ctk.CTkLabel(item, text=f"{fighter.weight_class or 'N/D'} · {fighter.nationality or 'N/D'}",
                         text_color=Theme.TEXT_SECONDARY, font=(Theme.FONT_FAMILY, 11), anchor="w"
                         ).pack(fill="x", padx=14, pady=(0, 10))
            for widget in (item, *item.winfo_children()):
                widget.bind("<Button-1>", lambda e, f=fighter: self._show_profile(f))

    def _render_empty_profile(self) -> None:
        for widget in self.profile_frame.winfo_children():
            widget.destroy()
        ctk.CTkLabel(self.profile_frame, text="Pesquise um lutador para ver o perfil completo.",
                     text_color=Theme.TEXT_MUTED, font=(Theme.FONT_FAMILY, 13)).pack(expand=True, pady=60)

    def _show_profile(self, fighter: Fighter) -> None:
        self.current_fighter = fighter
        stats = self.app.db.get_fighter_stats(fighter.fighter_id)

        for widget in self.profile_frame.winfo_children():
            widget.destroy()

        top = ctk.CTkFrame(self.profile_frame, fg_color="transparent")
        top.pack(fill="x", padx=24, pady=(24, 10))

        img = load_fighter_image(fighter)
        if img:
            ctk.CTkLabel(top, image=img, text="").pack(side="left", padx=(0, 20))
        else:
            placeholder_avatar(top).pack(side="left", padx=(0, 20))
        info = ctk.CTkFrame(top, fg_color="transparent")
        info.pack(side="left", fill="both", expand=True)
        ctk.CTkLabel(info, text=fighter.display_name, font=(Theme.FONT_FAMILY_BOLD, 20, "bold"),
                     text_color=Theme.TEXT_PRIMARY, anchor="w").pack(fill="x")
        subtitle = " · ".join(filter(None, [fighter.weight_class, fighter.nationality]))
        ctk.CTkLabel(info, text=subtitle or "Informações incompletas", text_color=Theme.TEXT_SECONDARY,
                     font=(Theme.FONT_FAMILY, 13), anchor="w").pack(fill="x", pady=(2, 0))
        ctk.CTkLabel(info, text=f"Cartel: {fighter.record_display}", text_color=Theme.ACCENT,
                     font=(Theme.FONT_FAMILY, 14, "bold"), anchor="w").pack(fill="x", pady=(6, 0))
        if fighter.ranking:
            ctk.CTkLabel(info, text=f"Ranking: {fighter.ranking}", text_color=Theme.TEXT_SECONDARY,
                         font=(Theme.FONT_FAMILY, 12), anchor="w").pack(fill="x", pady=(2, 0))

        actions = ctk.CTkFrame(top, fg_color="transparent")
        actions.pack(side="right", anchor="n")
        is_fav = self.app.db.is_favorite(fighter.fighter_id)
        fav_btn = ctk.CTkButton(
            actions, text=("★ Remover Favorito" if is_fav else "☆ Favoritar"), width=160, height=32,
            fg_color=Theme.ACCENT if not is_fav else Theme.BG_SECONDARY,
            hover_color=Theme.ACCENT_HOVER,
        )
        fav_btn.configure(command=lambda: self._toggle_favorite(fighter, fav_btn))
        fav_btn.pack()

        # Dados biográficos
        bio_card = Card(self.profile_frame)
        bio_card.pack(fill="x", padx=24, pady=10)
        ctk.CTkLabel(bio_card, text="Dados Biográficos", font=(Theme.FONT_FAMILY_BOLD, 13, "bold"),
                     text_color=Theme.TEXT_PRIMARY, anchor="w").pack(fill="x", padx=16, pady=(14, 6))
        bio_rows = [
            ("Idade", (f"{fighter.age} anos*" if fighter.age_is_estimated else f"{fighter.age} anos") if fighter.age else "N/D"),
            ("Nacionalidade", fighter.nationality or "N/D"),
            ("Categoria", fighter.weight_class or "N/D"),
            ("Altura", f"{fighter.height_display_metric} ({fighter.height_display})"),
            ("Alcance", f"{fighter.reach_display_metric} ({fighter.reach_display})"),
            ("Postura", fighter.stance or "N/D"),
            ("Vitórias", str(fighter.wins)),
            ("Derrotas", str(fighter.losses)),
            ("Empates", str(fighter.draws)),
            ("Vitórias por Nocaute", str(fighter.wins_ko) if fighter.wins_ko is not None else "N/D"),
            ("Vitórias por Finalização", str(fighter.wins_sub) if fighter.wins_sub is not None else "N/D"),
            ("Vitórias por Decisão", str(fighter.wins_dec) if fighter.wins_dec is not None else "N/D"),
        ]
        for label, value in bio_rows:
            StatRow(bio_card, label, value).pack(fill="x", padx=16, pady=3)
        ctk.CTkLabel(bio_card, text="").pack(pady=4)

        # Estatísticas de desempenho
        stats_card = Card(self.profile_frame)
        stats_card.pack(fill="x", padx=24, pady=10)
        ctk.CTkLabel(stats_card, text="Estatísticas de Desempenho", font=(Theme.FONT_FAMILY_BOLD, 13, "bold"),
                     text_color=Theme.TEXT_PRIMARY, anchor="w").pack(fill="x", padx=16, pady=(14, 6))
        stat_rows = [
            ("Golpes Significativos / min", safe_number(stats.slpm)),
            ("Precisão de Golpes", safe_percent(stats.str_acc_pct)),
            ("Golpes Absorvidos / min", safe_number(stats.sapm)),
            ("Defesa de Golpes", safe_percent(stats.str_def_pct)),
            ("Quedas por Luta", safe_number(stats.td_avg)),
            ("Precisão de Quedas", safe_percent(stats.td_acc_pct)),
            ("Defesa de Quedas", safe_percent(stats.td_def_pct)),
            ("Tentativas de Finalização /15min", safe_number(stats.sub_avg)),
            ("Tempo Médio de Luta", stats.avg_fight_time or "N/D"),
        ]
        for label, value in stat_rows:
            StatRow(stats_card, label, value).pack(fill="x", padx=16, pady=3)
        ctk.CTkLabel(stats_card, text="").pack(pady=4)

        missing = self.app.analyzer.scan_missing_data(stats)
        if missing:
            ctk.CTkLabel(
                self.profile_frame,
                text="⚠ Dados ainda não disponíveis nesta base para: " + ", ".join(missing),
                text_color=Theme.WARNING, font=(Theme.FONT_FAMILY, 10), wraplength=520, justify="left",
            ).pack(anchor="w", padx=28, pady=(0, 6))

        if fighter.age_is_estimated:
            ctk.CTkLabel(
                self.profile_frame,
                text="* idade informada diretamente pela fonte (sem data de nascimento exata); "
                     "pode estar até 1 ano desatualizada.",
                text_color=Theme.TEXT_MUTED, font=(Theme.FONT_FAMILY, 10), wraplength=520, justify="left",
            ).pack(anchor="w", padx=28, pady=(0, 6))

        if fighter.manually_overridden_fields:
            ctk.CTkLabel(
                self.profile_frame,
                text="✏️ Campos verificados manualmente: " + fighter.manually_overridden_fields,
                text_color=Theme.INFO, font=(Theme.FONT_FAMILY, 10), wraplength=520, justify="left",
            ).pack(anchor="w", padx=28, pady=(0, 6))

        if fighter.source:
            source_text = f"Fonte dos dados: {fighter.source}"
            if fighter.last_updated:
                source_text += f" · atualizado em {fighter.last_updated}"
            ctk.CTkLabel(self.profile_frame, text=source_text, text_color=Theme.TEXT_MUTED,
                         font=(Theme.FONT_FAMILY, 10)).pack(anchor="w", padx=28, pady=(0, 4))

        if fighter.local_image_path and fighter.image_attribution:
            photo_credit = f"Foto: {fighter.image_attribution} · {fighter.image_license or 'licença livre'} · Wikimedia Commons"
            ctk.CTkLabel(self.profile_frame, text=photo_credit, text_color=Theme.TEXT_MUTED,
                         font=(Theme.FONT_FAMILY, 10)).pack(anchor="w", padx=28, pady=(0, 20))

    def _toggle_favorite(self, fighter: Fighter, button: ctk.CTkButton) -> None:
        if self.app.db.is_favorite(fighter.fighter_id):
            self.app.db.remove_favorite(fighter.fighter_id)
            button.configure(text="☆ Favoritar", fg_color=Theme.ACCENT)
            self.app.notify(f"{fighter.name} removido dos favoritos.", "info")
        else:
            self.app.db.add_favorite(fighter.fighter_id, fighter.name)
            button.configure(text="★ Remover Favorito", fg_color=Theme.BG_SECONDARY)
            self.app.notify(f"{fighter.name} adicionado aos favoritos!", "success")


# ==========================================================================
# Página: Comparar
# ==========================================================================
class ComparePage(ctk.CTkFrame):
    def __init__(self, master, app: FightIQApp):
        super().__init__(master, fg_color=Theme.BG_PRIMARY)
        self.app = app

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=36, pady=(32, 12))
        ctk.CTkLabel(header, text="Comparar Lutadores", font=(Theme.FONT_FAMILY_BOLD, 22, "bold"),
                     text_color=Theme.TEXT_PRIMARY).pack(anchor="w")

        selectors = ctk.CTkFrame(self, fg_color="transparent")
        selectors.pack(fill="x", padx=36, pady=(0, 16))
        selectors.grid_columnconfigure(0, weight=1)
        selectors.grid_columnconfigure(1, weight=0)
        selectors.grid_columnconfigure(2, weight=1)

        self.combo_a = ctk.CTkComboBox(selectors, values=[], height=38)
        self.combo_a.grid(row=0, column=0, sticky="ew", padx=(0, 10))
        ctk.CTkLabel(selectors, text="VS", font=(Theme.FONT_FAMILY_BOLD, 16, "bold"),
                     text_color=Theme.ACCENT).grid(row=0, column=1, padx=8)
        self.combo_b = ctk.CTkComboBox(selectors, values=[], height=38)
        self.combo_b.grid(row=0, column=2, sticky="ew", padx=(10, 0))

        ctk.CTkButton(self, text="Comparar", height=40, fg_color=Theme.ACCENT,
                      hover_color=Theme.ACCENT_HOVER, command=self._do_compare
                      ).pack(padx=36, pady=(0, 16), anchor="w")

        self.result_container = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self.result_container.pack(fill="both", expand=True, padx=36, pady=(0, 24))

        self._fighter_map: dict[str, str] = {}

    def on_show(self, **kwargs) -> None:
        fighters = self.app.db.list_all_fighters()
        self._fighter_map = {f.display_name: f.fighter_id for f in fighters}
        names = list(self._fighter_map.keys())
        self.combo_a.configure(values=names)
        self.combo_b.configure(values=names)
        if names:
            self.combo_a.set(names[0])
            self.combo_b.set(names[1] if len(names) > 1 else names[0])

    def _do_compare(self) -> None:
        name_a, name_b = self.combo_a.get(), self.combo_b.get()
        id_a = self._fighter_map.get(name_a)
        id_b = self._fighter_map.get(name_b)

        for widget in self.result_container.winfo_children():
            widget.destroy()

        if not id_a or not id_b:
            self.app.notify("Selecione dois lutadores válidos.", "warning")
            return
        if id_a == id_b:
            self.app.notify("Escolha dois lutadores diferentes.", "warning")
            return

        fighter_a = self.app.db.get_fighter(id_a)
        fighter_b = self.app.db.get_fighter(id_b)
        stats_a = self.app.db.get_fighter_stats(id_a)
        stats_b = self.app.db.get_fighter_stats(id_b)

        result = self.app.analyzer.compare(fighter_a, fighter_b, stats_a, stats_b)
        self._render_result(result)

    def _render_result(self, result: ComparisonResult) -> None:
        narrative_card = Card(self.result_container)
        narrative_card.pack(fill="x", pady=(0, 16))
        ctk.CTkLabel(narrative_card, text="🧠 Análise Inteligente", font=(Theme.FONT_FAMILY_BOLD, 14, "bold"),
                     text_color=Theme.TEXT_PRIMARY, anchor="w").pack(fill="x", padx=18, pady=(16, 6))
        ctk.CTkLabel(narrative_card, text=result.narrative, font=(Theme.FONT_FAMILY, 13),
                     text_color=Theme.TEXT_SECONDARY, wraplength=880, justify="left", anchor="w"
                     ).pack(fill="x", padx=18, pady=(0, 16))

        # Comparação lado a lado
        side_by_side = ctk.CTkFrame(self.result_container, fg_color="transparent")
        side_by_side.pack(fill="x", pady=(0, 16))
        side_by_side.grid_columnconfigure(0, weight=1)
        side_by_side.grid_columnconfigure(1, weight=1)

        self._render_fighter_summary(side_by_side, result.fighter_a, result.stats_a, column=0)
        self._render_fighter_summary(side_by_side, result.fighter_b, result.stats_b, column=1)

        # Destaques automáticos
        highlights_card = Card(self.result_container)
        highlights_card.pack(fill="x", pady=(0, 16))
        ctk.CTkLabel(highlights_card, text="Vantagens Automáticas", font=(Theme.FONT_FAMILY_BOLD, 14, "bold"),
                     text_color=Theme.TEXT_PRIMARY, anchor="w").pack(fill="x", padx=18, pady=(16, 8))
        if not result.highlights:
            ctk.CTkLabel(highlights_card, text="Dados insuficientes para destacar vantagens.",
                         text_color=Theme.TEXT_MUTED).pack(padx=18, pady=(0, 16), anchor="w")
        for h in result.highlights:
            row = ctk.CTkFrame(highlights_card, fg_color="transparent")
            row.pack(fill="x", padx=18, pady=3)
            ctk.CTkLabel(row, text=f"● {h.category}", text_color=Theme.TEXT_SECONDARY,
                         font=(Theme.FONT_FAMILY, 12), anchor="w", width=220).pack(side="left")
            ctk.CTkLabel(row, text=f"{h.value_a}", text_color=(
                Theme.SUCCESS if h.winner_side == "a" else Theme.TEXT_MUTED),
                         font=(Theme.FONT_FAMILY, 12, "bold")).pack(side="left", padx=10)
            ctk.CTkLabel(row, text="vs", text_color=Theme.TEXT_MUTED, font=(Theme.FONT_FAMILY, 10)).pack(side="left", padx=4)
            ctk.CTkLabel(row, text=f"{h.value_b}", text_color=(
                Theme.SUCCESS if h.winner_side == "b" else Theme.TEXT_MUTED),
                         font=(Theme.FONT_FAMILY, 12, "bold")).pack(side="left", padx=10)
            ctk.CTkLabel(row, text=f"🏆 {h.winner_name}", text_color=Theme.ACCENT,
                         font=(Theme.FONT_FAMILY, 11, "bold")).pack(side="right")
        ctk.CTkLabel(highlights_card, text="").pack(pady=4)

        # Gráficos
        charts_card = Card(self.result_container)
        charts_card.pack(fill="x", pady=(0, 16))
        ctk.CTkLabel(charts_card, text="Comparação Visual", font=(Theme.FONT_FAMILY_BOLD, 14, "bold"),
                     text_color=Theme.TEXT_PRIMARY, anchor="w").pack(fill="x", padx=18, pady=(16, 8))
        charts_row = ctk.CTkFrame(charts_card, fg_color="transparent")
        charts_row.pack(fill="x", padx=18, pady=(0, 18))

        radar_fig = self.app.charts.radar_comparison(result.fighter_a, result.stats_a,
                                                       result.fighter_b, result.stats_b)
        bar_fig = self.app.charts.bar_comparison(result.fighter_a, result.fighter_b,
                                                   result.stats_a, result.stats_b)
        _embed_figure(charts_row, radar_fig, side="left")
        _embed_figure(charts_row, bar_fig, side="left")

    def _render_fighter_summary(self, master, fighter: Fighter, stats: FighterStats, column: int) -> None:
        card = Card(master)
        card.grid(row=0, column=column, sticky="nsew", padx=6)
        ctk.CTkLabel(card, text=fighter.display_name, font=(Theme.FONT_FAMILY_BOLD, 15, "bold"),
                     text_color=Theme.TEXT_PRIMARY).pack(pady=(16, 2))
        ctk.CTkLabel(card, text=fighter.record_display, text_color=Theme.ACCENT,
                     font=(Theme.FONT_FAMILY, 13, "bold")).pack(pady=(0, 10))
        rows = [
            ("Altura", f"{fighter.height_display_metric} ({fighter.height_display})"),
            ("Alcance", f"{fighter.reach_display_metric} ({fighter.reach_display})"),
            ("Idade", (f"{fighter.age} anos*" if fighter.age_is_estimated else f"{fighter.age} anos") if fighter.age else "N/D"),
            ("SLpM", safe_number(stats.slpm)),
            ("Defesa de Quedas", safe_percent(stats.td_def_pct)),
        ]
        for label, value in rows:
            StatRow(card, label, value).pack(fill="x", padx=18, pady=3)
        ctk.CTkLabel(card, text="").pack(pady=6)


# ==========================================================================
# Página: Dashboard
# ==========================================================================
class DashboardPage(ctk.CTkFrame):
    def __init__(self, master, app: FightIQApp):
        super().__init__(master, fg_color=Theme.BG_PRIMARY)
        self.app = app

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=36, pady=(32, 12))
        ctk.CTkLabel(header, text="Dashboard", font=(Theme.FONT_FAMILY_BOLD, 22, "bold"),
                     text_color=Theme.TEXT_PRIMARY).pack(anchor="w")

        selector_row = ctk.CTkFrame(self, fg_color="transparent")
        selector_row.pack(fill="x", padx=36, pady=(0, 12))
        ctk.CTkLabel(selector_row, text="Lutador:", text_color=Theme.TEXT_SECONDARY).pack(side="left", padx=(0, 8))
        self.combo = ctk.CTkComboBox(selector_row, values=[], width=300, command=lambda _v: self._render())
        self.combo.pack(side="left")

        self.content = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self.content.pack(fill="both", expand=True, padx=36, pady=(0, 24))

        self._fighter_map: dict[str, str] = {}

    def on_show(self, **kwargs) -> None:
        fighters = self.app.db.list_all_fighters()
        self._fighter_map = {f.display_name: f.fighter_id for f in fighters}
        names = list(self._fighter_map.keys())
        self.combo.configure(values=names)
        if names and not self.combo.get():
            self.combo.set(names[0])
        if names:
            self._render()

    def _render(self) -> None:
        for widget in self.content.winfo_children():
            widget.destroy()

        name = self.combo.get()
        fighter_id = self._fighter_map.get(name)
        if not fighter_id:
            return
        fighter = self.app.db.get_fighter(fighter_id)
        stats = self.app.db.get_fighter_stats(fighter_id)

        row1 = ctk.CTkFrame(self.content, fg_color="transparent")
        row1.pack(fill="x", pady=8)

        radar_card = Card(row1)
        radar_card.pack(side="left", padx=(0, 10))
        ctk.CTkLabel(radar_card, text="Perfil de Desempenho (Radar)", font=(Theme.FONT_FAMILY_BOLD, 12, "bold"),
                     text_color=Theme.TEXT_PRIMARY).pack(pady=(12, 0))
        radar_fig = self.app.charts.radar_comparison(fighter, stats)
        _embed_figure(radar_card, radar_fig)

        pie_card = Card(row1)
        pie_card.pack(side="left", padx=(0, 10))
        ctk.CTkLabel(pie_card, text="Vitórias por Método", font=(Theme.FONT_FAMILY_BOLD, 12, "bold"),
                     text_color=Theme.TEXT_PRIMARY).pack(pady=(12, 0))
        pie_fig = self.app.charts.win_method_pie(fighter)
        _embed_figure(pie_card, pie_fig)


# ==========================================================================
# Página: Favoritos
# ==========================================================================
class FavoritesPage(ctk.CTkFrame):
    def __init__(self, master, app: FightIQApp):
        super().__init__(master, fg_color=Theme.BG_PRIMARY)
        self.app = app

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=36, pady=(32, 16))
        ctk.CTkLabel(header, text="Favoritos", font=(Theme.FONT_FAMILY_BOLD, 22, "bold"),
                     text_color=Theme.TEXT_PRIMARY).pack(anchor="w")

        self.list_container = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self.list_container.pack(fill="both", expand=True, padx=36, pady=(0, 24))

    def on_show(self, **kwargs) -> None:
        for widget in self.list_container.winfo_children():
            widget.destroy()

        favorites = self.app.db.list_favorites()
        if not favorites:
            ctk.CTkLabel(self.list_container, text="Você ainda não favoritou nenhum lutador.",
                         text_color=Theme.TEXT_MUTED).pack(pady=30)
            return

        for fav in favorites:
            row = Card(self.list_container)
            row.pack(fill="x", pady=5)
            ctk.CTkLabel(row, text=fav.name, font=(Theme.FONT_FAMILY, 13, "bold"),
                         text_color=Theme.TEXT_PRIMARY).pack(side="left", padx=16, pady=12)
            ctk.CTkLabel(row, text=fav.added_at.strftime("Adicionado em %d/%m/%Y"),
                         text_color=Theme.TEXT_SECONDARY, font=(Theme.FONT_FAMILY, 11)).pack(side="left", padx=10)
            ctk.CTkButton(row, text="Ver perfil", width=90, height=28, fg_color=Theme.ACCENT,
                          hover_color=Theme.ACCENT_HOVER,
                          command=lambda fid=fav.fighter_id: self.app.open_fighter_profile(fid)
                          ).pack(side="right", padx=8, pady=8)
            ctk.CTkButton(row, text="Remover", width=90, height=28, fg_color=Theme.BG_SECONDARY,
                          hover_color=Theme.ERROR,
                          command=lambda fid=fav.fighter_id: self._remove(fid)
                          ).pack(side="right", padx=8, pady=8)

    def _remove(self, fighter_id: str) -> None:
        self.app.db.remove_favorite(fighter_id)
        self.app.notify("Favorito removido.", "info")
        self.on_show()


# ==========================================================================
# Página: Histórico
# ==========================================================================
class HistoryPage(ctk.CTkFrame):
    def __init__(self, master, app: FightIQApp):
        super().__init__(master, fg_color=Theme.BG_PRIMARY)
        self.app = app

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=36, pady=(32, 16))
        ctk.CTkLabel(header, text="Histórico de Pesquisas", font=(Theme.FONT_FAMILY_BOLD, 22, "bold"),
                     text_color=Theme.TEXT_PRIMARY).pack(side="left")
        ctk.CTkButton(header, text="Limpar histórico", fg_color=Theme.BG_SECONDARY, hover_color=Theme.ERROR,
                      width=140, command=self._clear).pack(side="right")

        self.list_container = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self.list_container.pack(fill="both", expand=True, padx=36, pady=(0, 24))

    def on_show(self, **kwargs) -> None:
        for widget in self.list_container.winfo_children():
            widget.destroy()

        entries = self.app.db.list_history()
        if not entries:
            ctk.CTkLabel(self.list_container, text="Nenhuma pesquisa realizada ainda.",
                         text_color=Theme.TEXT_MUTED).pack(pady=30)
            return

        for entry in entries:
            row = Card(self.list_container, corner_radius=8)
            row.pack(fill="x", pady=4)
            ctk.CTkLabel(row, text=f'"{entry.query}"', font=(Theme.FONT_FAMILY, 13),
                         text_color=Theme.TEXT_PRIMARY).pack(side="left", padx=16, pady=10)
            ctk.CTkLabel(row, text=entry.searched_at.strftime("%d/%m/%Y %H:%M"),
                         text_color=Theme.TEXT_MUTED, font=(Theme.FONT_FAMILY, 11)).pack(side="right", padx=16)

    def _clear(self) -> None:
        self.app.db.clear_history()
        self.app.notify("Histórico limpo.", "info")
        self.on_show()


# ==========================================================================
# Página: Sobre
# ==========================================================================
class AboutPage(ctk.CTkFrame):
    def __init__(self, master, app: FightIQApp):
        super().__init__(master, fg_color=Theme.BG_PRIMARY)
        self.app = app

        content = ctk.CTkScrollableFrame(self, fg_color="transparent")
        content.pack(fill="both", expand=True, padx=36, pady=32)

        ctk.CTkLabel(content, text="Sobre o FightIQ", font=(Theme.FONT_FAMILY_BOLD, 22, "bold"),
                     text_color=Theme.TEXT_PRIMARY).pack(anchor="w", pady=(0, 12))

        text = (
            "FightIQ é um analisador de desempenho de atletas do UFC, construído em "
            "Python com CustomTkinter, SQLite, Pandas e Matplotlib.\n\n"
            "Princípio central do projeto: nenhum dado exibido é inventado. Todos os "
            "valores de cartel, físico e estatísticas de luta vêm de um banco SQLite "
            "local, populado a partir de dados públicos verificados manualmente "
            "(ver a coluna 'Fonte' em cada perfil de lutador). Quando um dado não "
            "está disponível na fonte, o sistema exibe 'N/D' em vez de estimar ou "
            "arredondar valores.\n\n"
            "O projeto foi desenhado em módulos independentes (models, database, "
            "api, analysis, charts, interface) para que a fonte de dados possa ser "
            "atualizada ou substituída (por uma API ao vivo, por exemplo) sem exigir "
            "mudanças na interface ou na lógica de análise."
        )
        ctk.CTkLabel(content, text=text, text_color=Theme.TEXT_SECONDARY, font=(Theme.FONT_FAMILY, 13),
                     wraplength=760, justify="left").pack(anchor="w")

        ctk.CTkLabel(content, text="Tecnologias", font=(Theme.FONT_FAMILY_BOLD, 15, "bold"),
                     text_color=Theme.TEXT_PRIMARY).pack(anchor="w", pady=(24, 8))
        for tech in ["Python 3", "CustomTkinter", "SQLite3", "Pandas", "Matplotlib", "Requests", "Pillow"]:
            ctk.CTkLabel(content, text=f"• {tech}", text_color=Theme.TEXT_SECONDARY,
                         font=(Theme.FONT_FAMILY, 12)).pack(anchor="w")

        ctk.CTkLabel(content, text="Versão 1.0.0 — projeto pessoal de portfólio.",
                     text_color=Theme.TEXT_MUTED, font=(Theme.FONT_FAMILY, 11)).pack(anchor="w", pady=(24, 0))


# ==========================================================================
# Helpers
# ==========================================================================
def _embed_figure(master, figure, side: Optional[str] = None) -> FigureCanvasTkAgg:
    canvas = FigureCanvasTkAgg(figure, master=master)
    canvas.draw()
    widget = canvas.get_tk_widget()
    widget.configure(bg=Theme.BG_CARD, highlightthickness=0)
    if side:
        widget.pack(side=side, padx=8, pady=8)
    else:
        widget.pack(padx=8, pady=8)
    return canvas
