"""
history_providers/sherdog_provider.py
---------------------------------------
Provider PRIMÁRIO de histórico de lutas: Sherdog.com Fight Finder.

Escolhido como fonte principal (ver conversa/README) porque:
    - Usa uma tabela HTML de verdade (`<table class="new_table fighter">`),
      não divs/spans aninhados — muito mais estável a mudanças visuais
      do que o padrão que já nos deu 3 regressões no scraper do GIDStats.
    - O resultado (vitória/derrota/empate) é uma coluna própria e
      explícita ("win"/"loss"/...), não um badge ambíguo — resolve o
      ponto mais frágil que teríamos se usássemos só o GIDStats.
    - Referência histórica da indústria de MMA (desde 1997), citada
      pela própria Wikipédia via template dedicado.

Confirmado via busca ao vivo (ver conversa): Sherdog não bloqueia
requisições HTTP simples (sem necessidade de browser headless) nos
caminhos /fighter/*, /stats/fightfinder.

Busca por nome: não existe endpoint de busca por relevância — só
`/stats/fightfinder?SearchTxt=`, que devolve resultados em ordem
alfabética por primeiro nome, sem ranking de relevância. Por isso,
filtramos por CORRESPONDÊNCIA EXATA de nome entre os candidatos
retornados; se não sobrar exatamente 1 candidato (nome ambíguo ou não
encontrado), não adivinhamos — devolvemos lista vazia e deixamos o
orquestrador cair para o próximo provider.
"""

from __future__ import annotations

import re
from datetime import date
from typing import List, Optional

from bs4 import BeautifulSoup

from history_providers.base import HistoryProvider
from models import Fighter, FightRecord

BASE_URL = "https://www.sherdog.com"
SEARCH_URL = f"{BASE_URL}/stats/fightfinder"

_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}


def _parse_sherdog_date(text: str) -> Optional[date]:
    """Sherdog usa o formato 'Mon / DD / YYYY' (ex.: 'Nov / 15 / 2025')."""
    match = re.search(r"([A-Za-z]{3})\s*/\s*(\d{1,2})\s*/\s*(\d{4})", text)
    if not match:
        return None
    mon, day, year = match.groups()
    month_num = _MONTHS.get(mon.lower()[:3])
    if not month_num:
        return None
    try:
        return date(int(year), month_num, int(day))
    except ValueError:
        return None


def _split_method(text: str):
    """'Decision (Unanimous)' -> ('Decision', 'Unanimous'); 'KO (Punch)' -> ('KO', 'Punch')."""
    text = text.strip()
    match = re.match(r"^([A-Za-z/ ]+?)\s*\(([^)]*)\)\s*$", text)
    if match:
        return match.group(1).strip(), match.group(2).strip()
    return (text or None), None


class SherdogProvider(HistoryProvider):
    source_name = "Sherdog.com"

    def fetch(self, fighter: Fighter) -> List[FightRecord]:
        profile_url = self._find_profile_url(fighter.name)
        if not profile_url:
            self._log(f"'{fighter.name}' não encontrado (ou nome ambíguo) — pulando.")
            return []

        try:
            response = self.session.get(profile_url, timeout=15)
            response.raise_for_status()
        except Exception as exc:
            self._log(f"Falha ao buscar {profile_url}: {exc}")
            return []

        records = self._parse_fight_history(response.text, fighter.fighter_id)
        self._log(f"'{fighter.name}': {len(records)} luta(s) extraída(s) de {profile_url}")
        return records

    # ------------------------------------------------------------------
    def _find_profile_url(self, name: str) -> Optional[str]:
        try:
            response = self.session.get(SEARCH_URL, params={"SearchTxt": name}, timeout=15)
            response.raise_for_status()
        except Exception as exc:
            self._log(f"Falha na busca por '{name}': {exc}")
            return None

        soup = BeautifulSoup(response.text, "html.parser")
        candidates = []
        for a in soup.find_all("a", href=re.compile(r"^/fighter/[^/]+-\d+$")):
            link_name = a.get_text(strip=True)
            if link_name.lower() == name.lower():
                candidates.append(BASE_URL + a["href"])

        unique = list(dict.fromkeys(candidates))
        if len(unique) == 1:
            return unique[0]
        if len(unique) > 1:
            self._log(f"'{name}' é ambíguo no Sherdog ({len(unique)} candidatos) — não adivinhando.")
        return None

    # ------------------------------------------------------------------
    def _parse_fight_history(self, html: str, fighter_id: str) -> List[FightRecord]:
        soup = BeautifulSoup(html, "html.parser")

        # A tabela de histórico profissional vem depois de um título
        # "FIGHT HISTORY - PRO" (ver docstring/evidência real). Localiza
        # a tabela mais próxima seguindo esse título; se não achar por
        # esse caminho, cai para a primeira tabela de classe conhecida.
        table = None
        title_node = soup.find(string=re.compile(r"FIGHT HISTORY\s*-\s*PRO", re.IGNORECASE))
        if title_node is not None:
            table = title_node.find_next("table")
        if table is None:
            table = soup.find("table", class_=re.compile(r"\bfighter\b"))
        if table is None:
            return []

        records: List[FightRecord] = []
        rows = table.find_all("tr")
        for row in rows:
            cells = row.find_all("td")
            if len(cells) < 5:
                continue  # linha de cabeçalho ou formatação inesperada

            result_text = cells[0].get_text(strip=True).lower()
            if result_text not in ("win", "loss", "draw", "nc", "no contest"):
                continue  # não é uma linha de luta de verdade

            opponent_link = cells[1].find("a")
            opponent_name = opponent_link.get_text(strip=True) if opponent_link else cells[1].get_text(strip=True)
            opponent_url = (BASE_URL + opponent_link["href"]) if opponent_link and opponent_link.get("href") else None

            event_link = cells[2].find("a")
            event_name = event_link.get_text(strip=True) if event_link else None
            event_url = (BASE_URL + event_link["href"]) if event_link and event_link.get("href") else None
            fight_date = _parse_sherdog_date(cells[2].get_text(" ", strip=True))

            method_bold = cells[3].find("b")
            method_text = method_bold.get_text(strip=True) if method_bold else cells[3].get_text(" ", strip=True)
            method, method_detail = _split_method(method_text)
            referee_link = cells[3].find("a", href=re.compile(r"^/referee/"))
            referee = referee_link.get_text(strip=True) if referee_link else None

            round_text = cells[4].get_text(strip=True) if len(cells) > 4 else None
            time_text = cells[5].get_text(strip=True) if len(cells) > 5 else None

            result_map = {"win": "win", "loss": "loss", "draw": "draw", "nc": "no_contest", "no contest": "no_contest"}

            records.append(FightRecord(
                fighter_id=fighter_id,
                opponent_name=opponent_name,
                opponent_source_url=opponent_url,
                event_name=event_name,
                event_source_url=event_url,
                fight_date=fight_date,
                result=result_map.get(result_text),
                method=method,
                method_detail=method_detail,
                round=int(round_text) if round_text and round_text.isdigit() else None,
                time=time_text or None,
                referee=referee,
                source=self.source_name,
                source_url=event_url,
            ))

        return records
