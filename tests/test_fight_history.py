"""
tests/test_fight_history.py
-----------------------------
Testes do histórico de lutas: providers (Sherdog, GIDStats), validação
de sanidade e persistência no banco.

Rode com:
    python -m unittest tests.test_fight_history -v
"""

import os
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import MagicMock

from database import DatabaseManager
from data_quality import (
    normalize_method, sanitize_fight_date, sanitize_fight_record_dict,
    sanitize_result, sanitize_round,
)
from history_providers.gidstats_provider import GIDStatsHistoryProvider
from history_providers.sherdog_provider import SherdogProvider
from models import Fighter, FightRecord

REAL_SHERDOG_TABLE_HTML = """
<html><body>
<div class="slanted_title"><div>FIGHT HISTORY - PRO</div></div>
<table class="new_table fighter">
<tr><th>Result</th><th>Fighter</th><th>Event</th><th>Method</th><th>R</th><th>Time</th></tr>
<tr>
  <td>win</td>
  <td><a href="/fighter/Jack-Della-Maddalena-208155">Jack Della Maddalena</a></td>
  <td><a href="/events/UFC-322">UFC 322 - Della Maddalena vs. Makhachev</a> Nov / 15 / 2025</td>
  <td><b>Decision (Unanimous)</b> <a href="/referee/Herb-Dean-5">Herb Dean</a></td>
  <td>5</td>
  <td>5:00</td>
</tr>
<tr>
  <td>loss</td>
  <td><a href="/fighter/Adriano-Martins-9907">Adriano Martins</a></td>
  <td><a href="/events/UFC-192">UFC 192 - Cormier vs. Gustafsson</a> Oct / 03 / 2015</td>
  <td><b>KO (Punch)</b> <a href="/referee/Frank-Collazo-317">Frank Collazo</a></td>
  <td>1</td>
  <td>1:46</td>
</tr>
</table>
</body></html>
"""

REAL_GIDSTATS_BLOCK_HTML = """
<html><body>
<h2>PRO Results</h2>
<div>
  <a href="/fighters/javid_basharat.html">Javid Basharat</a>
  <div>07.02.2026 Status: cancelled</div>
</div>
<div>
  <a href="/fighters/bryce_mitchell.html">Bryce Mitchell</a>
  <div>26.07.2025 • UFC Fight Night</div>
  <div>Round 3 Time 15.00 Method Decision</div>
</div>
</body></html>
"""


class TestDataQualityForFightRecords(unittest.TestCase):
    def test_normalize_method_variants(self):
        self.assertEqual(normalize_method("ko"), "KO/TKO")
        self.assertEqual(normalize_method("Submission"), "Submission")
        self.assertEqual(normalize_method("dq"), "DQ")

    def test_sanitize_result_accepts_only_fixed_vocabulary(self):
        self.assertEqual(sanitize_result("win"), "win")
        self.assertEqual(sanitize_result("No Contest"), "no_contest")
        self.assertIsNone(sanitize_result("vitória"))  # não está no vocabulário fixo

    def test_sanitize_round_rejects_out_of_range(self):
        self.assertEqual(sanitize_round(3), 3)
        self.assertIsNone(sanitize_round(9))
        self.assertIsNone(sanitize_round(0))

    def test_sanitize_fight_date_rejects_future_and_pre_ufc(self):
        future = (date.today() + timedelta(days=30)).isoformat()
        self.assertIsNone(sanitize_fight_date(future))
        self.assertIsNone(sanitize_fight_date("1980-01-01"))
        self.assertEqual(sanitize_fight_date("2023-11-11"), "2023-11-11")

    def test_sanitize_fight_record_dict_end_to_end(self):
        row = {"result": "WIN", "method": "sub", "round": "1", "fight_date": "2023-11-11"}
        clean = sanitize_fight_record_dict(row)
        self.assertEqual(clean["result"], "win")
        self.assertEqual(clean["method"], "Submission")
        self.assertEqual(clean["round"], 1)


class TestSherdogHistoryProvider(unittest.TestCase):
    def test_parses_real_table_structure_correctly(self):
        provider = SherdogProvider(session=MagicMock())
        records = provider._parse_fight_history(REAL_SHERDOG_TABLE_HTML, "islam_makhachev")

        self.assertEqual(len(records), 2)
        win = records[0]
        self.assertEqual(win.result, "win")
        self.assertEqual(win.opponent_name, "Jack Della Maddalena")
        self.assertEqual(win.fight_date, date(2025, 11, 15))
        self.assertEqual(win.method, "Decision")
        self.assertEqual(win.method_detail, "Unanimous")
        self.assertEqual(win.round, 5)
        self.assertEqual(win.time, "5:00")
        self.assertEqual(win.referee, "Herb Dean")

        loss = records[1]
        self.assertEqual(loss.result, "loss")
        self.assertEqual(loss.method, "KO")
        self.assertEqual(loss.method_detail, "Punch")

    def test_name_search_picks_exact_match_only(self):
        html = '<html><body><a href="/fighter/Islam-Makhachev-76836">Islam Makhachev</a></body></html>'
        session = MagicMock()
        response = MagicMock()
        response.text = html
        response.raise_for_status = lambda: None
        session.get.return_value = response

        provider = SherdogProvider(session=session)
        url = provider._find_profile_url("Islam Makhachev")
        self.assertEqual(url, "https://www.sherdog.com/fighter/Islam-Makhachev-76836")

    def test_ambiguous_name_returns_none_instead_of_guessing(self):
        html = (
            '<html><body>'
            '<a href="/fighter/Jon-Jones-1">Jon Jones</a>'
            '<a href="/fighter/Jon-Jones-2">Jon Jones</a>'
            '</body></html>'
        )
        session = MagicMock()
        response = MagicMock()
        response.text = html
        response.raise_for_status = lambda: None
        session.get.return_value = response

        provider = SherdogProvider(session=session)
        url = provider._find_profile_url("Jon Jones")
        self.assertIsNone(url)

    def test_fetch_returns_empty_list_when_fighter_not_found(self):
        html = "<html><body>Nenhum resultado</body></html>"
        session = MagicMock()
        response = MagicMock()
        response.text = html
        response.raise_for_status = lambda: None
        session.get.return_value = response

        provider = SherdogProvider(session=session)
        fighter = Fighter(fighter_id="x", name="Lutador Inexistente")
        records = provider.fetch(fighter)
        self.assertEqual(records, [])


class TestGIDStatsHistoryProviderFallback(unittest.TestCase):
    def test_cancelled_bout_is_excluded(self):
        provider = GIDStatsHistoryProvider(session=MagicMock())
        records = provider._parse_pro_results(REAL_GIDSTATS_BLOCK_HTML, "said_nurmagomedov")
        self.assertTrue(all(r.opponent_name != "Javid Basharat" for r in records))

    def test_result_is_deliberately_none_not_guessed(self):
        """
        Limitação conhecida e assumida: esta fonte não expõe resultado
        de forma confiável, então result deve ficar None (N/D na
        interface) em vez de um valor adivinhado.
        """
        provider = GIDStatsHistoryProvider(session=MagicMock())
        records = provider._parse_pro_results(REAL_GIDSTATS_BLOCK_HTML, "said_nurmagomedov")
        bryce = [r for r in records if r.opponent_name == "Bryce Mitchell"]
        self.assertEqual(len(bryce), 1)
        self.assertIsNone(bryce[0].result)
        self.assertEqual(bryce[0].round, 3)

    def test_fetch_returns_empty_when_no_source_url(self):
        provider = GIDStatsHistoryProvider(session=MagicMock())
        fighter = Fighter(fighter_id="x", name="Sem Fonte", source_url=None)
        self.assertEqual(provider.fetch(fighter), [])


class TestFightHistoryDatabasePersistence(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.db_path = self.tmp / "test.db"
        self.db = DatabaseManager(db_path=str(self.db_path))
        self.db.initialize()

    def tearDown(self):
        if self.db_path.exists():
            os.remove(self.db_path)

    def test_save_and_list_ordered_most_recent_first(self):
        records = [
            FightRecord(fighter_id="jon_jones", opponent_name="A", fight_date=date(2020, 1, 1), result="win"),
            FightRecord(fighter_id="jon_jones", opponent_name="B", fight_date=date(2023, 1, 1), result="win"),
        ]
        self.db.save_fight_history(records)
        history = self.db.list_fight_history("jon_jones")
        self.assertEqual([h.opponent_name for h in history], ["B", "A"])

    def test_rerunning_collector_updates_instead_of_duplicating(self):
        """A chave natural (fighter_id, opponent_name, fight_date) evita duplicar ao rodar de novo."""
        r1 = FightRecord(fighter_id="jon_jones", opponent_name="A", fight_date=date(2020, 1, 1), result="win")
        self.db.save_fight_history([r1])
        r1_updated = FightRecord(fighter_id="jon_jones", opponent_name="A", fight_date=date(2020, 1, 1),
                                  result="win", method="KO/TKO")  # mesmo bout, campo novo
        self.db.save_fight_history([r1_updated])
        history = self.db.list_fight_history("jon_jones")
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0].method, "KO/TKO")

    def test_has_fight_history(self):
        self.assertFalse(self.db.has_fight_history("jon_jones"))
        self.db.save_fight_history([
            FightRecord(fighter_id="jon_jones", opponent_name="A", fight_date=date(2020, 1, 1), result="win"),
        ])
        self.assertTrue(self.db.has_fight_history("jon_jones"))


if __name__ == "__main__":
    unittest.main()
