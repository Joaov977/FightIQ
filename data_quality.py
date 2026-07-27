"""
data_quality.py
----------------
Regras de validação e normalização de dados do FightIQ.

Este módulo é usado em DOIS pontos do pipeline, como defesa em duas
camadas independentes:
    1. Pelo scraper (scripts/scrape_gidstats.py), logo antes de gravar
       o CSV — pega problemas na origem.
    2. Pelo banco de dados (database.py), logo antes de inserir no
       SQLite — pega problemas mesmo que o CSV tenha sido editado à
       mão ou gerado por outra fonte no futuro.

Princípio importante: nenhuma função aqui "conserta" um valor errado
adivinhando o valor certo. Elas só fazem duas coisas:
    - Descartam (viram None) valores fisicamente/logicamente
      impossíveis (ex.: altura de 30cm, idade -1, precisão de 140%).
    - Normalizam nomenclatura para um vocabulário fixo e conhecido
      (ex.: "MIDDLEWEIGHT", "middleweight" e "Middleweight" viram todos
      "Middleweight") — nunca inferem uma categoria a partir de outros
      dados, só padronizam grafias diferentes do mesmo valor.

Isso significa que, depois de passar por aqui, um campo "estranho" vira
None (exibido como "N/D" na interface) em vez de um número/tex to
errado exibido com confiança.
"""

from __future__ import annotations

from datetime import date
from typing import Optional

# --------------------------------------------------------------------------
# Faixas plausíveis (baseadas em atletas profissionais de MMA reais)
# --------------------------------------------------------------------------
MIN_HEIGHT_CM, MAX_HEIGHT_CM = 145.0, 215.0
MIN_REACH_CM, MAX_REACH_CM = 145.0, 230.0
MIN_AGE, MAX_AGE = 17, 60
MAX_PCT = 100.0
MAX_SLPM, MAX_SAPM = 15.0, 15.0
MAX_TD_AVG, MAX_SUB_AVG = 12.0, 8.0
MIN_ROUND, MAX_ROUND = 1, 5

VALID_RESULTS = {"win", "loss", "draw", "no_contest"}

# Vocabulário fixo de métodos de vitória/derrota — normalização, não inferência.
METHOD_CANONICAL = {
    "ko": "KO/TKO", "tko": "KO/TKO", "ko/tko": "KO/TKO", "technical knockout": "KO/TKO",
    "submission": "Submission", "sub": "Submission",
    "decision": "Decision", "dec": "Decision",
    "dq": "DQ", "disqualification": "DQ",
    "no contest": "No Contest", "nc": "No Contest",
    "overturned": "Overturned",
}


def normalize_method(raw: Optional[str]) -> Optional[str]:
    """Padroniza a grafia do método (ex.: 'ko', 'KO', 'Ko/Tko' -> 'KO/TKO')."""
    if not raw:
        return None
    key = raw.strip().lower()
    return METHOD_CANONICAL.get(key, raw.strip())


def sanitize_result(value: Optional[str]) -> Optional[str]:
    """Aceita só o vocabulário fixo de resultado — qualquer outra coisa vira None."""
    if not value:
        return None
    key = value.strip().lower().replace(" ", "_")
    return key if key in VALID_RESULTS else None


def sanitize_round(value) -> Optional[int]:
    """Round precisa estar entre 1 e 5 (nenhuma luta de MMA profissional tem mais que isso)."""
    if value is None or value == "":
        return None
    try:
        r = int(float(value))
    except (TypeError, ValueError):
        return None
    return r if MIN_ROUND <= r <= MAX_ROUND else None


def sanitize_fight_date(value) -> Optional[str]:
    """
    Valida a data de uma luta: precisa ser uma data real, não no futuro
    (lutas já ocorridas), e depois de 1993 (ano de fundação do UFC —
    qualquer coisa antes disso é quase certamente erro de parsing).
    """
    if not value:
        return None
    try:
        if isinstance(value, str):
            y, m, d = (int(p) for p in value.split("-"))
            parsed = date(y, m, d)
        else:
            parsed = value
    except (ValueError, TypeError):
        return None

    if parsed > date.today() or parsed.year < 1993:
        return None
    return parsed.isoformat() if isinstance(value, str) else value


def sanitize_fight_record_dict(row: dict) -> dict:
    """
    Aplica as mesmas regras de sanidade de sanitize_fighter_dict, mas
    para um registro de luta individual (vindo de qualquer provider de
    histórico). Mesmo princípio: descarta o implausível, normaliza a
    grafia, nunca adivinha.
    """
    row = dict(row)
    row["result"] = sanitize_result(row.get("result"))
    row["method"] = normalize_method(row.get("method"))
    row["round"] = sanitize_round(row.get("round"))
    row["fight_date"] = sanitize_fight_date(row.get("fight_date"))
    row["weight_class"] = normalize_weight_class(row.get("weight_class"))
    return row


# --------------------------------------------------------------------------
# Vocabulário fixo de categorias de peso (normalização, não inferência)
# --------------------------------------------------------------------------
WEIGHT_CLASS_CANONICAL = {
    "heavyweight": "Heavyweight",
    "light heavyweight": "Light Heavyweight",
    "middleweight": "Middleweight",
    "welterweight": "Welterweight",
    "lightweight": "Lightweight",
    "featherweight": "Featherweight",
    "bantamweight": "Bantamweight",
    "flyweight": "Flyweight",
    "women's strawweight": "Women's Strawweight",
    "womens strawweight": "Women's Strawweight",
    "women's flyweight": "Women's Flyweight",
    "womens flyweight": "Women's Flyweight",
    "women's bantamweight": "Women's Bantamweight",
    "womens bantamweight": "Women's Bantamweight",
    "women's featherweight": "Women's Featherweight",
    "womens featherweight": "Women's Featherweight",
    "catchweight": "Catchweight",
}


def normalize_weight_class(raw: Optional[str]) -> Optional[str]:
    """Padroniza a grafia de uma categoria de peso já identificada.

    Não tenta adivinhar a categoria a partir de outros dados — apenas
    mapeia variações de capitalização/apóstrofo para o nome canônico.
    Se o valor não estiver no dicionário, é devolvido como veio (limpo
    de espaços), em vez de ser descartado — preferimos mostrar um valor
    "não padronizado" a esconder um dado real.
    """
    if not raw:
        return None
    key = raw.strip().lower().replace("’", "'")
    return WEIGHT_CLASS_CANONICAL.get(key, raw.strip())


def sanitize_birth_date(iso_date: Optional[str]) -> Optional[str]:
    """
    Descarta datas de nascimento fisicamente implausíveis: datas no
    futuro, ou que resultariam em uma idade fora da faixa 17-60 anos.
    Esta é a correção direta do bug de "idade -1": uma data de nascimento
    capturada erroneamente (ex.: data de um evento futuro) é rejeitada
    aqui antes de chegar ao banco, mesmo que o regex de origem falhe.
    """
    if not iso_date:
        return None
    try:
        y, m, d = (int(p) for p in iso_date.split("-"))
        birth = date(y, m, d)
    except (ValueError, TypeError):
        return None

    today = date.today()
    if birth > today:
        return None

    age = today.year - birth.year - ((today.month, today.day) < (birth.month, birth.day))
    if not (MIN_AGE <= age <= MAX_AGE):
        return None
    return iso_date


def sanitize_age_reported(value) -> Optional[int]:
    """
    Valida uma idade reportada diretamente pela fonte (sem data de
    nascimento por trás) — usada como fallback quando o site só publica
    "Age NN" em vez de uma data de nascimento parseável (caso real do
    GIDStats.com). Mesma faixa de sanidade aplicada a idades derivadas
    de birth_date, para consistência.
    """
    if value is None or value == "":
        return None
    try:
        age = int(float(value))
    except (TypeError, ValueError):
        return None
    return age if MIN_AGE <= age <= MAX_AGE else None


def sanitize_range(value, min_value: float, max_value: float) -> Optional[float]:
    """Descarta um valor numérico fora de uma faixa plausível."""
    if value is None or value == "":
        return None
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    if not (min_value <= value <= max_value):
        return None
    return value


def sanitize_percentage(value) -> Optional[float]:
    return sanitize_range(value, 0.0, MAX_PCT)


def sanitize_fighter_dict(row: dict) -> dict:
    """
    Aplica todas as validações de sanidade a um dicionário de lutador
    (chaves no mesmo formato de fighters_seed.csv). Retorna uma cópia
    com os campos implausíveis zerados para None e a categoria de peso
    normalizada. Não modifica o dicionário original.
    """
    row = dict(row)

    row["birth_date"] = sanitize_birth_date(row.get("birth_date"))
    row["age_reported"] = sanitize_age_reported(row.get("age_reported"))
    row["height_cm"] = sanitize_range(row.get("height_cm"), MIN_HEIGHT_CM, MAX_HEIGHT_CM)
    row["reach_cm"] = sanitize_range(row.get("reach_cm"), MIN_REACH_CM, MAX_REACH_CM)
    row["weight_class"] = normalize_weight_class(row.get("weight_class"))

    for field in ("str_acc_pct", "str_def_pct", "td_acc_pct", "td_def_pct"):
        row[field] = sanitize_percentage(row.get(field))

    row["slpm"] = sanitize_range(row.get("slpm"), 0.0, MAX_SLPM)
    row["sapm"] = sanitize_range(row.get("sapm"), 0.0, MAX_SAPM)
    row["td_avg"] = sanitize_range(row.get("td_avg"), 0.0, MAX_TD_AVG)
    row["sub_avg"] = sanitize_range(row.get("sub_avg"), 0.0, MAX_SUB_AVG)

    for field in ("wins", "losses", "draws", "no_contests", "wins_ko", "wins_sub", "wins_dec"):
        value = row.get(field)
        if value is None or value == "":
            continue
        try:
            ivalue = int(float(value))
            row[field] = ivalue if ivalue >= 0 else None
        except (TypeError, ValueError):
            row[field] = None

    return row


def _normalize_for_diff(value):
    """Normaliza um valor pra comparação 'de verdade' (ignora string vs float/int)."""
    if value is None or value == "":
        return None
    try:
        return round(float(value), 4)
    except (TypeError, ValueError):
        return str(value).strip()


def diff_sanitized_fields(before: dict, after: dict) -> list[str]:
    """
    Retorna os campos cujo valor MUDOU DE VERDADE entre `before` e
    `after` (usado pra logar o que a validação descartou/normalizou).

    Compara os valores de forma tolerante a tipo (a string "180" vinda
    do CSV e o float 180.0 depois de sanitizado contam como iguais) —
    sem essa normalização, praticamente todo campo numérico aparecia
    como "alterado" só por causa da conversão de tipo, o que poluía o
    log com falsos positivos.
    """
    changed = []
    for key, new_value in after.items():
        old_value = before.get(key)
        if _normalize_for_diff(old_value) != _normalize_for_diff(new_value):
            changed.append(key)
    return changed


def describe_sanitization(before: dict, after: dict) -> list[str]:
    """
    Versão legível do diff, para logs/relatórios: diferencia campos que
    foram DESCARTADOS (valor implausível -> None) de campos que foram
    apenas NORMALIZADOS (ex.: grafia da categoria de peso padronizada).
    """
    descriptions = []
    for key in diff_sanitized_fields(before, after):
        old_value, new_value = before.get(key), after.get(key)
        if _normalize_for_diff(new_value) is None:
            descriptions.append(f"{key} (descartado, era {old_value!r})")
        else:
            descriptions.append(f"{key} (normalizado: {old_value!r} -> {new_value!r})")
    return descriptions
