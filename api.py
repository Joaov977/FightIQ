"""
api.py
------
Camada de acesso a dados externos do FightIQ.

Contexto importante sobre a fonte de dados
===========================================
Não existe, no momento em que este projeto foi construído, uma API pública
gratuita e confiável que forneça estatísticas completas de lutadores do
UFC (golpes por minuto, defesa de quedas, etc.) em formato estruturado.
Por isso, o FightIQ segue a estratégia descrita no README.md:

    1. Os dados exibidos pelo aplicativo vêm de um banco SQLite local
       (database.py), populado a partir de um CSV com dados reais
       coletados manualmente de fontes públicas verificáveis (GIDStats.com
       e UFC.com — ver a coluna `source_url` de cada lutador na tabela
       `fighters`).
    2. Este módulo, `api.py`, existe como a camada de integração externa
       do projeto: é aqui — e só aqui — que o FightIQ deveria falar com a
       internet para buscar ou atualizar dados de lutadores. Isso mantém
       o resto do sistema (interface, análise, gráficos) completamente
       desacoplado de como e de onde os dados chegam.
    3. `DataUpdateService` abaixo mostra o esqueleto pronto para ligar uma
       fonte real (ex.: um endpoint JSON próprio, um scraper autorizado,
       ou uma futura API oficial) usando a biblioteca `requests`. Ele não
       inventa dados: se a fonte não responder ou o campo não existir,
       o valor correspondente permanece None e a interface mostra "N/D".

Ou seja: este módulo é o único lugar do projeto autorizado a fazer
requisições de rede, e o único lugar que precisa mudar quando uma fonte
de dados real (API ou scraper) estiver disponível para uso contínuo.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import requests

from utils import get_logger

logger = get_logger(__name__)

REQUEST_TIMEOUT_SECONDS = 10


@dataclass
class FighterUpdatePayload:
    """
    Estrutura esperada de um registro de atualização vindo de uma fonte
    externa. Corresponde 1:1 às colunas de `fighters` e `fighter_stats`
    em database.py, para que um retorno de API possa ser gravado
    diretamente pelo DatabaseManager sem transformação adicional.
    """

    fighter_id: str  # slug estável, ex.: 'jon_jones'
    name: str
    nickname: Optional[str] = None
    nationality: Optional[str] = None
    weight_class: Optional[str] = None
    height_cm: Optional[float] = None
    reach_cm: Optional[float] = None
    stance: Optional[str] = None
    birth_date: Optional[str] = None
    wins: Optional[int] = None
    losses: Optional[int] = None
    draws: Optional[int] = None
    no_contests: Optional[int] = None
    wins_ko: Optional[int] = None
    wins_sub: Optional[int] = None
    wins_dec: Optional[int] = None
    slpm: Optional[float] = None
    str_acc_pct: Optional[float] = None
    sapm: Optional[float] = None
    str_def_pct: Optional[float] = None
    td_avg: Optional[float] = None
    td_acc_pct: Optional[float] = None
    td_def_pct: Optional[float] = None
    sub_avg: Optional[float] = None
    avg_fight_time: Optional[str] = None
    source: Optional[str] = None
    source_url: Optional[str] = None


class DataUpdateService:
    """
    Serviço responsável por buscar atualizações de uma fonte externa.

    Este serviço é opcional: o aplicativo funciona inteiramente offline
    usando o banco SQLite local. Ele foi incluído para deixar claro como
    o FightIQ deve evoluir quando uma fonte de dados ao vivo (API oficial,
    endpoint próprio, etc.) estiver disponível — sem exigir mudanças em
    nenhum outro módulo do projeto.

    Uso pretendido (quando uma `base_url` real estiver configurada):

        service = DataUpdateService(base_url="https://minha-fonte-de-dados/api")
        payload = service.fetch_fighter_update("Jon Jones")
        if payload:
            db.apply_update(payload)   # método a implementar em database.py
    """

    def __init__(self, base_url: Optional[str] = None) -> None:
        self.base_url = base_url
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "FightIQ/1.0 (educational project)"})

    def is_configured(self) -> bool:
        return bool(self.base_url)

    def fetch_fighter_update(self, fighter_name: str) -> Optional[FighterUpdatePayload]:
        """
        Busca dados atualizados de um lutador na fonte configurada.

        Retorna None (em vez de inventar valores) sempre que:
            - nenhuma `base_url` foi configurada;
            - a requisição falha (rede, timeout, HTTP 4xx/5xx);
            - a resposta não contém os campos esperados.
        """
        if not self.is_configured():
            logger.info(
                "DataUpdateService sem fonte configurada; nenhuma atualização buscada "
                "para '%s'. O app continuará usando o banco local.",
                fighter_name,
            )
            return None

        try:
            response = self.session.get(
                f"{self.base_url}/fighters",
                params={"name": fighter_name},
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            data = response.json()
        except requests.RequestException as exc:
            logger.warning("Falha ao buscar atualização para '%s': %s", fighter_name, exc)
            return None
        except ValueError:
            logger.warning("Resposta inválida (não-JSON) para '%s'.", fighter_name)
            return None

        try:
            return FighterUpdatePayload(**data)
        except TypeError:
            logger.warning("Payload de atualização com campos inesperados para '%s'.", fighter_name)
            return None

    def check_connectivity(self) -> bool:
        """Verifica rapidamente se a fonte configurada está acessível."""
        if not self.is_configured():
            return False
        try:
            response = self.session.get(self.base_url, timeout=5)
            return response.status_code < 500
        except requests.RequestException:
            return False
