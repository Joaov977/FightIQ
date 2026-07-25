"""
database.py
-----------
Camada de persistência do FightIQ. Toda a interação com SQLite passa
por aqui — nenhum outro módulo deve abrir uma conexão sqlite3 diretamente.

Responsabilidades:
    - Criar o schema (tabelas fighters, fighter_stats, favorites, history).
    - Popular ("seed") o banco a partir do CSV de dados reais em
      assets/data/fighters_seed.csv na primeira execução.
    - Aplicar a camada de curadoria manual (assets/data/manual_overrides.csv)
      por cima dos dados automáticos, campo a campo.
    - CRUD de favoritos e histórico de pesquisas.
    - Consultas de busca/listagem de lutadores.

Nenhum dado é gerado aqui: os únicos valores gravados nas tabelas de
lutadores/estatísticas vêm do CSV de seed (fonte pública verificada,
ver README.md), da camada de overrides manuais (curadoria humana
explícita, com proveniência registrada), ou de uma futura atualização
via api.py. As tabelas de favoritos/histórico armazenam apenas ações do
próprio usuário.

v1.2 — fighter_id passou a ser um slug estável (ex.: "jon_jones"),
derivado da URL de origem, em vez de um número sequencial atribuído por
ordem de coleta. Isso evita que favoritos, histórico e overrides
manuais apontem para o lutador errado se a ordem do scraping mudar
entre execuções (ex.: um lutador sai do ranking, os índices de todo
mundo abaixo dele deslizavam uma posição).
"""

from __future__ import annotations

import csv
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Iterator, List, Optional

from models import Fighter, FighterStats, FavoriteEntry, SearchHistoryEntry
from data_quality import sanitize_fighter_dict, describe_sanitization
from utils import DATA_DIR, DATABASE_PATH, SEED_CSV_PATH, get_logger, parse_iso_date

logger = get_logger(__name__)

OVERRIDES_CSV_PATH = str(Path(DATA_DIR) / "manual_overrides.csv")

# Colunas de fighters/fighter_stats que podem ser sobrescritas pela
# camada de curadoria manual. Mantido explícito (em vez de "qualquer
# coluna") para que o override nunca mexa em campos administrativos
# (fighter_id, source, last_updated, etc.) sem querer.
OVERRIDABLE_FIELDS = [
    "name", "nickname", "nationality", "weight_class",
    "height_cm", "reach_cm", "stance", "birth_date", "age_reported",
    "wins", "losses", "draws", "no_contests",
    "wins_ko", "wins_sub", "wins_dec",
    "ranking", "image_url",
    "slpm", "str_acc_pct", "sapm", "str_def_pct",
    "td_avg", "td_acc_pct", "td_def_pct", "sub_avg", "avg_fight_time",
]
_STATS_FIELDS = {"slpm", "str_acc_pct", "sapm", "str_def_pct",
                  "td_avg", "td_acc_pct", "td_def_pct", "sub_avg", "avg_fight_time"}


SCHEMA = """
CREATE TABLE IF NOT EXISTS fighters (
    fighter_id      TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    nickname        TEXT,
    nationality     TEXT,
    weight_class    TEXT,
    height_cm       REAL,
    reach_cm        REAL,
    stance          TEXT,
    birth_date      TEXT,
    age_reported    INTEGER,
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
    image_license   TEXT,
    image_attribution TEXT,
    image_source_url TEXT,
    source          TEXT,
    source_url      TEXT,
    last_updated    TEXT,
    manually_overridden_fields TEXT
);

CREATE TABLE IF NOT EXISTS fighter_stats (
    fighter_id      TEXT PRIMARY KEY REFERENCES fighters(fighter_id) ON DELETE CASCADE,
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
    fighter_id      TEXT NOT NULL REFERENCES fighters(fighter_id) ON DELETE CASCADE,
    name            TEXT NOT NULL,
    added_at        TEXT NOT NULL,
    UNIQUE(fighter_id)
);

CREATE TABLE IF NOT EXISTS search_history (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    query           TEXT NOT NULL,
    fighter_id      TEXT,
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

    IMPORTANTE (migração de schema): se você já tinha um banco criado
    antes da v1.2 (fighter_id como INTEGER), apague o arquivo
    database/fightiq.db antes de rodar — o schema mudou (fighter_id
    agora é TEXT/slug) e "CREATE TABLE IF NOT EXISTS" não migra tabelas
    existentes automaticamente.
    """

    def __init__(self, db_path: str = DATABASE_PATH, seed_csv: str = SEED_CSV_PATH,
                 overrides_csv: str = OVERRIDES_CSV_PATH) -> None:
        self.db_path = db_path
        self.seed_csv = seed_csv
        self.overrides_csv = overrides_csv

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
    # Colunas que podem ter sido adicionadas em versões mais novas do
    # projeto, mapeadas para seu tipo SQLite — usado por _migrate_schema()
    # para adicionar automaticamente em bancos já existentes.
    _MIGRATABLE_COLUMNS = {
        "age_reported": "INTEGER",
        "manually_overridden_fields": "TEXT",
        "image_license": "TEXT",
        "image_attribution": "TEXT",
        "image_source_url": "TEXT",
    }

    def _ensure_schema(self) -> None:
        """
        Garante que as tabelas existam, de forma idempotente (CREATE
        TABLE IF NOT EXISTS). Chamada por TODA operação pública que
        toca o banco (initialize, reseed, reapply_overrides) — não só
        por initialize() — porque qualquer uma dessas pode ser a
        primeira chamada feita numa instalação nova (ex.: rodar
        DatabaseManager().reseed() direto, sem um initialize() antes).

        Também roda uma migração leve (_migrate_schema) para que um
        banco criado por uma versão mais antiga do projeto ganhe
        automaticamente as colunas adicionadas depois — sem isso, abrir
        um banco antigo com uma versão nova do código quebra com
        "IndexError: No item with that key" na primeira coluna nova que
        a interface tentar ler.
        """
        with self._connect() as conn:
            conn.executescript(SCHEMA)
        self._migrate_schema()

    def _migrate_schema(self) -> None:
        """
        Adiciona, via ALTER TABLE ... ADD COLUMN, qualquer coluna de
        _MIGRATABLE_COLUMNS que ainda não exista na tabela fighters de
        um banco já criado. Cobre apenas adições de coluna (o caso
        comum ao evoluir o projeto); mudanças de TIPO de uma coluna já
        existente (ex.: fighter_id INTEGER -> TEXT, feita na v1.2) não
        são cobertas por este mecanismo — SQLite não migra tipo de
        chave primária de forma trivial, então essa mudança específica
        continua exigindo apagar o banco antigo (documentado no README).
        """
        with self._connect() as conn:
            existing_cols = {row["name"] for row in conn.execute("PRAGMA table_info(fighters)")}
            for column, col_type in self._MIGRATABLE_COLUMNS.items():
                if column not in existing_cols:
                    conn.execute(f"ALTER TABLE fighters ADD COLUMN {column} {col_type}")
                    logger.info("Migração de schema: coluna '%s' adicionada à tabela fighters.", column)

    def initialize(self) -> None:
        """
        Cria o schema (se necessário), popula com o CSV na primeira
        execução, e SEMPRE reaplica a camada de overrides manuais (é
        idempotente e barata) — assim, editar
        assets/data/manual_overrides.csv e só reabrir o app já é
        suficiente para a correção entrar em vigor, sem precisar rodar
        reseed() manualmente.

        Este é o comando canônico para inicializar o banco do zero:
            from database import DatabaseManager
            DatabaseManager().initialize()
        """
        self._ensure_schema()

        if not self._is_seeded():
            self._seed_from_csv()
        else:
            logger.info("Banco de dados já populado; seed automático ignorado.")

        self._apply_manual_overrides()

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
                fighter_id = _require_fighter_id(row)
                if fighter_id is None:
                    logger.warning("Linha sem fighter_id/slug válido ignorada: %s", row.get("name"))
                    continue
                conn.execute(
                    """
                    INSERT OR REPLACE INTO fighters (
                        fighter_id, name, nickname, nationality, weight_class,
                        height_cm, reach_cm, stance, birth_date, age_reported,
                        wins, losses, draws, no_contests,
                        wins_ko, wins_sub, wins_dec,
                        ranking, image_url, local_image_path,
                        source, source_url, last_updated
                    ) VALUES (?,?,?,?,?, ?,?,?,?,?, ?,?,?,?, ?,?,?, ?,?,?, ?,?,?)
                    """,
                    (
                        fighter_id,
                        row["name"].strip(),
                        row.get("nickname") or None,
                        row.get("nationality") or None,
                        row.get("weight_class") or None,
                        _to_float(row.get("height_cm")),
                        _to_float(row.get("reach_cm")),
                        row.get("stance") or None,
                        row.get("birth_date") or None,
                        _to_int(row.get("age_reported")),
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
                        fighter_id,
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

    def _apply_manual_overrides(self) -> None:
        """
        Aplica assets/data/manual_overrides.csv por cima dos dados já
        carregados, campo a campo — só os campos preenchidos no arquivo
        de overrides são sobrescritos; o resto do registro continua
        vindo do scraper. Roda sempre por último (depois do seed), tanto
        na primeira inicialização quanto em cada reseed(), para que um
        override nunca seja perdido quando os dados automáticos forem
        atualizados.

        Arquivo é opcional: se não existir, esta função não faz nada.
        """
        try:
            with open(self.overrides_csv, newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                override_rows = list(reader)
        except FileNotFoundError:
            logger.info("Nenhum arquivo de overrides manuais encontrado em %s; pulando.", self.overrides_csv)
            return

        applied_count = 0
        with self._connect() as conn:
            for row in override_rows:
                fighter_id = (row.get("fighter_id") or "").strip()
                if not fighter_id:
                    continue

                exists = conn.execute(
                    "SELECT 1 FROM fighters WHERE fighter_id = ?", (fighter_id,)
                ).fetchone()
                if not exists:
                    logger.warning(
                        "manual_overrides.csv referencia fighter_id '%s' que não existe no banco "
                        "(rode o scraper antes, ou confira o slug) — ignorado.", fighter_id,
                    )
                    continue

                filled_fields = {
                    field: row[field].strip()
                    for field in OVERRIDABLE_FIELDS
                    if row.get(field) is not None and row[field].strip() != ""
                }
                if not filled_fields:
                    continue

                sanitized = sanitize_fighter_dict({**filled_fields, "fighter_id": fighter_id})

                fighters_updates = {k: v for k, v in sanitized.items()
                                     if k in filled_fields and k not in _STATS_FIELDS}
                stats_updates = {k: v for k, v in sanitized.items()
                                  if k in filled_fields and k in _STATS_FIELDS}

                if fighters_updates:
                    set_clause = ", ".join(f"{k} = ?" for k in fighters_updates)
                    conn.execute(
                        f"UPDATE fighters SET {set_clause}, manually_overridden_fields = ? WHERE fighter_id = ?",
                        (*fighters_updates.values(), ", ".join(sorted(filled_fields.keys())), fighter_id),
                    )
                if stats_updates:
                    set_clause = ", ".join(f"{k} = ?" for k in stats_updates)
                    conn.execute(
                        f"UPDATE fighter_stats SET {set_clause} WHERE fighter_id = ?",
                        (*stats_updates.values(), fighter_id),
                    )

                applied_count += 1
                logger.info("Override manual aplicado a '%s': %s", fighter_id, ", ".join(filled_fields.keys()))

        if applied_count:
            print(f"✏️  {applied_count} lutador(es) com correções manuais aplicadas (manual_overrides.csv)")

    def reseed(self) -> None:
        """
        Força uma nova importação do CSV + reaplica os overrides
        manuais. Funciona também em uma instalação limpa (sem banco
        ainda criado) — garante o schema antes de qualquer outra coisa,
        então é seguro chamar isso como primeiro comando depois de
        rodar o scraper:

            python -c "from database import DatabaseManager; DatabaseManager().reseed()"
        """
        self._ensure_schema()
        with self._connect() as conn:
            conn.execute("DELETE FROM meta WHERE key = 'seeded'")
        self._seed_from_csv()
        self._apply_manual_overrides()

    def reapply_overrides(self) -> None:
        """Reaplica só a camada de overrides manuais, sem reimportar o CSV inteiro."""
        self._ensure_schema()
        self._apply_manual_overrides()

    def set_fighter_photo(self, fighter_id: str, local_image_path: str, image_license: str,
                           image_attribution: str, image_source_url: str) -> None:
        """
        Grava a foto de um lutador coletada via scripts/fetch_fighter_photos.py
        — sempre com licença e atribuição, nunca uma imagem "solta".
        """
        with self._connect() as conn:
            exists = conn.execute("SELECT 1 FROM fighters WHERE fighter_id = ?", (fighter_id,)).fetchone()
            if not exists:
                logger.warning("set_fighter_photo: fighter_id '%s' não existe no banco.", fighter_id)
                return
            conn.execute(
                """
                UPDATE fighters
                SET local_image_path = ?, image_license = ?, image_attribution = ?, image_source_url = ?
                WHERE fighter_id = ?
                """,
                (local_image_path, image_license, image_attribution, image_source_url, fighter_id),
            )
        logger.info("Foto salva para '%s' (%s, %s)", fighter_id, image_license, image_attribution)

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

    def list_weight_classes(self) -> List[str]:
        """Categorias de peso distintas presentes no banco, ordenadas alfabeticamente."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT DISTINCT weight_class FROM fighters WHERE weight_class IS NOT NULL ORDER BY weight_class"
            ).fetchall()
        return [r["weight_class"] for r in rows]

    def list_nationalities(self) -> List[str]:
        """Nacionalidades distintas presentes no banco, ordenadas alfabeticamente."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT DISTINCT nationality FROM fighters WHERE nationality IS NOT NULL ORDER BY nationality"
            ).fetchall()
        return [r["nationality"] for r in rows]

    def filter_fighters(self, query: Optional[str] = None, weight_class: Optional[str] = None,
                         nationality: Optional[str] = None) -> List[Fighter]:
        """
        Busca combinável: nome/apelido (parcial) E/OU categoria de peso
        E/OU nacionalidade — todos os filtros informados se combinam
        com AND. Qualquer filtro deixado em None/"" é ignorado.
        """
        clauses, params = [], []
        if query:
            clauses.append("(name LIKE ? COLLATE NOCASE OR nickname LIKE ? COLLATE NOCASE)")
            like = f"%{query.strip()}%"
            params.extend([like, like])
        if weight_class:
            clauses.append("weight_class = ?")
            params.append(weight_class)
        if nationality:
            clauses.append("nationality = ?")
            params.append(nationality)

        sql = "SELECT * FROM fighters"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY name ASC"

        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [_row_to_fighter(r) for r in rows]

    def get_fighter(self, fighter_id: str) -> Optional[Fighter]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM fighters WHERE fighter_id = ?", (fighter_id,)
            ).fetchone()
        return _row_to_fighter(row) if row else None

    def get_fighter_stats(self, fighter_id: str) -> FighterStats:
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
    def add_favorite(self, fighter_id: str, name: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO favorites (fighter_id, name, added_at) VALUES (?,?,?)",
                (fighter_id, name, datetime.now().isoformat(timespec="seconds")),
            )
        logger.info("Favorito adicionado: %s (id=%s)", name, fighter_id)

    def remove_favorite(self, fighter_id: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM favorites WHERE fighter_id = ?", (fighter_id,))
        logger.info("Favorito removido: id=%s", fighter_id)

    def is_favorite(self, fighter_id: str) -> bool:
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
    def log_search(self, query: str, fighter_id: Optional[str]) -> None:
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


def _require_fighter_id(row: dict) -> Optional[str]:
    """Valida que a linha tem um fighter_id/slug não vazio (string, não índice numérico)."""
    fighter_id = str(row.get("fighter_id") or "").strip()
    return fighter_id or None


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
        age_reported=row["age_reported"],
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
        image_license=row["image_license"],
        image_attribution=row["image_attribution"],
        image_source_url=row["image_source_url"],
        source=row["source"],
        source_url=row["source_url"],
        last_updated=row["last_updated"],
        manually_overridden_fields=row["manually_overridden_fields"],
    )
