"""
tests/test_database.py
------------------------
Testes de integração da camada de banco: ID estável por slug e a
camada de overrides manuais (aplicação parcial, precedência,
persistência entre reaberturas do app).

Rode com:
    python -m unittest tests.test_database -v
"""

import csv
import os
import tempfile
import unittest
from pathlib import Path

from database import DatabaseManager, OVERRIDABLE_FIELDS

CSV_HEADER = [
    "fighter_id", "name", "nickname", "nationality", "weight_class",
    "height_cm", "reach_cm", "stance", "birth_date", "age_reported",
    "wins", "losses", "draws", "no_contests", "wins_ko", "wins_sub", "wins_dec",
    "slpm", "str_acc_pct", "sapm", "str_def_pct", "td_avg", "td_acc_pct",
    "td_def_pct", "sub_avg", "avg_fight_time", "image_url", "ranking",
    "source", "source_url", "last_updated",
]


def _write_seed_csv(path: Path, rows: list[dict]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_HEADER)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in CSV_HEADER})


def _write_overrides_csv(path: Path, rows: list[dict]) -> None:
    fieldnames = ["fighter_id"] + OVERRIDABLE_FIELDS + ["note"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in fieldnames})


class TestStableSlugId(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.db_path = self.tmp / "test.db"
        self.seed_csv = self.tmp / "seed.csv"
        self.overrides_csv = self.tmp / "overrides.csv"  # não existe -> sem overrides

    def tearDown(self):
        for f in (self.db_path, self.seed_csv, self.overrides_csv):
            if f.exists():
                os.remove(f)

    def test_fighter_id_is_string_slug_not_int(self):
        _write_seed_csv(self.seed_csv, [
            {"fighter_id": "miesha_tate", "name": "Miesha Tate", "wins": 20, "losses": 10, "draws": 0},
        ])
        db = DatabaseManager(db_path=str(self.db_path), seed_csv=str(self.seed_csv),
                              overrides_csv=str(self.overrides_csv))
        db.initialize()
        fighter = db.get_fighter("miesha_tate")
        self.assertIsInstance(fighter.fighter_id, str)
        self.assertEqual(fighter.fighter_id, "miesha_tate")

    def test_lookup_by_slug_survives_reorder_in_csv(self):
        """
        Simula o cenário que o ID sequencial antigo quebrava: a ordem
        dos lutadores no CSV muda entre duas coletas, mas como o ID
        agora é o slug (não a posição), a busca continua correta.
        """
        _write_seed_csv(self.seed_csv, [
            {"fighter_id": "fighter_a", "name": "Fighter A", "wins": 1, "losses": 0, "draws": 0},
            {"fighter_id": "fighter_b", "name": "Fighter B", "wins": 2, "losses": 0, "draws": 0},
        ])
        db = DatabaseManager(db_path=str(self.db_path), seed_csv=str(self.seed_csv),
                              overrides_csv=str(self.overrides_csv))
        db.initialize()
        self.assertEqual(db.get_fighter("fighter_a").name, "Fighter A")
        self.assertEqual(db.get_fighter("fighter_b").name, "Fighter B")

        # Reordena o CSV (como aconteceria se o ranking mudasse) e reseeda
        os.remove(self.db_path)
        _write_seed_csv(self.seed_csv, [
            {"fighter_id": "fighter_b", "name": "Fighter B", "wins": 2, "losses": 0, "draws": 0},
            {"fighter_id": "fighter_a", "name": "Fighter A", "wins": 1, "losses": 0, "draws": 0},
        ])
        db2 = DatabaseManager(db_path=str(self.db_path), seed_csv=str(self.seed_csv),
                               overrides_csv=str(self.overrides_csv))
        db2.initialize()
        # Mesmo com a ordem trocada no CSV, cada slug continua apontando pro lutador certo
        self.assertEqual(db2.get_fighter("fighter_a").name, "Fighter A")
        self.assertEqual(db2.get_fighter("fighter_b").name, "Fighter B")


class TestSchemaMigration(unittest.TestCase):
    """
    Regressão: abrir um banco criado por uma versão mais antiga do
    projeto (sem as colunas de idade direta/overrides/fotos) não pode
    quebrar com 'IndexError: No item with that key'.
    """

    OLD_SCHEMA = """
    CREATE TABLE fighters (
        fighter_id      TEXT PRIMARY KEY,
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
    CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
    """

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.db_path = self.tmp / "old_schema.db"

        import sqlite3
        conn = sqlite3.connect(self.db_path)
        conn.executescript(self.OLD_SCHEMA)
        conn.execute(
            "INSERT INTO fighters (fighter_id, name, wins, losses, draws) "
            "VALUES ('jon_jones', 'Jon Jones', 28, 1, 0)"
        )
        conn.execute("INSERT INTO meta (key, value) VALUES ('seeded', '1')")
        conn.commit()
        conn.close()

    def tearDown(self):
        if self.db_path.exists():
            os.remove(self.db_path)

    def test_opening_old_database_does_not_raise_indexerror(self):
        db = DatabaseManager(db_path=str(self.db_path))
        db.initialize()  # não deve levantar IndexError
        fighter = db.get_fighter("jon_jones")
        self.assertEqual(fighter.name, "Jon Jones")
        self.assertIsNone(fighter.image_license)  # coluna nova, migrada, sem dado ainda
        self.assertIsNone(fighter.age_reported)

    def test_new_columns_are_usable_after_migration(self):
        db = DatabaseManager(db_path=str(self.db_path))
        db.initialize()
        db.set_fighter_photo("jon_jones", local_image_path="x.jpg", image_license="CC0",
                              image_attribution="A", image_source_url="https://example.com")
        fighter = db.get_fighter("jon_jones")
        self.assertEqual(fighter.image_license, "CC0")


class TestFreshInstallInitialization(unittest.TestCase):
    """Regressão: reseed() e initialize() precisam funcionar numa instalação limpa (sem .db ainda)."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.db_path = self.tmp / "does_not_exist_yet.db"
        self.seed_csv = self.tmp / "seed.csv"
        self.overrides_csv = self.tmp / "no_overrides.csv"
        _write_seed_csv(self.seed_csv, [
            {"fighter_id": "jon_jones", "name": "Jon Jones", "wins": 28, "losses": 1, "draws": 0},
        ])

    def tearDown(self):
        if self.db_path.exists():
            os.remove(self.db_path)

    def test_reseed_works_without_prior_initialize_or_existing_db_file(self):
        """
        Reprodução exata do bug reportado: chamar reseed() como primeiro
        comando, sem initialize() antes e sem o arquivo .db existir,
        não deve levantar 'no such table: meta'.
        """
        self.assertFalse(self.db_path.exists())
        db = DatabaseManager(db_path=str(self.db_path), seed_csv=str(self.seed_csv),
                              overrides_csv=str(self.overrides_csv))
        db.reseed()  # não deve levantar sqlite3.OperationalError
        fighter = db.get_fighter("jon_jones")
        self.assertIsNotNone(fighter)
        self.assertEqual(fighter.name, "Jon Jones")

    def test_reapply_overrides_also_works_without_prior_initialize(self):
        db = DatabaseManager(db_path=str(self.db_path), seed_csv=str(self.seed_csv),
                              overrides_csv=str(self.overrides_csv))
        db.reapply_overrides()  # não deve levantar exceção mesmo sem schema/dados ainda


class TestManualOverrides(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.db_path = self.tmp / "test.db"
        self.seed_csv = self.tmp / "seed.csv"
        self.overrides_csv = self.tmp / "overrides.csv"
        _write_seed_csv(self.seed_csv, [
            {"fighter_id": "islam_makhachev", "name": "Islam Makhachev", "height_cm": 178,
             "reach_cm": 179, "wins": 28, "losses": 1, "draws": 0},
        ])

    def tearDown(self):
        for f in (self.db_path, self.seed_csv, self.overrides_csv):
            if f.exists():
                os.remove(f)

    def test_partial_override_changes_only_specified_field(self):
        _write_overrides_csv(self.overrides_csv, [
            {"fighter_id": "islam_makhachev", "reach_cm": "183", "note": "conferido manualmente"},
        ])
        db = DatabaseManager(db_path=str(self.db_path), seed_csv=str(self.seed_csv),
                              overrides_csv=str(self.overrides_csv))
        db.initialize()
        fighter = db.get_fighter("islam_makhachev")

        self.assertEqual(fighter.reach_cm, 183.0)          # sobrescrito
        self.assertEqual(fighter.name, "Islam Makhachev")   # intacto
        self.assertEqual(fighter.height_cm, 178.0)           # intacto
        self.assertEqual(fighter.manually_overridden_fields, "reach_cm")

    def test_override_for_unknown_fighter_id_is_ignored_safely(self):
        _write_overrides_csv(self.overrides_csv, [
            {"fighter_id": "lutador_que_nao_existe", "reach_cm": "200"},
        ])
        db = DatabaseManager(db_path=str(self.db_path), seed_csv=str(self.seed_csv),
                              overrides_csv=str(self.overrides_csv))
        # Não deve levantar exceção
        db.initialize()
        self.assertIsNone(db.get_fighter("lutador_que_nao_existe"))

    def test_overrides_persist_across_reopen_without_explicit_reseed(self):
        """
        Regressão: overrides devem ser reaplicados toda vez que o app
        abre (initialize()), não só na primeira vez que o banco é criado.
        """
        _write_overrides_csv(self.overrides_csv, [
            {"fighter_id": "islam_makhachev", "reach_cm": "183"},
        ])
        db1 = DatabaseManager(db_path=str(self.db_path), seed_csv=str(self.seed_csv),
                               overrides_csv=str(self.overrides_csv))
        db1.initialize()
        self.assertEqual(db1.get_fighter("islam_makhachev").reach_cm, 183.0)

        # "Reabre o app" com uma nova instância, banco já existe (não deveria reseedar)
        db2 = DatabaseManager(db_path=str(self.db_path), seed_csv=str(self.seed_csv),
                               overrides_csv=str(self.overrides_csv))
        db2.initialize()
        self.assertEqual(db2.get_fighter("islam_makhachev").reach_cm, 183.0)

    def test_no_overrides_file_does_not_break_initialization(self):
        missing_path = self.tmp / "does_not_exist.csv"
        db = DatabaseManager(db_path=str(self.db_path), seed_csv=str(self.seed_csv),
                              overrides_csv=str(missing_path))
        db.initialize()  # não deve levantar exceção
        fighter = db.get_fighter("islam_makhachev")
        self.assertIsNone(fighter.manually_overridden_fields)


class TestAgeReportedInDatabase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.db_path = self.tmp / "test.db"
        self.seed_csv = self.tmp / "seed.csv"
        self.overrides_csv = self.tmp / "no_overrides.csv"

    def tearDown(self):
        for f in (self.db_path, self.seed_csv):
            if f.exists():
                os.remove(f)

    def test_age_falls_back_to_age_reported_when_no_birth_date(self):
        _write_seed_csv(self.seed_csv, [
            {"fighter_id": "miesha_tate", "name": "Miesha Tate", "age_reported": 39,
             "wins": 20, "losses": 10, "draws": 0},
        ])
        db = DatabaseManager(db_path=str(self.db_path), seed_csv=str(self.seed_csv),
                              overrides_csv=str(self.overrides_csv))
        db.initialize()
        fighter = db.get_fighter("miesha_tate")
        self.assertEqual(fighter.age, 39)
        self.assertTrue(fighter.age_is_estimated)

    def test_birth_date_takes_priority_over_age_reported_when_both_present(self):
        _write_seed_csv(self.seed_csv, [
            {"fighter_id": "jon_jones", "name": "Jon Jones", "birth_date": "1987-07-19",
             "age_reported": 99,  # propositalmente errado, pra confirmar que NÃO é usado
             "wins": 28, "losses": 1, "draws": 0},
        ])
        db = DatabaseManager(db_path=str(self.db_path), seed_csv=str(self.seed_csv),
                              overrides_csv=str(self.overrides_csv))
        db.initialize()
        fighter = db.get_fighter("jon_jones")
        self.assertNotEqual(fighter.age, 99)
        self.assertFalse(fighter.age_is_estimated)


class TestFiltersAndPhotos(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.db_path = self.tmp / "test.db"
        self.seed_csv = self.tmp / "seed.csv"
        self.overrides_csv = self.tmp / "no_overrides.csv"
        _write_seed_csv(self.seed_csv, [
            {"fighter_id": "jon_jones", "name": "Jon Jones", "weight_class": "Heavyweight",
             "nationality": "United States", "wins": 28, "losses": 1, "draws": 0},
            {"fighter_id": "weili_zhang", "name": "Zhang Weili", "weight_class": "Women's Strawweight",
             "nationality": "China", "wins": 26, "losses": 4, "draws": 0},
        ])

    def tearDown(self):
        for f in (self.db_path, self.seed_csv, self.overrides_csv):
            if f.exists():
                os.remove(f)

    def _db(self):
        db = DatabaseManager(db_path=str(self.db_path), seed_csv=str(self.seed_csv),
                              overrides_csv=str(self.overrides_csv))
        db.initialize()
        return db

    def test_list_weight_classes_and_nationalities(self):
        db = self._db()
        self.assertIn("Heavyweight", db.list_weight_classes())
        self.assertIn("China", db.list_nationalities())

    def test_filter_by_nationality_only(self):
        db = self._db()
        results = db.filter_fighters(nationality="China")
        self.assertEqual([f.name for f in results], ["Zhang Weili"])

    def test_filter_combines_query_and_weight_class_with_and(self):
        db = self._db()
        # nome bate, categoria não -> não deve retornar nada
        results = db.filter_fighters(query="jon", weight_class="Women's Strawweight")
        self.assertEqual(results, [])
        # nome e categoria batem -> retorna
        results2 = db.filter_fighters(query="jon", weight_class="Heavyweight")
        self.assertEqual([f.name for f in results2], ["Jon Jones"])

    def test_set_fighter_photo_persists_license_and_attribution(self):
        db = self._db()
        db.set_fighter_photo("jon_jones", local_image_path="images/fighters/jon_jones.jpg",
                              image_license="CC-BY-SA 4.0", image_attribution="Some Photographer",
                              image_source_url="https://commons.wikimedia.org/wiki/File:x.jpg")
        fighter = db.get_fighter("jon_jones")
        self.assertEqual(fighter.image_license, "CC-BY-SA 4.0")
        self.assertEqual(fighter.image_attribution, "Some Photographer")
        self.assertTrue(fighter.local_image_path.endswith("jon_jones.jpg"))

    def test_set_fighter_photo_for_unknown_fighter_does_not_raise(self):
        db = self._db()
        db.set_fighter_photo("nao_existe", local_image_path="x.jpg", image_license="CC0",
                              image_attribution="A", image_source_url="https://example.com")
        # não deve levantar exceção; simplesmente não grava nada


if __name__ == "__main__":
    unittest.main()
