"""
scripts/scrape_gidstats.py
--------------------------
Utilitário de coleta de dados em escala para o FightIQ.

v1.2 — revisado após auditoria com dados reais da página da Miesha Tate
(https://gidstats.com/fighters/miesha_tate.html). Principais mudanças:

    - Extração de altura, alcance, idade e nacionalidade agora usa
      NAVEGAÇÃO ESTRUTURAL na árvore do BeautifulSoup (localiza o nó de
      texto do rótulo exato, ex. "Height", e olha os próximos nós de
      texto NA ÁRVORE, não a distância em caracteres no texto achatado).
      Isso resolve a causa raiz encontrada na auditoria: rótulo e valor
      costumam estar em elementos HTML diferentes/irmãos, então um
      regex que exige "mesma linha" nunca batia. Regex continua sendo
      usado, mas só dentro dessa janela já localizada estruturalmente
      — nunca mais como "ache o primeiro número na página inteira".
    - A idade agora é capturada DIRETO do campo "Age NN" que o site
      publica (Fighter.age_reported), em vez de depender só de uma data
      de nascimento — a auditoria confirmou que o GIDStats não publica
      data de nascimento em formato numérico; "Born" no site é o LOCAL
      de nascimento, não a data.
    - Nacionalidade agora é extraída da estrutura "Born <Cidade>, <País>"
      (a única fonte confiável de país encontrada na página), em vez de
      um rótulo "Country:" que nunca existiu de fato.
    - fighter_id agora é o slug estável da URL (ex. "miesha_tate"), não
      mais um número sequencial por ordem de coleta.

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
    python scripts/scrape_gidstats.py --inspect miesha_tate # debug de 1 página

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
from bs4 import BeautifulSoup, NavigableString

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from data_quality import normalize_weight_class, sanitize_fighter_dict, describe_sanitization  # noqa: E402

BASE_URL = "https://gidstats.com"
RANKING_URL = f"{BASE_URL}/ranking/ufc/"
USER_AGENT = "FightIQDataCollector/1.2 (+educational portfolio project; respects robots.txt)"
DEFAULT_DELAY_SECONDS = 1.5
MIN_EXPECTED_FIGHTERS = 150  # abaixo disso, algo está errado na extração — não é resultado normal
OUTPUT_CSV = Path(__file__).resolve().parent.parent / "assets" / "data" / "fighters_seed.csv"

CSV_FIELDS = [
    "fighter_id", "name", "nickname", "nationality", "weight_class",
    "height_cm", "reach_cm", "stance", "birth_date", "age_reported",
    "wins", "losses", "draws", "no_contests",
    "wins_ko", "wins_sub", "wins_dec",
    "slpm", "str_acc_pct", "sapm", "str_def_pct",
    "td_avg", "td_acc_pct", "td_def_pct", "sub_avg", "avg_fight_time",
    "image_url", "ranking", "source", "source_url", "last_updated",
]

WEIGHT_CLASS_ORDER = [
    "Women's Strawweight", "Women's Flyweight", "Women's Bantamweight",
    "Women's Featherweight", "Flyweight", "Bantamweight", "Featherweight",
    "Lightweight", "Welterweight", "Middleweight", "Light Heavyweight",
    "Heavyweight", "Pound-for-Pound", "Women's Pound-for-Pound",
]


@dataclass
class RankingEntry:
    name: str
    weight_class: str
    rank: int


@dataclass
class ScrapedFighter:
    fighter_id: str
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
    age_reported: Optional[int] = None
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


def slug_from_url(url: str) -> str:
    """Extrai o slug estável de uma URL de lutador (ex.: 'miesha_tate')."""
    return url.rstrip("/").split("/")[-1].removesuffix(".html")


# --------------------------------------------------------------------------
# Etiqueta de scraping
# --------------------------------------------------------------------------
def check_robots_allowed(paths: list[str]) -> bool:
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
def fetch_ranking_entries(session: requests.Session, verbose: bool = False) -> dict[str, RankingEntry]:
    """
    Lê a página de rankings e devolve um dicionário {url: RankingEntry}.

    Com `verbose=True`, imprime contadores em cada etapa do pipeline
    (bytes baixados, cabeçalhos de categoria encontrados, links brutos
    para /fighters/, links válidos depois do filtro de categoria) —
    existe especificamente para que uma regressão como "0 lutadores
    encontrados" nunca mais precise ser diagnosticada por tentativa e
    erro: rode com --verbose e a saída aponta exatamente em qual etapa
    a contagem despenca.
    """
    response = session.get(RANKING_URL, timeout=15)
    if verbose:
        print(f"  [diagnóstico] HTTP status: {response.status_code}")
        print(f"  [diagnóstico] Bytes recebidos: {len(response.content)}")
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")

    if verbose:
        looks_like_ranking_page = "ranking" in response.text.lower() and "fighters" in response.text.lower()
        print(f"  [diagnóstico] Conteúdo parece a página de rankings? {looks_like_ranking_page}")
        raw_fighter_links = len(re.findall(r'href="(/fighters/[^"]+\.html)"', response.text))
        print(f"  [diagnóstico] Links brutos para /fighters/*.html no HTML (antes de qualquer filtro): "
              f"{raw_fighter_links}")

    # Remove o dropdown de filtro — fonte CONFIRMADA de contaminação
    # (ver docstring acima). IMPORTANTE: não remover <nav> aqui — uma
    # versão anterior removia <nav> "por precaução", sem evidência real,
    # e isso apagava a listagem verdadeira de lutadores sempre que ela
    # estava dentro de uma tag <nav> (comum e semanticamente correto
    # para uma lista de rankings) — causando "0 lutadores encontrados".
    # Só remova elementos daqui com evidência concreta de contaminação,
    # nunca por suposição.
    for tag in soup.select("select, option"):
        tag.decompose()

    heading_re = re.compile(
        r"^\s*(" + "|".join(re.escape(wc) for wc in sorted(WEIGHT_CLASS_ORDER, key=len, reverse=True)) + r")\s*$",
        re.IGNORECASE,
    )

    entries: dict[str, RankingEntry] = {}
    current_class: Optional[str] = None
    rank_counter = 0
    headings_matched = 0
    fighter_links_seen = 0

    # soup.descendants percorre TODOS os nós (tags E textos) na ordem real
    # do documento — diferente da versão anterior, que checava se o nó de
    # TEXTO tinha o <a> como pai DIRETO. Isso quebrava sempre que o nome do
    # lutador vinha envolto em <span> aninhados dentro do <a> (confirmado
    # como a estrutura real da página — o texto do link vem fragmentado em
    # spans de primeiro nome / rank / nome completo). Agora tratamos cada
    # tag <a> como uma unidade e pegamos todo o texto dela com get_text(),
    # não importando quantos elementos estejam aninhados dentro.
    for node in soup.descendants:
        if isinstance(node, NavigableString):
            text = str(node).strip()
            if not text:
                continue
            heading_match = heading_re.match(text)
            if heading_match:
                headings_matched += 1
                normalized = normalize_weight_class(heading_match.group(1))
                current_class = normalized if normalized and "pound" not in normalized.lower() else None
                rank_counter = 0
            continue

        if getattr(node, "name", None) != "a":
            continue
        href = node.get("href", "")
        if not (href.startswith("/fighters/") and href.endswith(".html")):
            continue
        fighter_links_seen += 1
        if current_class is None:
            continue

        full_url = BASE_URL + href
        if full_url in entries:
            continue
        name = re.sub(r"\s+", " ", node.get_text(" ", strip=True)).strip()
        rank_counter += 1
        entries[full_url] = RankingEntry(name=name, weight_class=current_class, rank=rank_counter)

    if verbose:
        print(f"  [diagnóstico] Cabeçalhos de categoria reconhecidos (heading_re bateu): {headings_matched}")
        print(f"  [diagnóstico] Tags <a href=\"/fighters/...\"> encontradas na árvore: {fighter_links_seen}")
        print(f"  [diagnóstico] Lutadores únicos com categoria válida associada: {len(entries)}")

    return entries


# --------------------------------------------------------------------------
# Navegação ESTRUTURAL (BeautifulSoup) para localizar rótulo -> valor
# --------------------------------------------------------------------------
def _find_label_context(soup: BeautifulSoup, label: str, window: int = 6) -> Optional[str]:
    """
    Localiza, na ÁRVORE do documento (não no texto achatado), o nó cujo
    texto é exatamente `label` (ignorando espaços/case), e devolve os
    próximos `window` nós de texto seguintes NA ORDEM DO DOCUMENTO,
    concatenados.

    Essa é a técnica estrutural pedida: em vez de assumir que rótulo e
    valor estão na mesma linha de um texto já achatado (o que causava o
    bug de altura/alcance ausentes), seguimos a ordem real dos nós de
    texto do HTML — o valor de "Height" está, estruturalmente, sempre
    logo depois do nó "Height", esteja ele no mesmo elemento ou não.

    Regex ainda é usado, mas só para extrair o número de dentro dessa
    janela já localizada pela estrutura — não mais como busca livre na
    página inteira.
    """
    label_re = re.compile(rf"^\s*{re.escape(label)}\s*$", re.IGNORECASE)
    label_node = soup.find(string=label_re)
    if label_node is None:
        return None

    collected = []
    node = label_node
    for _ in range(window):
        node = node.find_next(string=True)
        if node is None:
            break
        text = str(node).strip()
        if text:
            collected.append(text)

    return " ".join(collected) if collected else None


def _extract_cm(context: Optional[str]) -> Optional[float]:
    """Extrai o valor em cm de uma janela de texto já localizada estruturalmente."""
    if not context:
        return None
    match = re.search(r"(\d+(?:\.\d+)?)\s*cm", context, re.IGNORECASE)
    if match:
        return float(match.group(1))
    # Fallback: valor em metros (ex.: "1.93 m")
    match_m = re.search(r"(\d\.\d{1,2})\s*m\b", context, re.IGNORECASE)
    return round(float(match_m.group(1)) * 100, 1) if match_m else None


def extract_height_cm(soup: BeautifulSoup) -> Optional[float]:
    return _extract_cm(_find_label_context(soup, "Height"))


def extract_reach_cm(soup: BeautifulSoup) -> Optional[float]:
    # Busca a string EXATA "Reach" (não "Leg Reach") — find(string=regex)
    # com "^...$" já garante isso, ao contrário de um regex de texto livre.
    return _extract_cm(_find_label_context(soup, "Reach"))


def extract_age_reported(soup: BeautifulSoup, full_text: str) -> Optional[int]:
    """
    Extrai a idade diretamente do campo "Age NN" do GIDStats (não deriva
    de data de nascimento — o site não publica uma). Tenta localizar
    estruturalmente primeiro; cai para regex no texto completo como
    fallback, já que "Age" às vezes aparece colado a outro texto no
    mesmo nó (ex.: "(W-L-D) Age 39") em vez de isolado num nó próprio.
    """
    context = _find_label_context(soup, "Age")
    if context:
        match = re.search(r"(\d{1,3})", context)
        if match:
            return int(match.group(1))
    # Fallback: regex no texto completo (rótulo pode não estar isolado num nó)
    match = re.search(r"\bAge\s+(\d{1,3})\b", full_text, re.IGNORECASE)
    return int(match.group(1)) if match else None


def extract_nationality(soup: BeautifulSoup) -> Optional[str]:
    """
    Extrai a nacionalidade de forma estrutural.

    v1.3 — reescrito após confirmar, com o texto real da página do Alex
    Pereira, DOIS bugs na versão anterior (que tentava extrair o país
    do campo "Born <Cidade>, <País>"):
        1. Nomes de cidade acentuados (ex.: "São Paulo") quebravam a
           classe de caracteres [A-Za-z .] do regex, que não inclui
           letras acentuadas — o resultado ficava truncado no primeiro
           caractere não-ASCII (ex.: "S" em vez de "Brazil").
        2. O campo "Born" tem número de vírgulas inconsistente entre
           lutadores: "Born Tacoma, United States" (1 vírgula) vs "Born
           São Bernardo do Campo, São Paulo, Brazil" (2 vírgulas, com
           estado no meio) — pegar "o texto depois da primeira vírgula"
           pegava o ESTADO, não o país, no segundo caso.

    A fonte mais confiável observada nas duas páginas reais analisadas
    é um token de país solto que aparece IMEDIATAMENTE ANTES do campo
    "Style" (estilo de luta) — ex.: "... USA · Style Grappling ..." e
    "... Brazil · Style Kickboxing ...". Localizamos esse token
    estruturalmente (nó de texto anterior ao rótulo "Style" na árvore),
    em vez de tentar decompor o campo "Born".
    """
    style_node = soup.find(string=re.compile(r"^\s*Style\b", re.IGNORECASE))
    if style_node is None:
        return None

    # Pula nós vazios/só-espaço (comuns entre tags em HTML formatado)
    # até achar o texto de verdade anterior ao rótulo "Style".
    node = style_node
    for _ in range(5):
        node = node.find_previous(string=True)
        if node is None:
            return None
        text = str(node).strip()
        if text:
            break
    else:
        return None
    # Sanidade básica: nome de país plausível (sem dígitos, tamanho razoável).
    # Suporta acentos (não restringe a A-Za-z como a versão anterior).
    if text and len(text) <= 40 and not re.search(r"\d", text):
        return text
    return None


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


def parse_fighter_page(html: str, url: str,
                        ranking_hint: Optional[RankingEntry] = None) -> Optional[ScrapedFighter]:
    """
    Extrai os campos reais de uma página de lutador do GIDStats.

    Altura, alcance, idade e nacionalidade usam navegação estrutural
    (ver funções extract_* acima). Os demais campos (cartel, golpes,
    quedas) seguem usando regex sobre o texto achatado, já validados
    contra o texto real da página da Miesha Tate durante a auditoria.
    """
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text("\n", strip=True)

    name_tag = soup.find(["h1", "h2"])
    name = name_tag.get_text(strip=True) if name_tag else (ranking_hint.name if ranking_hint else None)
    if not name:
        return None

    fighter_id = slug_from_url(url)

    height_cm = extract_height_cm(soup)
    reach_cm = extract_reach_cm(soup)
    age_reported = extract_age_reported(soup, text)
    nationality = extract_nationality(soup)

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

    # A página não publica data de nascimento em formato numérico (só
    # local de nascimento + idade já calculada) — mas deixamos o regex
    # ancorado como tentativa honesta, caso o layout mude no futuro ou
    # outro lutador tenha uma variação de página com DOB de verdade.
    birth_date = None
    dob_match = re.search(
        r"(?:date of birth|dob)[:\s]*(\d{1,2})[./](\d{1,2})[./](\d{2,4})", text, re.IGNORECASE,
    )
    if dob_match:
        d, m, y = dob_match.groups()
        y = ("19" + y) if len(y) == 2 and int(y) > 30 else (("20" + y) if len(y) == 2 else y)
        try:
            birth_date = date(int(y), int(m), int(d)).isoformat()
        except ValueError:
            birth_date = None

    record_match = re.search(r"(\d+)\s*-\s*(\d+)\s*-\s*(\d+)", text)
    wins = _to_int(record_match.group(1)) if record_match else None
    losses = _to_int(record_match.group(2)) if record_match else None
    draws = _to_int(record_match.group(3)) if record_match else None

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
        fighter_id=fighter_id, name=name, source_url=url,
        nationality=nationality, weight_class=weight_class, ranking=ranking,
        height_cm=height_cm, reach_cm=reach_cm, stance=stance,
        birth_date=birth_date, age_reported=age_reported,
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
        for fighter in fighters:
            raw_row = {f.name: getattr(fighter, f.name, None) for f in fields(ScrapedFighter)}
            clean_row = sanitize_fighter_dict(raw_row)
            clean_row["fighter_id"] = fighter.fighter_id  # nunca sanitizar/perder o slug

            descriptions = describe_sanitization(raw_row, clean_row)
            if descriptions:
                total_flags += len(descriptions)
                print(f"  ⚠ {fighter.name}: {'; '.join(descriptions)}")

            clean_row["image_url"] = None
            clean_row["source"] = "GIDStats.com"
            clean_row["last_updated"] = today
            writer.writerow({k: (clean_row.get(k) if clean_row.get(k) not in (None, "") else "")
                              for k in CSV_FIELDS})

    print(f"\n✅ {len(fighters)} lutadores gravados em {output_path}")
    if total_flags:
        print(f"⚠ {total_flags} campo(s), no total, foram descartados/normalizados pela validação de sanidade.")


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------
def main() -> int:
    parser = argparse.ArgumentParser(description="Coletor de dados reais de lutadores (GIDStats.com)")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--delay", type=float, default=DEFAULT_DELAY_SECONDS)
    parser.add_argument("--output", type=Path, default=OUTPUT_CSV)
    parser.add_argument("--inspect", type=str, default=None,
                         help="Modo debug: mostra os 5 estágios de extração de um lutador (slug, ex.: miesha_tate)")
    parser.add_argument("--verbose", action="store_true",
                         help="Mostra contadores de diagnóstico em cada etapa da leitura da página de rankings "
                              "(HTTP status, bytes, links brutos, cabeçalhos reconhecidos, links válidos)")
    args = parser.parse_args()

    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})

    if args.inspect:
        url = f"{BASE_URL}/fighters/{args.inspect}.html"
        print(f"Buscando {url} ...")
        response = session.get(url, timeout=15)
        response.raise_for_status()
        fighter = parse_fighter_page(response.text, url)

        print("\n--- Estágio 1: valor bruto extraído (parsing) ---")
        print(fighter)

        if fighter:
            raw_row = {f.name: getattr(fighter, f.name, None) for f in fields(ScrapedFighter)}
            clean_row = sanitize_fighter_dict(raw_row)
            clean_row["fighter_id"] = fighter.fighter_id
            descriptions = describe_sanitization(raw_row, clean_row)

            print("\n--- Estágio 2: após validação de sanidade (data_quality.py) ---")
            print(clean_row)
            if descriptions:
                print(f"\n⚠ Ajustes da validação: {'; '.join(descriptions)}")

            print("\n--- Estágios 3-5 (CSV -> banco) ---")
            print("Rode 'python scripts/scrape_gidstats.py' (sem --inspect) pra gravar no CSV,")
            print("depois 'DatabaseManager().reseed()' e confira com db.get_fighter(fighter_id)")
            print(f"pra comparar com os estágios acima. fighter_id = {fighter.fighter_id!r}")
        return 0

    print("Verificando robots.txt do GIDStats.com...")
    if not check_robots_allowed(["/ranking/ufc/", "/fighters/miesha_tate.html"]):
        print("\n❌ O robots.txt não permite a coleta nesses caminhos. Abortando.")
        return 1

    print(f"\nBuscando página de rankings em {RANKING_URL} ...")
    ranking_entries = fetch_ranking_entries(session, verbose=args.verbose)
    fighter_urls = list(ranking_entries.keys())
    if args.limit:
        fighter_urls = fighter_urls[: args.limit]
    print(f"Encontrados {len(fighter_urls)} lutadores únicos nos rankings.\n")

    # Nunca gerar um CSV vazio silenciosamente: se a contagem vier
    # anormalmente baixa, para com um erro explícito em vez de seguir em
    # frente como se nada tivesse acontecido (foi exatamente isso que
    # aconteceu na regressão que gerou um fighters_seed.csv vazio).
    if not args.limit and len(fighter_urls) < MIN_EXPECTED_FIGHTERS:
        print(
            f"❌ Esperado bem mais que {MIN_EXPECTED_FIGHTERS} lutadores nos rankings, encontrado "
            f"{len(fighter_urls)}. Isso indica uma regressão na extração, não um resultado normal.\n"
            f"   Rode de novo com --verbose para ver em qual etapa a contagem cai:\n"
            f"       python scripts/scrape_gidstats.py --verbose --limit 5\n"
            f"   Nenhum arquivo CSV foi sobrescrito."
        )
        return 1

    results: list[ScrapedFighter] = []
    for i, url in enumerate(fighter_urls, start=1):
        try:
            response = session.get(url, timeout=15)
            response.raise_for_status()
            fighter = parse_fighter_page(response.text, url, ranking_hint=ranking_entries.get(url))
            if fighter:
                results.append(fighter)
                print(f"[{i}/{len(fighter_urls)}] OK: {fighter.name} "
                      f"({fighter.weight_class or 'categoria N/D'}, id={fighter.fighter_id})")
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
