"""
scripts/scrape_gidstats.py
--------------------------
Utilitário de coleta de dados em escala para o FightIQ.

v1.1 — revisado após auditoria de qualidade de dados. Principais
mudanças em relação à v1.0 (ver PR/changelog no README):
    - A categoria de peso e o ranking agora vêm da página de rankings
      (fonte confiável, já estruturada por categoria), em vez de serem
      re-extraídos com regex da página individual do lutador.
    - A data de nascimento só é aceita se vier ancorada a um rótulo
      real (Born/DOB/Date of birth) — nunca mais pega "a primeira data
      solta que aparecer na página" (causa raiz do bug de idade "-1").
    - Altura agora é ancorada ao rótulo "Height" (antes pegava qualquer
      número seguido de "cm" na página, podendo roubar o valor do
      alcance).
    - Vitórias por finalização/decisão e no-contests agora aceitam
      forma plural e a anotação "(N NC)" no cartel.
    - Todo registro passa por data_quality.sanitize_fighter_dict()
      antes de ser gravado no CSV — valores fisicamente implausíveis
      (idade negativa, altura de 30cm, percentual de 140%, etc.) são
      descartados (viram vazio) em vez de gravados.

Este script continua não inventando nenhum dado: campos que não batem
com nenhum padrão, ou que falham na validação de sanidade, ficam vazios
— nunca estimados.

IMPORTANTE — por que isso não roda dentro do chat com o Claude:
O ambiente onde o FightIQ foi desenvolvido e testado não tem acesso de
rede a gidstats.com (só a domínios de pacotes Python, como pypi.org).
Rode este script na SUA máquina, que tem acesso normal à internet.

Uso:
    python scripts/scrape_gidstats.py                    # roda tudo
    python scripts/scrape_gidstats.py --limit 20          # só os 20 primeiros
    python scripts/scrape_gidstats.py --delay 2.0         # mais devagar
    python scripts/scrape_gidstats.py --inspect jon_jones # debug de 1 página

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

# Garante que "import data_quality" funcione mesmo rodando o script
# de dentro da pasta scripts/ (adiciona a raiz do projeto ao sys.path).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from data_quality import normalize_weight_class, sanitize_fighter_dict, describe_sanitization  # noqa: E402

BASE_URL = "https://gidstats.com"
RANKING_URL = f"{BASE_URL}/ranking/ufc/"
USER_AGENT = "FightIQDataCollector/1.1 (+educational portfolio project; respects robots.txt)"
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

# Ordem em que as categorias costumam aparecer em páginas de rankings.
# Usado tanto para achar os cabeçalhos de seção na página de rankings
# quanto para reconhecer a categoria dentro do texto da página do lutador
# (como fallback, caso a categoria não tenha sido resolvida via rankings).
WEIGHT_CLASS_ORDER = [
    "Women's Strawweight", "Women's Flyweight", "Women's Bantamweight",
    "Women's Featherweight", "Flyweight", "Bantamweight", "Featherweight",
    "Lightweight", "Welterweight", "Middleweight", "Light Heavyweight",
    "Heavyweight", "Pound-for-Pound", "Women's Pound-for-Pound",
]


@dataclass
class RankingEntry:
    """Uma entrada da página de rankings: nome, categoria e posição."""
    name: str
    weight_class: str
    rank: int


@dataclass
class ScrapedFighter:
    name: str
    source_url: str
    nickname: Optional[str] = None
    nationality: Optional[str] = None
    weight_class: Optional[str] = None
    ranking: Optional[str] = None
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
# Coleta da página de rankings (fonte confiável de categoria + posição)
# --------------------------------------------------------------------------
def fetch_ranking_entries(session: requests.Session) -> dict[str, RankingEntry]:
    """
    Lê a página de rankings e devolve um dicionário {url: RankingEntry}.

    Estratégia: percorre o HTML bruto em ordem de aparição, alternando
    entre "encontrei um cabeçalho de categoria" e "encontrei um link de
    lutador". Cada link é associado à categoria do cabeçalho mais
    recente visto antes dele, com a posição (rank) sendo a ordem dentro
    daquela seção. Isso evita ter que adivinhar a categoria a partir da
    página individual do lutador — usamos a estrutura que o próprio
    site já usa para organizar os rankings.

    Heurística baseada em posição textual: como não temos acesso à
    árvore DOM real do site neste ambiente de desenvolvimento, isso foi
    validado contra uma reconstrução do formato observado, não contra o
    HTML ao vivo. Se a extração vier vazia ou estranha, rode com
    --inspect e me avise para ajustar os padrões.
    """
    response = session.get(RANKING_URL, timeout=15)
    response.raise_for_status()
    html = response.text

    heading_pattern = re.compile(
        r">\s*(" + "|".join(re.escape(wc) for wc in WEIGHT_CLASS_ORDER) + r")\s*<",
        re.IGNORECASE,
    )
    link_pattern = re.compile(
        r'href="(/fighters/[^"]+\.html)"[^>]*>\s*([^<]{2,60}?)\s*<',
        re.IGNORECASE,
    )

    events = []
    for m in heading_pattern.finditer(html):
        events.append((m.start(), "heading", m.group(1)))
    for m in link_pattern.finditer(html):
        events.append((m.start(), "link", (m.group(1), m.group(2))))
    events.sort(key=lambda e: e[0])

    entries: dict[str, RankingEntry] = {}
    current_class: Optional[str] = None
    rank_counter = 0

    for _, kind, payload in events:
        if kind == "heading":
            normalized = normalize_weight_class(payload)
            # "Pound-for-Pound" não é uma categoria de peso de verdade —
            # ignoramos como categoria (fica None) para não sobrescrever
            # a categoria real do lutador com isso.
            current_class = normalized if normalized and "pound" not in normalized.lower() else None
            rank_counter = 0
            continue

        if current_class is None:
            continue
        url_path, name = payload
        full_url = BASE_URL + url_path
        rank_counter += 1
        if full_url not in entries:  # primeira aparição = ranking "principal" do lutador
            entries[full_url] = RankingEntry(name=name.strip(), weight_class=current_class, rank=rank_counter)

    return entries


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


def _parse_anchored_date(text: str) -> Optional[str]:
    """
    Extrai a data de nascimento SOMENTE se estiver ancorada a um rótulo
    real (Born / DOB / Date of birth). Correção direta do bug de idade
    "-1": a versão anterior pegava a primeira data solta na página
    (podendo ser data de evento, não de nascimento). Se não achar o
    rótulo, devolve None em vez de arriscar um "melhor palpite".
    """
    match = re.search(
        r"(?:date of birth|born|dob)[:\s]*"
        r"(\d{1,2})[./](\d{1,2})[./](\d{2,4})",
        text, re.IGNORECASE,
    )
    if not match:
        return None
    d, m, y = match.groups()
    y = ("19" + y) if len(y) == 2 and int(y) > 30 else (("20" + y) if len(y) == 2 else y)
    try:
        return date(int(y), int(m), int(d)).isoformat()
    except ValueError:
        return None


def parse_fighter_page(html: str, url: str,
                        ranking_hint: Optional[RankingEntry] = None) -> Optional[ScrapedFighter]:
    """
    Extrai os campos reais de uma página de lutador do GIDStats.

    `ranking_hint`, quando fornecido (vindo de fetch_ranking_entries),
    tem prioridade sobre qualquer extração de categoria feita aqui —
    a página de rankings é uma fonte mais confiável para esse campo
    específico do que tentar re-extrair da página individual.
    """
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text("\n", strip=True)

    name_tag = soup.find(["h1", "h2"])
    name = name_tag.get_text(strip=True) if name_tag else (ranking_hint.name if ranking_hint else None)
    if not name:
        return None

    height_cm = _to_float(_search(r"height[^\n]*?(\d+(?:\.\d+)?)\s*cm", text))
    if height_cm is None:
        # fallback: altura em metros (ex.: "1.93 m")
        h_m = _to_float(_search(r"height[^\n]*?(\d\.\d{1,2})\s*m\b", text))
        height_cm = round(h_m * 100, 1) if h_m else None

    reach_cm = _to_float(_search(r"reach[^\n]*?(\d+(?:\.\d+)?)\s*cm", text))
    if reach_cm is None:
        r_m = _to_float(_search(r"reach[^\n]*?(\d\.\d{1,2})\s*m\b", text))
        reach_cm = round(r_m * 100, 1) if r_m else None

    # Categoria: prioridade absoluta para o dado vindo da página de
    # rankings (mais confiável). Só tenta extrair da página individual
    # se não veio nenhuma dica de fora.
    if ranking_hint:
        weight_class = ranking_hint.weight_class
        ranking = f"#{ranking_hint.rank} {ranking_hint.weight_class}"
    else:
        raw_class = _search(
            r"(" + "|".join(re.escape(wc) for wc in WEIGHT_CLASS_ORDER if "pound" not in wc.lower()) + r")",
            text,
        )
        weight_class = normalize_weight_class(raw_class)
        ranking = None

    stance = _search(r"stance[:\s]+([A-Za-z\-]+)", text)
    nationality = _search(r"country[:\s]+([A-Za-z .]+)", text)
    birth_date = _parse_anchored_date(text)

    record_match = re.search(r"(\d+)\s*-\s*(\d+)\s*-\s*(\d+)", text)
    wins = _to_int(record_match.group(1)) if record_match else None
    losses = _to_int(record_match.group(2)) if record_match else None
    draws = _to_int(record_match.group(3)) if record_match else None

    # "(N NC)" só aparece anotado no cartel quando existe pelo menos um
    # no-contest — convenção comum em sites de estatísticas de MMA.
    # Na ausência dessa anotação, assumimos 0 (não None): é uma leitura
    # direta da convenção de formatação da fonte, não uma estimativa.
    nc_match = re.search(r"\(\s*(\d+)\s*NC\s*\)", text, re.IGNORECASE)
    no_contests = _to_int(nc_match.group(1)) if nc_match else 0

    wins_ko = _to_int(_search(r"KO/TKOs?[:\s]+(\d+)", text))
    wins_sub = _to_int(_search(r"Sub(?:mission)?s?[:\s]+(\d+)", text))
    wins_dec = _to_int(_search(r"Dec(?:ision)?s?[:\s]+(\d+)", text))

    slpm = _to_float(_search(r"strikes? landed[^0-9]{0,25}(\d+(?:\.\d+)?)", text))
    sapm = _to_float(_search(r"strikes? absorbed[^0-9]{0,25}(\d+(?:\.\d+)?)", text))
    str_acc = _to_float(_search(r"strike accuracy[:\s]+(\d+(?:\.\d+)?)\s*%", text))
    str_def = _to_float(_search(r"strikes? defen[cs]e[:\s]+(\d+(?:\.\d+)?)\s*%", text))

    td_avg = _to_float(_search(r"Takedowns? per (?:bout|fight)[:\s]+(\d+(?:\.\d+)?)", text))
    td_acc = _to_float(_search(r"(?:Takedown success|TD Acc(?:uracy)?)[:\s]+(\d+(?:\.\d+)?)\s*%", text))
    td_def = _to_float(_search(r"Takedown [Dd]efen[cs]e[:\s]+(\d+(?:\.\d+)?)\s*%", text))
    sub_avg = _to_float(_search(r"[Ss]ubmission attempts[^\n]*?min[:\s]*(\d+(?:\.\d+)?)", text))
    avg_fight_time = _search(r"[Aa]verage fight time[:\s]+(\d{1,2}:\d{2})", text)

    return ScrapedFighter(
        name=name, source_url=url,
        nationality=nationality, weight_class=weight_class, ranking=ranking,
        height_cm=height_cm, reach_cm=reach_cm, stance=stance, birth_date=birth_date,
        wins=wins, losses=losses, draws=draws, no_contests=no_contests,
        wins_ko=wins_ko, wins_sub=wins_sub, wins_dec=wins_dec,
        slpm=slpm, str_acc_pct=str_acc, sapm=sapm, str_def_pct=str_def,
        td_avg=td_avg, td_acc_pct=td_acc, td_def_pct=td_def, sub_avg=sub_avg,
        avg_fight_time=avg_fight_time,
    )


# --------------------------------------------------------------------------
# CSV (com validação de sanidade antes de gravar)
# --------------------------------------------------------------------------
def write_csv(fighters: list[ScrapedFighter], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    today = date.today().isoformat()
    total_flags = 0

    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for i, fighter in enumerate(fighters, start=1):
            raw_row = {f.name: getattr(fighter, f.name, None) for f in fields(ScrapedFighter)}
            clean_row = sanitize_fighter_dict(raw_row)

            descriptions = describe_sanitization(raw_row, clean_row)
            if descriptions:
                total_flags += len(descriptions)
                print(f"  ⚠ {fighter.name}: {'; '.join(descriptions)}")

            clean_row["fighter_id"] = i
            clean_row["image_url"] = None
            clean_row["source"] = "GIDStats.com"
            clean_row["last_updated"] = today
            writer.writerow({k: (clean_row.get(k) if clean_row.get(k) not in (None, "") else "")
                              for k in CSV_FIELDS})

    print(f"\n✅ {len(fighters)} lutadores gravados em {output_path}")
    if total_flags:
        print(f"⚠ {total_flags} campo(s), no total, foram descartados por falharem na validação de sanidade "
              f"(ver data_quality.py) — melhor vazio do que errado.")


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
                         help="Modo debug: mostra os campos extraídos de um único lutador (slug, ex.: jon_jones)")
    args = parser.parse_args()

    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})

    if args.inspect:
        url = f"{BASE_URL}/fighters/{args.inspect}.html"
        print(f"Buscando {url} ...")
        response = session.get(url, timeout=15)
        response.raise_for_status()
        fighter = parse_fighter_page(response.text, url)
        print("\n--- Campos extraídos (antes da validação de sanidade) ---")
        print(fighter)
        if fighter:
            raw_row = {f.name: getattr(fighter, f.name, None) for f in fields(ScrapedFighter)}
            clean_row = sanitize_fighter_dict(raw_row)
            descriptions = describe_sanitization(raw_row, clean_row)
            print("\n--- Após validação de sanidade ---")
            print(clean_row)
            if descriptions:
                print(f"\n⚠ Ajustes da validação: {'; '.join(descriptions)}")
        return 0

    print("Verificando robots.txt do GIDStats.com...")
    if not check_robots_allowed(["/ranking/ufc/", "/fighters/jon_jones.html"]):
        print("\n❌ O robots.txt não permite a coleta nesses caminhos. Abortando.")
        return 1

    print(f"\nBuscando página de rankings em {RANKING_URL} ...")
    ranking_entries = fetch_ranking_entries(session)
    fighter_urls = list(ranking_entries.keys())
    if args.limit:
        fighter_urls = fighter_urls[: args.limit]
    print(f"Encontrados {len(fighter_urls)} lutadores únicos nos rankings.\n")

    results: list[ScrapedFighter] = []
    for i, url in enumerate(fighter_urls, start=1):
        try:
            response = session.get(url, timeout=15)
            response.raise_for_status()
            fighter = parse_fighter_page(response.text, url, ranking_hint=ranking_entries.get(url))
            if fighter:
                results.append(fighter)
                print(f"[{i}/{len(fighter_urls)}] OK: {fighter.name} ({fighter.weight_class or 'categoria N/D'})")
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
