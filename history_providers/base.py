"""
history_providers/base.py
--------------------------
Interface comum para qualquer fonte de histórico de lutas.

Cada provider (Sherdog, GIDStats, ou uma fonte futura) implementa a
mesma interface simples: dado um lutador, devolve uma lista de
FightRecord (ou lista vazia se não encontrou). Isso é o que permite
trocar/adicionar fontes sem tocar no resto do projeto — o orquestrador
(scripts/fetch_fight_history.py) só sabe que todo provider tem um
método `fetch(fighter)`, nunca precisa saber como cada site funciona
por dentro.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List

import requests

from models import Fighter, FightRecord


class HistoryProvider(ABC):
    """Interface que todo provider de histórico de lutas deve implementar."""

    #: Nome da fonte, usado no campo `source` de cada FightRecord gravado.
    source_name: str = "unknown"

    def __init__(self, session: requests.Session, verbose: bool = False) -> None:
        self.session = session
        self.verbose = verbose

    @abstractmethod
    def fetch(self, fighter: Fighter) -> List[FightRecord]:
        """
        Busca o histórico de lutas de um lutador nesta fonte.

        Deve retornar lista vazia (nunca levantar exceção para "não
        encontrado") quando o lutador não existir na fonte, for
        ambíguo, ou a extração falhar — a decisão de tentar outra fonte
        (fallback) é do orquestrador, não do provider.
        """
        raise NotImplementedError

    def _log(self, message: str) -> None:
        if self.verbose:
            print(f"  [{self.source_name}] {message}")
