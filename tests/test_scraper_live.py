"""
tests/test_scraper_live.py
----------------------------
Teste de integração REAL contra gidstats.com — precisa de acesso à
internet de verdade. Existe como rede de segurança contra regressões
que reduzem drasticamente (ou zeram) a quantidade de lutadores
coletados, como a causada por uma remoção excessiva de elementos HTML
(<nav>) numa correção anterior — esse tipo de bug não aparece nos
testes offline (que usam HTML sintético) porque o HTML de teste nunca
tinha uma tag <nav> envolvendo a listagem real.

Este teste NÃO roda junto com a suíte padrão (`python -m unittest
discover tests`) — ele fica desligado por padrão (via
@unittest.skipUnless) pra nunca quebrar num ambiente sem internet. Para
rodá-lo de propósito, na sua máquina, depois de qualquer mudança em
scripts/scrape_gidstats.py:

    FIGHTIQ_RUN_LIVE_TESTS=1 python -m unittest tests.test_scraper_live -v
"""

import os
import unittest

MIN_EXPECTED_FIGHTERS = 150

RUN_LIVE = os.environ.get("FIGHTIQ_RUN_LIVE_TESTS") == "1"


@unittest.skipUnless(
    RUN_LIVE,
    "Teste desligado por padrão (precisa de internet). Rode com "
    "FIGHTIQ_RUN_LIVE_TESTS=1 python -m unittest tests.test_scraper_live -v",
)
class TestScraperFindsMinimumFighterCount(unittest.TestCase):
    def test_ranking_page_returns_at_least_minimum_fighters(self):
        import requests
        from scripts.scrape_gidstats import fetch_ranking_entries

        session = requests.Session()
        session.headers.update({"User-Agent": "FightIQTests/1.0 (live test)"})
        entries = fetch_ranking_entries(session)

        self.assertGreater(
            len(entries), MIN_EXPECTED_FIGHTERS,
            f"Esperado mais de {MIN_EXPECTED_FIGHTERS} lutadores na página de rankings, "
            f"encontrado {len(entries)}. Isso indica uma regressão na extração — confira "
            f"mudanças recentes em fetch_ranking_entries() (ex.: elementos HTML removidos "
            f"em excesso) antes de fazer deploy dessa mudança.",
        )


if __name__ == "__main__":
    unittest.main()
