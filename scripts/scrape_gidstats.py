"""
scripts/scrape_gidstats.py
--------------------------
Utilitário de coleta de dados em escala para o FightIQ.

Este script é a resposta correta para "por que só 3 lutadores no banco?":
os 3 lutadores da entrega original foram coletados manualmente, um a um,
para garantir 100% de precisão. Isso não escala. Este script automatiza
exatamente o mesmo processo — ler as páginas públicas do GIDStats.com e
extrair os campos reais — para popular o CSV com dezenas ou centenas de
lutadores de uma vez, sem inventar nenhum valor.

IMPORTANTE — por que isso não roda dentro do chat com o Claude:
O ambiente onde o FightIQ foi desenvolvido e testado não tem acesso de
rede a gidstats.com (só a domínios de pacotes Python, como pypi.org).
Rode este script na SUA máquina, que tem acesso normal à internet.

O que o script faz, em ordem:
    1. Verifica o robots.txt do GIDStats.com antes de fazer qualquer
       requisição, e para caso o scraping não seja permitido nos
       caminhos usados (/ranking/ e /fighters/).
    2. Baixa a página de rankings (gidstats.com/ranking/ufc/), que lista
       a maior parte do roster ativo do UFC com link para a página de
       cada lutador — isso dá, tipicamente, 100+ lutadores únicos.
    3. Visita a página de cada lutador, extrai os campos reais (cartel,
       físico, golpes, quedas) e grava tudo em
       assets/data/fighters_seed.csv.
    4. Faz uma pausa (--delay) entre requisições para ser um "bom
       cidadão" da web — não sobrecarregar o servidor do GIDStats.

Campos que o parser não conseguir encontrar na página ficam como None
(célula vazia no CSV) — nunca um valor estimado ou interpolado.

Uso:
    python scripts/scrape_gidstats.py                  # roda tudo
    python scripts/scrape_gidstats.py --limit 20        # só os 20 primeiros
    python scripts/scrape_gidstats.py --delay 2.0        # mais devagar
    python scripts/scrape_gidstats.py --inspect jon_jones  # debug de 1 página

Depois de rodar, atualize o banco com:
    python -c "from database import DatabaseManager; DatabaseManager().reseed()"
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
import time
import urllib.robotparser
from dataclasses import dataclass, fields
from datetime import date
from pathlib import Path
from typing import Optional

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://gidstats.com"
RANKING_URL = f"{BASE_URL}/ranking/ufc/"
USER_AGENT = "FightIQDataCollector/1.0 (+educational portfolio project; respects robots.txt)"
DEFAULT_DELAY_SECONDS = 1.5
OUTPUT_CSV = Path(__file__).resolve().parent.parent / "assets" / "data" / "fighters_seed.csv"

CSV_FIELDS = [
    "fighter_id", "name", "nickname", "nationality", "weight_class",
    "height_cm", "reach_cm", "stance", "birth_date",
    "wins", "losses", "draws", "no_contests",
    "wins_ko", "wins_sub", "wins_dec",
    "slpm", "str_acc_pct", "sapm", "str_def_pct",
    "td_avg", "td_acc_pct", "td_def_pct", "sub_avg", "avg_fight_time",
    "image_url", "ranking", "source", "source_url", "last_updated",
]


@dataclass
class ScrapedFighter:
    name: str
    source_url: str
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


# --------------------------------------------------------------------------
# Etiqueta de scraping
# --------------------------------------------------------------------------
def check_robots_allowed(paths: list[str]) -> bool:
    """Verifica no robots.txt do site se os caminhos usados são permitidos."""
    parser = urllib.robotparser.RobotFileParser()
    parser.set_url(f"{BASE_URL}/robots.txt")
    try:
        parser.read()
    except Exception as exc:
        print(f"⚠ Não foi possível ler robots.txt ({exc}). Abortando por precaução.")
        return False

    all_allowed = True
    for path in paths:
        allowed = parser.can_fetch(USER_AGENT, path)
        status = "permitido" if allowed else "NÃO permitido"
        print(f"  robots.txt: {path} -> {status}")
        all_allowed = all_allowed and allowed
    return all_allowed


# --------------------------------------------------------------------------
# Coleta da lista de lutadores (via página de rankings)
# --------------------------------------------------------------------------
def fetch_fighter_urls(session: requests.Session) -> list[str]:
    response = session.get(RANKING_URL, timeout=15)
    response.raise_for_status()
    urls = sorted(set(re.findall(r'href="(/fighters/[^"]+\.html)"', response.text)))
    return [BASE_URL + path for path in urls]


# --------------------------------------------------------------------------
# Parsing de uma página individual de lutador
# --------------------------------------------------------------------------
def _search(pattern: str, text: str, group: int = 1, flags=re.IGNORECASE) -> Optional[str]:
    match = re.search(pattern, text, flags)
    return match.group(group).strip() if match else None


def _to_float(value: Optional[str]) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value.replace(",", "."))
    except ValueError:
        return None


def _to_int(value: Optional[str]) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(float(value))
    except ValueError:
        return None


def parse_fighter_page(html: str, url: str) -> Optional[ScrapedFighter]:
    """
    Extrai os campos reais de uma página de lutador do GIDStats.

    Todos os padrões abaixo são tolerantes (aceitam variações de
    rótulo/pontuação) mas nunca "adivinham": se o padrão não casar, o
    campo correspondente fica None.
    """
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text("\n", strip=True)

    name_tag = soup.find(["h1", "h2"])
    name = name_tag.get_text(strip=True) if name_tag else _search(r"^(.*)$", text)
    if not name:
        return None

    height_cm = _to_float(_search(r"(\d+(?:\.\d+)?)\s*cm", text))
    reach_cm = _to_float(_search(r"reach[^\n]*?(\d+(?:\.\d+)?)\s*cm", text))
    weight_class = _search(r"\n(Heavyweight|Light [Hh]eavyweight|Middleweight|Welterweight|"
                            r"Lightweight|Featherweight|Bantamweight|Flyweight|"
                            r"Women'?s [A-Za-z]+weight)\n", text)
    stance = _search(r"stance[:\s]+([A-Za-z\-]+)", text)
    nationality = _search(r"country[:\s]+([A-Za-z .]+)", text)

    dob_match = _search(r"(\d{1,2}[./]\d{1,2}[./]\d{2,4})", text)
    birth_date = None
    if dob_match:
        for fmt_sep in ("/", "."):
            parts = dob_match.split(fmt_sep)
            if len(parts) == 3:
                try:
                    d, m, y = parts
                    y = ("20" + y) if len(y) == 2 else y
                    birth_date = date(int(y), int(m), int(d)).isoformat()
                except ValueError:
                    pass
                break

    record_match = re.search(r"(\d+)\s*-\s*(\d+)\s*-\s*(\d+)", text)
    wins = _to_int(record_match.group(1)) if record_match else None
    losses = _to_int(record_match.group(2)) if record_match else None
    draws = _to_int(record_match.group(3)) if record_match else None

    wins_ko = _to_int(_search(r"KO/TKO[:\s]+(\d+)", text))
    wins_sub = _to_int(_search(r"Sub(?:mission)?[:\s]+(\d+)", text))
    wins_dec = _to_int(_search(r"Dec(?:ision)?[:\s]+(\d+)", text))

    slpm = _to_float(_search(r"strikes? landed[^0-9]{0,25}(\d+(?:\.\d+)?)", text))
    sapm = _to_float(_search(r"strikes? absorbed[^0-9]{0,25}(\d+(?:\.\d+)?)", text))
    str_acc = _to_float(_search(r"strike accuracy[:\s]+(\d+(?:\.\d+)?)\s*%", text))
    str_def = _to_float(_search(r"strikes? defen[cs]e[:\s]+(\d+(?:\.\d+)?)\s*%", text))

    td_avg = _to_float(_search(r"Takedowns? per (?:bout|fight)[:\s]+(\d+(?:\.\d+)?)", text))
    td_acc = _to_float(_search(r"Takedown success[:\s]+(\d+(?:\.\d+)?)\s*%", text))
    td_def = _to_float(_search(r"Takedown [Dd]efen[cs]e[:\s]+(\d+(?:\.\d+)?)\s*%", text))
    sub_avg = _to_float(_search(r"[Ss]ubmission attempts[^\n]*?min[:\s]*(\d+(?:\.\d+)?)", text))
    avg_fight_time = _search(r"[Aa]verage fight time[:\s]+(\d{1,2}:\d{2})", text)

    return ScrapedFighter(
        name=name,
        source_url=url,
        nationality=nationality,
        weight_class=weight_class,
        height_cm=height_cm,
        reach_cm=reach_cm,
        stance=stance,
        birth_date=birth_date,
        wins=wins, losses=losses, draws=draws,
        wins_ko=wins_ko, wins_sub=wins_sub, wins_dec=wins_dec,
        slpm=slpm, str_acc_pct=str_acc, sapm=sapm, str_def_pct=str_def,
        td_avg=td_avg, td_acc_pct=td_acc, td_def_pct=td_def, sub_avg=sub_avg,
        avg_fight_time=avg_fight_time,
    )


# --------------------------------------------------------------------------
# CSV
# --------------------------------------------------------------------------
def write_csv(fighters: list[ScrapedFighter], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    today = date.today().isoformat()

    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for i, fighter in enumerate(fighters, start=1):
            row = {f.name: getattr(fighter, f.name, None) for f in fields(ScrapedFighter)}
            row["fighter_id"] = i
            row["image_url"] = None
            row["ranking"] = None
            row["source"] = "GIDStats.com"
            row["last_updated"] = today
            writer.writerow({k: (row.get(k) if row.get(k) is not None else "") for k in CSV_FIELDS})

    print(f"\n✅ {len(fighters)} lutadores gravados em {output_path}")


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------
def main() -> int:
    parser = argparse.ArgumentParser(description="Coletor de dados reais de lutadores (GIDStats.com)")
    parser.add_argument("--limit", type=int, default=None, help="Limita o número de lutadores coletados")
    parser.add_argument("--delay", type=float, default=DEFAULT_DELAY_SECONDS,
                         help="Segundos de espera entre requisições (padrão: 1.5)")
    parser.add_argument("--output", type=Path, default=OUTPUT_CSV, help="Caminho do CSV de saída")
    parser.add_argument("--inspect", type=str, default=None,
                         help="Modo debug: mostra o texto extraído de um único lutador (slug, ex.: jon_jones)")
    args = parser.parse_args()

    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})

    if args.inspect:
        url = f"{BASE_URL}/fighters/{args.inspect}.html"
        print(f"Buscando {url} ...")
        response = session.get(url, timeout=15)
        response.raise_for_status()
        fighter = parse_fighter_page(response.text, url)
        print("\n--- Campos extraídos ---")
        print(fighter)
        return 0

    print("Verificando robots.txt do GIDStats.com...")
    if not check_robots_allowed(["/ranking/ufc/", "/fighters/jon_jones.html"]):
        print("\n❌ O robots.txt não permite a coleta nesses caminhos. Abortando.")
        return 1

    print(f"\nBuscando lista de lutadores em {RANKING_URL} ...")
    fighter_urls = fetch_fighter_urls(session)
    if args.limit:
        fighter_urls = fighter_urls[: args.limit]
    print(f"Encontrados {len(fighter_urls)} lutadores únicos para coletar.\n")

    results: list[ScrapedFighter] = []
    for i, url in enumerate(fighter_urls, start=1):
        try:
            response = session.get(url, timeout=15)
            response.raise_for_status()
            fighter = parse_fighter_page(response.text, url)
            if fighter:
                results.append(fighter)
                print(f"[{i}/{len(fighter_urls)}] OK: {fighter.name}")
            else:
                print(f"[{i}/{len(fighter_urls)}] ⚠ Não foi possível extrair dados de {url}")
        except requests.RequestException as exc:
            print(f"[{i}/{len(fighter_urls)}] ❌ Erro ao buscar {url}: {exc}")
        time.sleep(args.delay)

    write_csv(results, args.output)
    print("\nPróximo passo: rode\n"
          "    python -c \"from database import DatabaseManager; DatabaseManager().reseed()\"\n"
          "para carregar esses dados no banco do FightIQ.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
