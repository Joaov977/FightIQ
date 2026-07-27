"""
history_providers/gidstats_provider.py
-----------------------------------------
Provider de FALLBACK de histórico de lutas: GIDStats.com ("PRO Results").

Usado só quando o Sherdog não encontra o lutador (nome ambíguo, lutador
regional não catalogado lá, etc.) — o Sherdog continua sendo a fonte
primária porque tem uma tabela HTML de verdade com o resultado como
coluna explícita.

IMPORTANTE — limitação conhecida e assumida deste provider:
o GIDStats NÃO expõe o resultado (vitória/derrota/empate) como texto
limpo — o bloco de cada luta mostra os 4 rótulos possíveis juntos
("Win! Loss! Draw Not Confirmed"), porque só um é destacado
visualmente via CSS/classe, o que se perde na extração de texto. Uma
técnica de inferência por diferença de cartel (comparar W-L-D antes e
depois de cada luta) foi considerada, mas exigiria acesso ao HTML bruto
real para confirmar a ordem exata dos números — que não temos neste
momento. Por isso, `result` fica deliberadamente None nas lutas vindas
deste provider (exibido como "N/D" na interface) em vez de arriscar um
valor errado. Os demais campos (adversário, data, evento, método,
round, tempo) são extraídos normalmente. Se no futuro conseguirmos
confirmar a estrutura exata via `--inspect` com HTML real, essa
limitação pode ser removida.
"""

from __future__ import annotations

import re
from datetime import date
from typing import List, Optional

from bs4 import BeautifulSoup

from history_providers.base import HistoryProvider
from models import Fighter, FightRecord

BASE_URL = "https://gidstats.com"


def _parse_gidstats_date(text: str) -> Optional[date]:
    """GIDStats usa o formato 'DD.MM.YYYY'."""
    match = re.search(r"(\d{1,2})\.(\d{1,2})\.(\d{4})", text)
    if not match:
        return None
    d, m, y = match.groups()
    try:
        return date(int(y), int(m), int(d))
    except ValueError:
        return None


class GIDStatsHistoryProvider(HistoryProvider):
    source_name = "GIDStats.com"

    def fetch(self, fighter: Fighter) -> List[FightRecord]:
        if not fighter.source_url:
            self._log(f"'{fighter.name}' sem source_url do GIDStats cadastrada — pulando.")
            return []

        try:
            response = self.session.get(fighter.source_url, timeout=15)
            response.raise_for_status()
        except Exception as exc:
            self._log(f"Falha ao buscar {fighter.source_url}: {exc}")
            return []

        records = self._parse_pro_results(response.text, fighter.fighter_id)
        self._log(f"'{fighter.name}': {len(records)} luta(s) extraída(s) de {fighter.source_url} "
                  f"(resultado N/D nesta fonte — ver limitação documentada)")
        return records

    # ------------------------------------------------------------------
    def _parse_pro_results(self, html: str, fighter_id: str) -> List[FightRecord]:
        soup = BeautifulSoup(html, "html.parser")

        section_title = soup.find(string=re.compile(r"PRO Results", re.IGNORECASE))
        if section_title is None:
            return []

        # Cada bloco de luta é delimitado por um link "VS <adversário>"
        # apontando para /fighters/<slug>.html — usamos isso como âncora
        # estrutural, igual já fazemos no scraper principal do roster.
        opponent_links = []
        node = section_title
        while True:
            node = node.find_next("a")
            if node is None:
                break
            href = node.get("href", "")
            if href.startswith("/fighters/") and href.endswith(".html"):
                opponent_links.append(node)

        records: List[FightRecord] = []
        for link in opponent_links:
            opponent_name = link.get_text(strip=True)
            opponent_url = BASE_URL + link["href"]

            # Janela de texto ao redor do link (mesmo bloco da luta) —
            # navegação estrutural, não distância de caracteres.
            context_nodes = []
            n = link
            for _ in range(25):
                n = n.find_next(string=True)
                if n is None:
                    break
                text = str(n).strip()
                if text:
                    context_nodes.append(text)
                if len(context_nodes) >= 15:
                    break
            context = " ".join(context_nodes)

            if re.search(r"cancelled", context, re.IGNORECASE):
                continue  # luta cancelada, não é um resultado real

            fight_date = _parse_gidstats_date(context)
            event_match = re.search(r"•\s*([^\n]+?)(?:\s+Round|\s+Method|$)", context)
            event_name = event_match.group(1).strip() if event_match else None
            round_match = re.search(r"Round\s+(\d)", context, re.IGNORECASE)
            time_match = re.search(r"Time\s+([\d.:]+)", context, re.IGNORECASE)
            method_match = re.search(r"Method\s+([A-Za-z/ ]+)", context, re.IGNORECASE)

            records.append(FightRecord(
                fighter_id=fighter_id,
                opponent_name=opponent_name,
                opponent_source_url=opponent_url,
                event_name=event_name,
                fight_date=fight_date,
                result=None,  # limitação conhecida desta fonte — ver docstring do módulo
                method=method_match.group(1).strip() if method_match else None,
                round=int(round_match.group(1)) if round_match else None,
                time=time_match.group(1) if time_match else None,
                source=self.source_name,
                source_url=BASE_URL,
            ))

        return records
