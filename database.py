"""
database.py
-----------
Camada de persistência do FightIQ. Toda a interação com SQLite passa
por aqui — nenhum outro módulo deve abrir uma conexão sqlite3 diretamente.

Responsabilidades:
    - Criar o schema (tabelas fighters, fighter_stats, favorites, history).
    - Popular ("seed") o banco a partir do CSV de dados reais em
      assets/data/fighters_seed.csv na primeira execução.
    - CRUD de favoritos e histórico de pesquisas.
    - Consultas de busca/listagem de lutadores.

Nenhum dado é gerado aqui: os únicos valores gravados nas tabelas de
lutadores/estatísticas vêm do CSV de seed (fonte pública verificada,
ver README.md) ou de uma futura atualização feita via api.py. As tabelas
de favoritos/histórico armazenam apenas ações do próprio usuário.
"""

from __future__ import annotations

import csv
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from typing import Iterator, List, Optional

from models import Fighter, FighterStats, FavoriteEntry, SearchHistoryEntry
from data_quality import sanitize_fighter_dict, describe_sanitization
from utils import DATABASE_PATH, SEED_CSV_PATH, get_logger, parse_iso_date

logger = get_logger(__name__)


SCHEMA = """
CREATE TABLE IF NOT EXISTS fighters (
    fighter_id      INTEGER PRIMARY KEY,
    name            TEXT NOT NULL,
    nickname        TEXT,
    nationality     TEXT,
    weight_class    TEXT,
    height_cm       REAL,
    reach_cm        REAL,
    stance          TEXT,
    birth_date      TEXT,
    wins            INTEGER DEFAULT 0,
    losses          INTEGER DEFAULT 0,
    draws           INTEGER DEFAULT 0,
    no_contests     INTEGER DEFAULT 0,
    wins_ko         INTEGER,
    wins_sub        INTEGER,
    wins_dec        INTEGER,
    ranking         TEXT,
    image_url       TEXT,
    local_image_path TEXT,
    source          TEXT,
    source_url      TEXT,
    last_updated    TEXT
);

CREATE TABLE IF NOT EXISTS fighter_stats (
    fighter_id      INTEGER PRIMARY KEY REFERENCES fighters(fighter_id) ON DELETE CASCADE,
    slpm            REAL,
    str_acc_pct     REAL,
    sapm            REAL,
    str_def_pct     REAL,
    td_avg          REAL,
    td_acc_pct      REAL,
    td_def_pct      REAL,
    sub_avg         REAL,
    avg_fight_time  TEXT
);

CREATE TABLE IF NOT EXISTS favorites (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    fighter_id      INTEGER NOT NULL REFERENCES fighters(fighter_id) ON DELETE CASCADE,
    name            TEXT NOT NULL,
    added_at        TEXT NOT NULL,
    UNIQUE(fighter_id)
);

CREATE TABLE IF NOT EXISTS search_history (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    query           TEXT NOT NULL,
    fighter_id      INTEGER,
    searched_at     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS meta (
    key             TEXT PRIMARY KEY,
    value           TEXT
);
"""


class DatabaseManager:
    """
    Gerencia a conexão e todas as operações com o banco SQLite do FightIQ.

    Uso típico:
        db = DatabaseManager()
        db.initialize()
        fighters = db.search_fighters("jones")
    """

    def __init__(self, db_path: str = DATABASE_PATH, seed_csv: str = SEED_CSV_PATH) -> None:
        self.db_path = db_path
        self.seed_csv = seed_csv

    # ------------------------------------------------------------------
    # Conexão
    # ------------------------------------------------------------------
    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            logger.exception("Erro em operação de banco de dados; rollback aplicado.")
            raise
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Inicialização / seed
    # ------------------------------------------------------------------
    def initialize(self) -> None:
        """Cria o schema (se necessário) e popula com o CSV na primeira execução."""
        with self._connect() as conn:
            conn.executescript(SCHEMA)

        if not self._is_seeded():
            self._seed_from_csv()
        else:
            logger.info("Banco de dados já populado; seed ignorado.")

    def _is_seeded(self) -> bool:
        with self._connect() as conn:
            cur = conn.execute("SELECT value FROM meta WHERE key = 'seeded'")
            row = cur.fetchone()
            return row is not None and row["value"] == "1"

    def _seed_from_csv(self) -> None:
        """
        Popula fighters/fighter_stats a partir do CSV real em
        assets/data/fighters_seed.csv. Ver README.md para a origem de
        cada campo. Esta função é idempotente e segura para rodar de
        novo caso o CSV seja atualizado (usa INSERT OR REPLACE).
        """
        try:
            with open(self.seed_csv, newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                rows = list(reader)
        except FileNotFoundError:
            logger.warning("CSV de seed não encontrado em %s; banco iniciará vazio.", self.seed_csv)
            return

        # Segunda camada de defesa: mesmo que o CSV tenha sido editado à
        # mão, gerado por outra fonte, ou o scraper tenha uma falha não
        # prevista, cada linha passa pela validação de sanidade antes de
        # entrar no banco (idade implausível, altura fora da faixa
        # humana, percentuais >100%, etc. viram None em vez de serem
        # gravados como estão).
        sanitized_rows = []
        for row in rows:
            clean_row = sanitize_fighter_dict(row)
            descriptions = describe_sanitization(row, clean_row)
            if descriptions:
                logger.warning(
                    "Validação de sanidade ajustou campo(s) de '%s': %s",
                    row.get("name", "?"), "; ".join(descriptions),
                )
            sanitized_rows.append(clean_row)
        rows = sanitized_rows

        with self._connect() as conn:
            for row in rows:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO fighters (
                        fighter_id, name, nickname, nationality, weight_class,
                        height_cm, reach_cm, stance, birth_date,
                        wins, losses, draws, no_contests,
                        wins_ko, wins_sub, wins_dec,
                        ranking, image_url, local_image_path,
                        source, source_url, last_updated
                    ) VALUES (?,?,?,?,?, ?,?,?,?, ?,?,?,?, ?,?,?, ?,?,?, ?,?,?)
                    """,
                    (
                        int(row["fighter_id"]),
                        row["name"].strip(),
                        row.get("nickname") or None,
                        row.get("nationality") or None,
                        row.get("weight_class") or None,
                        _to_float(row.get("height_cm")),
                        _to_float(row.get("reach_cm")),
                        row.get("stance") or None,
                        row.get("birth_date") or None,
                        _to_int(row.get("wins"), 0),
                        _to_int(row.get("losses"), 0),
                        _to_int(row.get("draws"), 0),
                        _to_int(row.get("no_contests"), 0),
                        _to_int(row.get("wins_ko")),
                        _to_int(row.get("wins_sub")),
                        _to_int(row.get("wins_dec")),
                        row.get("ranking") or None,
                        row.get("image_url") or None,
                        None,
                        row.get("source") or None,
                        row.get("source_url") or None,
                        row.get("last_updated") or None,
                    ),
                )
                conn.execute(
                    """
                    INSERT OR REPLACE INTO fighter_stats (
                        fighter_id, slpm, str_acc_pct, sapm, str_def_pct,
                        td_avg, td_acc_pct, td_def_pct, sub_avg, avg_fight_time
                    ) VALUES (?,?,?,?,?, ?,?,?,?,?)
                    """,
                    (
                        int(row["fighter_id"]),
                        _to_float(row.get("slpm")),
                        _to_float(row.get("str_acc_pct")),
                        _to_float(row.get("sapm")),
                        _to_float(row.get("str_def_pct")),
                        _to_float(row.get("td_avg")),
                        _to_float(row.get("td_acc_pct")),
                        _to_float(row.get("td_def_pct")),
                        _to_float(row.get("sub_avg")),
                        row.get("avg_fight_time") or None,
                    ),
                )
            conn.execute(
                "INSERT OR REPLACE INTO meta (key, value) VALUES ('seeded', '1')"
            )
        logger.info("Banco populado com %d lutadores a partir de %s", len(rows), self.seed_csv)

    def reseed(self) -> None:
        """Força uma nova importação do CSV (útil após atualizar os dados)."""
        with self._connect() as conn:
            conn.execute("DELETE FROM meta WHERE key = 'seeded'")
        self._seed_from_csv()

    # ------------------------------------------------------------------
    # Consultas de lutadores
    # ------------------------------------------------------------------
    def search_fighters(self, query: str) -> List[Fighter]:
        """Busca lutadores por nome ou apelido (case-insensitive, parcial)."""
        like = f"%{query.strip()}%"
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM fighters
                WHERE name LIKE ? COLLATE NOCASE OR nickname LIKE ? COLLATE NOCASE
                ORDER BY name ASC
                """,
                (like, like),
            ).fetchall()
        return [_row_to_fighter(r) for r in rows]

    def list_all_fighters(self) -> List[Fighter]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM fighters ORDER BY name ASC").fetchall()
        return [_row_to_fighter(r) for r in rows]

    def get_fighter(self, fighter_id: int) -> Optional[Fighter]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM fighters WHERE fighter_id = ?", (fighter_id,)
            ).fetchone()
        return _row_to_fighter(row) if row else None

    def get_fighter_stats(self, fighter_id: int) -> FighterStats:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM fighter_stats WHERE fighter_id = ?", (fighter_id,)
            ).fetchone()
        if row is None:
            return FighterStats(fighter_id=fighter_id)
        return FighterStats(
            fighter_id=row["fighter_id"],
            slpm=row["slpm"],
            str_acc_pct=row["str_acc_pct"],
            sapm=row["sapm"],
            str_def_pct=row["str_def_pct"],
            td_avg=row["td_avg"],
            td_acc_pct=row["td_acc_pct"],
            td_def_pct=row["td_def_pct"],
            sub_avg=row["sub_avg"],
            avg_fight_time=row["avg_fight_time"],
        )

    # ------------------------------------------------------------------
    # Favoritos
    # ------------------------------------------------------------------
    def add_favorite(self, fighter_id: int, name: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO favorites (fighter_id, name, added_at) VALUES (?,?,?)",
                (fighter_id, name, datetime.now().isoformat(timespec="seconds")),
            )
        logger.info("Favorito adicionado: %s (id=%s)", name, fighter_id)

    def remove_favorite(self, fighter_id: int) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM favorites WHERE fighter_id = ?", (fighter_id,))
        logger.info("Favorito removido: id=%s", fighter_id)

    def is_favorite(self, fighter_id: int) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM favorites WHERE fighter_id = ?", (fighter_id,)
            ).fetchone()
        return row is not None

    def list_favorites(self) -> List[FavoriteEntry]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM favorites ORDER BY added_at DESC"
            ).fetchall()
        return [
            FavoriteEntry(
                fighter_id=r["fighter_id"],
                name=r["name"],
                added_at=datetime.fromisoformat(r["added_at"]),
            )
            for r in rows
        ]

    # ------------------------------------------------------------------
    # Histórico de pesquisas
    # ------------------------------------------------------------------
    def log_search(self, query: str, fighter_id: Optional[int]) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO search_history (query, fighter_id, searched_at) VALUES (?,?,?)",
                (query, fighter_id, datetime.now().isoformat(timespec="seconds")),
            )

    def list_history(self, limit: int = 50) -> List[SearchHistoryEntry]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM search_history ORDER BY searched_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [
            SearchHistoryEntry(
                query=r["query"],
                fighter_id=r["fighter_id"],
                searched_at=datetime.fromisoformat(r["searched_at"]),
            )
            for r in rows
        ]

    def clear_history(self) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM search_history")
        logger.info("Histórico de pesquisas limpo.")


# --------------------------------------------------------------------------
# Helpers privados
# --------------------------------------------------------------------------
def _to_float(value) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _to_int(value, default: Optional[int] = None) -> Optional[int]:
    if value is None or value == "":
        return default
    try:
        return int(float(value))
    except ValueError:
        return default


def _row_to_fighter(row: sqlite3.Row) -> Fighter:
    return Fighter(
        fighter_id=row["fighter_id"],
        name=row["name"],
        nickname=row["nickname"],
        nationality=row["nationality"],
        weight_class=row["weight_class"],
        height_cm=row["height_cm"],
        reach_cm=row["reach_cm"],
        stance=row["stance"],
        birth_date=parse_iso_date(row["birth_date"]),
        wins=row["wins"] or 0,
        losses=row["losses"] or 0,
        draws=row["draws"] or 0,
        no_contests=row["no_contests"] or 0,
        wins_ko=row["wins_ko"],
        wins_sub=row["wins_sub"],
        wins_dec=row["wins_dec"],
        ranking=row["ranking"],
        image_url=row["image_url"],
        local_image_path=row["local_image_path"],
        source=row["source"],
        source_url=row["source_url"],
        last_updated=row["last_updated"],
    )
