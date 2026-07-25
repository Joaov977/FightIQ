"""
tests/test_scraper_parsing.py
-------------------------------
Testes de regressão para os 4 campos investigados na auditoria de
qualidade de dados (idade, altura, alcance, nacionalidade), usando
fixtures de HTML reconstruídas a partir da estrutura real observada em
https://gidstats.com/fighters/miesha_tate.html (rótulo e valor em
elementos separados — a causa raiz dos bugs originais).

Rode com:
    python -m unittest tests.test_scraper_parsing -v
"""

import unittest
from bs4 import BeautifulSoup

from scripts.scrape_gidstats import (
    extract_age_reported,
    extract_height_cm,
    extract_nationality,
    extract_reach_cm,
    fetch_ranking_entries,
    parse_fighter_page,
    slug_from_url,
    RankingEntry,
)

# Reconstrução da estrutura real: rótulo e valor em <span> irmãos
# separados dentro do mesmo bloco — o cenário que quebrava o regex
# original (que exigia estarem na mesma "linha" de texto achatado).
REAL_STRUCTURE_HTML = """
<html><body>
<h1>Miesha Tate</h1>
<div class="record">20 - 10 - 0</div>
<div class="age-block"><span>(W-L-D) Age</span> <span>39</span></div>
<div class="stat-row"><span class="label">Height</span><span class="value">66 inch</span><span class="value">168 cm</span></div>
<div class="stat-row"><span class="label">Reach</span><span class="value">65 inch</span><span class="value">165 cm</span></div>
<div class="stat-row"><span class="label">Leg Reach</span><span class="value">37 inch</span><span class="value">94 cm</span></div>
<div class="country">USA</div>
<div class="style">Style Grappling</div>
<div class="stance">Stance Orthodox</div>
<div class="born">Born Tacoma, United States</div>
</body></html>
"""


class TestStructuralHeightExtraction(unittest.TestCase):
    def test_height_found_when_label_and_value_are_separate_elements(self):
        soup = BeautifulSoup(REAL_STRUCTURE_HTML, "html.parser")
        self.assertEqual(extract_height_cm(soup), 168.0)

    def test_height_missing_returns_none_not_wrong_value(self):
        soup = BeautifulSoup("<html><body><h1>Sem Altura</h1></body></html>", "html.parser")
        self.assertIsNone(extract_height_cm(soup))

    def test_height_supports_meters_fallback(self):
        html = '<html><body><div><span>Height</span><span>1.93 m</span></div></body></html>'
        soup = BeautifulSoup(html, "html.parser")
        self.assertEqual(extract_height_cm(soup), 193.0)


class TestStructuralReachExtraction(unittest.TestCase):
    def test_reach_does_not_get_confused_with_leg_reach(self):
        """
        Regressão específica: 'Reach' e 'Leg Reach' aparecem na mesma
        página; o extrator precisa pegar o valor de 'Reach' (165cm),
        nunca o de 'Leg Reach' (94cm), mesmo com "Reach" sendo
        substring de "Leg Reach".
        """
        soup = BeautifulSoup(REAL_STRUCTURE_HTML, "html.parser")
        reach = extract_reach_cm(soup)
        self.assertEqual(reach, 165.0)
        self.assertNotEqual(reach, 94.0)


class TestAgeReportedExtraction(unittest.TestCase):
    def test_age_extracted_directly_not_derived_from_dob(self):
        soup = BeautifulSoup(REAL_STRUCTURE_HTML, "html.parser")
        text = soup.get_text("\n", strip=True)
        self.assertEqual(extract_age_reported(soup, text), 39)

    def test_age_falls_back_to_full_text_regex_when_label_not_isolated(self):
        """'Age' colado a outro texto no mesmo nó (sem nó próprio) ainda deve funcionar."""
        html = "<html><body><div>(W-L-D) Age 27 more text</div></body></html>"
        soup = BeautifulSoup(html, "html.parser")
        text = soup.get_text("\n", strip=True)
        self.assertEqual(extract_age_reported(soup, text), 27)

    def test_no_age_present_returns_none(self):
        soup = BeautifulSoup("<html><body><h1>Sem Idade</h1></body></html>", "html.parser")
        text = soup.get_text("\n", strip=True)
        self.assertIsNone(extract_age_reported(soup, text))


class TestNationalityExtraction(unittest.TestCase):
    def test_nationality_extracted_from_token_before_style_label(self):
        """
        A fonte confiável de nacionalidade é o token solto logo antes
        do rótulo 'Style' (não existe rótulo 'Country:' na página).
        """
        soup = BeautifulSoup(REAL_STRUCTURE_HTML, "html.parser")
        self.assertEqual(extract_nationality(soup), "USA")

    def test_no_born_field_returns_none(self):
        soup = BeautifulSoup("<html><body><h1>Sem Style</h1></body></html>", "html.parser")
        self.assertIsNone(extract_nationality(soup))

    def test_accented_city_name_does_not_break_extraction(self):
        """
        Regressão do bug do Alex Pereira: 'Born São Bernardo do Campo,
        São Paulo, Brazil' tem (a) um nome de cidade acentuado e (b)
        DUAS vírgulas (cidade, estado, país) — a versão antiga cortava
        no primeiro caractere não-ASCII e pegava o estado, não o país.
        A extração correta usa o token solto antes de 'Style', não o
        campo 'Born'.
        """
        html = """
        <html><body>
        <h1>Alex Pereira</h1>
        <div>Brazil</div>
        <div>Style Kickboxing</div>
        <div>Born São Bernardo do Campo, São Paulo, Brazil</div>
        </body></html>
        """
        soup = BeautifulSoup(html, "html.parser")
        self.assertEqual(extract_nationality(soup), "Brazil")

    def test_whitespace_only_text_nodes_between_tags_are_skipped(self):
        """HTML formatado com indentação/quebras de linha entre tags não deve quebrar a busca."""
        html = "<html><body>\n  <div>\n    Brazil\n  </div>\n  <div>\n    Style Kickboxing\n  </div>\n</body></html>"
        soup = BeautifulSoup(html, "html.parser")
        self.assertEqual(extract_nationality(soup), "Brazil")


class TestRankingDropdownDoesNotContaminateWeightClass(unittest.TestCase):
    """
    Regressão do bug relatado: Alex Pereira, Alexandre Pantoja e
    Alexander Volkanovski apareciam todos como 'Women's Bantamweight'
    porque um <select> de filtro (com todas as categorias, inclusive
    essa por último) contaminava a detecção de cabeçalhos de seção.
    """

    def _fake_ranking_html(self) -> str:
        return """
        <html><body>
        <select>
        <option>Men's Pound-for-Pound Top Rank</option>
        <option>Heavyweight</option>
        <option>Light Heavyweight</option>
        <option>Flyweight</option>
        <option>Featherweight</option>
        <option>Women's Pound-for-Pound Top Rank</option>
        <option>Women's Bantamweight</option>
        </select>
        <h2>Light Heavyweight</h2>
        <a href="/fighters/alex_pereira.html">Alex Pereira</a>
        <h2>Flyweight</h2>
        <a href="/fighters/alexandre_pantoja.html">Alexandre Pantoja</a>
        <h2>Featherweight</h2>
        <a href="/fighters/alexander_volkanovski.html">Alexander Volkanovski</a>
        <h2>Women's Bantamweight</h2>
        <a href="/fighters/some_woman_fighter.html">Some Woman Fighter</a>
        </body></html>
        """

    def test_men_fighters_get_correct_division_not_last_dropdown_option(self):
        from unittest.mock import MagicMock

        session = MagicMock()
        response = MagicMock()
        response.text = self._fake_ranking_html()
        response.raise_for_status = lambda: None
        session.get.return_value = response

        entries = fetch_ranking_entries(session)

        self.assertEqual(
            entries["https://gidstats.com/fighters/alex_pereira.html"].weight_class, "Light Heavyweight"
        )
        self.assertEqual(
            entries["https://gidstats.com/fighters/alexandre_pantoja.html"].weight_class, "Flyweight"
        )
        self.assertEqual(
            entries["https://gidstats.com/fighters/alexander_volkanovski.html"].weight_class, "Featherweight"
        )
        # A seção real de Women's Bantamweight (depois do dropdown) continua correta
        self.assertEqual(
            entries["https://gidstats.com/fighters/some_woman_fighter.html"].weight_class, "Women's Bantamweight"
        )

    def test_real_fighter_listing_inside_nav_tag_is_not_deleted(self):
        """
        Regressão direta: uma correção anterior removia <nav> "por
        precaução", sem evidência de que fosse fonte de contaminação —
        isso apagava a listagem real de lutadores sempre que ela estava
        dentro de uma tag <nav> (comum e semanticamente correto para
        uma lista de rankings), zerando a coleta ("0 lutadores
        encontrados"). Só <select>/<option> devem ser removidos — são a
        única fonte de contaminação com evidência real por trás.
        """
        from unittest.mock import MagicMock

        html = """
        <html><body>
        <select><option>Women's Bantamweight</option></select>
        <nav>
        <h2>Heavyweight</h2>
        <a href="/fighters/jon_jones.html">Jon Jones</a>
        <h2>Light Heavyweight</h2>
        <a href="/fighters/alex_pereira.html">Alex Pereira</a>
        </nav>
        </body></html>
        """
        session = MagicMock()
        response = MagicMock()
        response.text = html
        response.raise_for_status = lambda: None
        session.get.return_value = response

        entries = fetch_ranking_entries(session)
        self.assertEqual(len(entries), 2)
        self.assertEqual(entries["https://gidstats.com/fighters/jon_jones.html"].weight_class, "Heavyweight")
        self.assertEqual(
            entries["https://gidstats.com/fighters/alex_pereira.html"].weight_class, "Light Heavyweight"
        )

    def test_fighter_name_wrapped_in_nested_spans_is_still_detected(self):
        """
        Regressão do bug de "0 lutadores encontrados": a estrutura real
        da página envolve o nome do lutador em <span> aninhados dentro
        do <a> (confirmado ao vivo — o texto do link vem fragmentado em
        spans de primeiro nome / rank / nome completo, ex.: "Islam 1
        IslamMakhachev"). A versão anterior checava se o nó de TEXTO
        tinha o <a> como pai direto — com spans aninhados, o pai direto
        do texto é o <span>, nunca o <a>, e ZERO links batiam com essa
        condição. A extração agora trata cada <a> como uma unidade
        (soup.descendants + get_text()), não importando o quanto de
        aninhamento exista dentro dele.
        """
        from unittest.mock import MagicMock

        html = """
        <html><body>
        <h3>Heavyweight</h3>
        <ul>
        <li><a href="/fighters/tom_aspinall.html"><span>Tom</span><span>TomAspinall Champion</span></a></li>
        <li><a href="/fighters/ciryl_gane.html"><span>Ciryl</span><span>1</span><span>CirylGane</span></a></li>
        </ul>
        <h3>Light Heavyweight</h3>
        <ul>
        <li><a href="/fighters/alex_pereira.html"><span>Alex</span><span>AlexPereira Champion</span></a></li>
        </ul>
        </body></html>
        """
        session = MagicMock()
        response = MagicMock()
        response.text = html
        response.raise_for_status = lambda: None
        session.get.return_value = response

        entries = fetch_ranking_entries(session)
        self.assertEqual(len(entries), 3)
        self.assertEqual(entries["https://gidstats.com/fighters/tom_aspinall.html"].weight_class, "Heavyweight")
        self.assertEqual(entries["https://gidstats.com/fighters/ciryl_gane.html"].weight_class, "Heavyweight")
        self.assertEqual(
            entries["https://gidstats.com/fighters/alex_pereira.html"].weight_class, "Light Heavyweight"
        )
        # nome não fica vazio nem quebra, mesmo vindo de spans concatenados
        self.assertIn("Tom", entries["https://gidstats.com/fighters/tom_aspinall.html"].name)

    def test_verbose_mode_does_not_raise_and_returns_same_result(self):
        """verbose=True é só instrumentação de diagnóstico — não pode mudar o resultado."""
        from unittest.mock import MagicMock

        html = self._fake_ranking_html()
        session = MagicMock()
        response = MagicMock()
        response.text = html
        response.content = html.encode()
        response.status_code = 200
        response.raise_for_status = lambda: None
        session.get.return_value = response

        entries_quiet = fetch_ranking_entries(session)
        entries_verbose = fetch_ranking_entries(session, verbose=True)
        self.assertEqual(set(entries_quiet.keys()), set(entries_verbose.keys()))


class TestSlugFromUrl(unittest.TestCase):
    def test_extracts_slug_correctly(self):
        self.assertEqual(slug_from_url("https://gidstats.com/fighters/miesha_tate.html"), "miesha_tate")

    def test_handles_trailing_slash(self):
        self.assertEqual(slug_from_url("https://gidstats.com/fighters/jon_jones.html/"), "jon_jones")


class TestFullParseFighterPage(unittest.TestCase):
    """Teste de integração: os 5 campos investigados, juntos, no fluxo completo de parse_fighter_page."""

    def test_all_investigated_fields_correct_together(self):
        result = parse_fighter_page(
            REAL_STRUCTURE_HTML, "https://gidstats.com/fighters/miesha_tate.html"
        )
        self.assertIsNotNone(result)
        self.assertEqual(result.fighter_id, "miesha_tate")
        self.assertEqual(result.height_cm, 168.0)
        self.assertEqual(result.reach_cm, 165.0)
        self.assertEqual(result.age_reported, 39)
        self.assertEqual(result.nationality, "USA")
        # birth_date deve ficar None (a página não publica DOB numérico)
        self.assertIsNone(result.birth_date)
        # cartel continua funcionando (não deveria ter regredido)
        self.assertEqual((result.wins, result.losses, result.draws), (20, 10, 0))

    def test_ranking_hint_overrides_weight_class_extraction(self):
        hint = RankingEntry(name="Miesha Tate", weight_class="Bantamweight", rank=14)
        result = parse_fighter_page(
            REAL_STRUCTURE_HTML, "https://gidstats.com/fighters/miesha_tate.html", ranking_hint=hint,
        )
        self.assertEqual(result.weight_class, "Bantamweight")
        self.assertEqual(result.ranking, "#14 Bantamweight")


class TestFetchRankingEntries(unittest.TestCase):
    def test_rank_and_weight_class_assigned_in_document_order(self):
        from unittest.mock import MagicMock

        fake_html = """
        <html><body>
        <h2>Middleweight</h2>
        <a href="/fighters/lutador_a.html">Lutador A</a>
        <a href="/fighters/lutador_b.html">Lutador B</a>
        <h2>Welterweight</h2>
        <a href="/fighters/lutador_c.html">Lutador C</a>
        </body></html>
        """
        session = MagicMock()
        response = MagicMock()
        response.text = fake_html
        response.raise_for_status = lambda: None
        session.get.return_value = response

        entries = fetch_ranking_entries(session)
        self.assertEqual(entries["https://gidstats.com/fighters/lutador_a.html"].weight_class, "Middleweight")
        self.assertEqual(entries["https://gidstats.com/fighters/lutador_a.html"].rank, 1)
        self.assertEqual(entries["https://gidstats.com/fighters/lutador_b.html"].rank, 2)
        self.assertEqual(entries["https://gidstats.com/fighters/lutador_c.html"].weight_class, "Welterweight")


if __name__ == "__main__":
    unittest.main()
