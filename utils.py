"""
utils.py
--------
Funções utilitárias e configuração transversal do FightIQ.

Responsabilidades deste módulo:
    - Configuração centralizada de logging (arquivo + console).
    - Constantes de caminho (assets, banco de dados, ícones, imagens).
    - Pequenas funções de formatação usadas em várias telas da interface
      (idade a partir da data de nascimento, cm -> pés/polegadas, etc.).
    - Paleta de cores e fontes usadas pela interface (tema UFC/dark mode).

Nenhuma lógica de negócio (análise, banco de dados, etc.) deve viver aqui;
este módulo existe apenas para evitar duplicação de código auxiliar entre
os demais módulos do projeto.
"""

from __future__ import annotations

import logging
import os
from datetime import date, datetime
from logging.handlers import RotatingFileHandler
from typing import Optional

# --------------------------------------------------------------------------
# Caminhos do projeto
# --------------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ASSETS_DIR = os.path.join(BASE_DIR, "assets")
DATA_DIR = os.path.join(ASSETS_DIR, "data")
DATABASE_DIR = os.path.join(BASE_DIR, "database")
ICONS_DIR = os.path.join(BASE_DIR, "icons")
IMAGES_DIR = os.path.join(BASE_DIR, "images")
LOG_DIR = os.path.join(BASE_DIR, "logs")

DATABASE_PATH = os.path.join(DATABASE_DIR, "fightiq.db")
SEED_CSV_PATH = os.path.join(DATA_DIR, "fighters_seed.csv")

for _directory in (ASSETS_DIR, DATA_DIR, DATABASE_DIR, ICONS_DIR, IMAGES_DIR, LOG_DIR):
    os.makedirs(_directory, exist_ok=True)


# --------------------------------------------------------------------------
# Logging
# --------------------------------------------------------------------------
def get_logger(name: str) -> logging.Logger:
    """
    Retorna um logger configurado (arquivo rotativo + console).

    Todos os módulos do projeto devem obter seu logger através desta
    função, garantindo formatação e destino consistentes em todo o
    software:

        logger = get_logger(__name__)
        logger.info("mensagem")
    """
    logger = logging.getLogger(name)
    if logger.handlers:
        # Já configurado (evita handlers duplicados em recarregamentos).
        return logger

    logger.setLevel(logging.DEBUG)

    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    file_handler = RotatingFileHandler(
        os.path.join(LOG_DIR, "fightiq.log"),
        maxBytes=2_000_000,
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)

    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    return logger


# --------------------------------------------------------------------------
# Tema visual (cores e fontes) - usado pela interface CustomTkinter
# --------------------------------------------------------------------------
class Theme:
    """Paleta de cores centralizada (inspirada no visual dark do UFC Stats)."""

    BG_PRIMARY = "#0d0d0f"
    BG_SECONDARY = "#161619"
    BG_CARD = "#1e1e22"
    BG_SIDEBAR = "#111113"

    ACCENT = "#d20a0a"          # vermelho UFC
    ACCENT_HOVER = "#a80808"
    ACCENT_SOFT = "#3a1414"

    TEXT_PRIMARY = "#f5f5f7"
    TEXT_SECONDARY = "#9a9aa2"
    TEXT_MUTED = "#5c5c64"

    SUCCESS = "#2fbf71"
    WARNING = "#e6a326"
    ERROR = "#e6394a"
    INFO = "#3a86ff"
    NEUTRAL = "#8a8a92"  # discreto — empates e No Contest (não é alerta nem erro)

    BORDER = "#2a2a2e"

    FONT_FAMILY = "Segoe UI"
    FONT_FAMILY_BOLD = "Segoe UI Semibold"


# --------------------------------------------------------------------------
# Formatação
# --------------------------------------------------------------------------
def calculate_age(birth_date: Optional[date]) -> Optional[int]:
    """Calcula a idade atual a partir de uma data de nascimento real."""
    if birth_date is None:
        return None
    today = date.today()
    years = today.year - birth_date.year
    if (today.month, today.day) < (birth_date.month, birth_date.day):
        years -= 1
    return years


def parse_iso_date(value: Optional[str]) -> Optional[date]:
    """Converte string ISO (YYYY-MM-DD) em objeto date, tolerando None/vazio."""
    if not value:
        return None
    try:
        return datetime.strptime(value.strip(), "%Y-%m-%d").date()
    except (ValueError, AttributeError):
        return None


def cm_to_feet_inches(cm: Optional[float]) -> str:
    """Converte centímetros para o formato pés'polegadas" (ex.: 6'4"). """
    if cm is None:
        return "—"
    total_inches = cm / 2.54
    feet = int(total_inches // 12)
    inches = round(total_inches - feet * 12)
    if inches == 12:
        feet += 1
        inches = 0
    return f"{feet}'{inches}\""


def cm_to_meters_br(cm: Optional[float]) -> str:
    """Converte centímetros para metros no padrão brasileiro (ex.: 195 -> '1,95 m')."""
    if cm is None:
        return "—"
    meters = cm / 100
    return f"{meters:.2f} m".replace(".", ",")


def cm_display(cm: Optional[float]) -> str:
    """Formata centímetros como inteiro com sufixo (ex.: 195 -> '195 cm')."""
    if cm is None:
        return "—"
    return f"{cm:.0f} cm"


def format_record(wins: Optional[int], losses: Optional[int], draws: Optional[int],
                   no_contests: Optional[int] = 0) -> str:
    """Formata o cartel de um lutador no padrão V-D-E (com NC se houver)."""
    wins = wins or 0
    losses = losses or 0
    draws = draws or 0
    record = f"{wins}-{losses}-{draws}"
    if no_contests:
        record += f" ({no_contests} NC)"
    return record


def safe_percent(value: Optional[float]) -> str:
    """Formata um valor percentual, retornando placeholder se ausente."""
    if value is None:
        return "N/D"
    return f"{value:.0f}%"


def safe_number(value: Optional[float], suffix: str = "", decimals: int = 2) -> str:
    """Formata um número (ex.: golpes por minuto), retornando placeholder se ausente."""
    if value is None:
        return "N/D"
    return f"{value:.{decimals}f}{suffix}"


def truncate(text: str, length: int = 40) -> str:
    """Trunca texto longo para uso em cards/listas, preservando legibilidade."""
    if text is None:
        return ""
    return text if len(text) <= length else text[: length - 1].rstrip() + "…"
