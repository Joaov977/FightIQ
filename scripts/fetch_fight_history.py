"""
scripts/fetch_fight_history.py
--------------------------------
Coletor de histórico de lutas do FightIQ — orquestra os providers
plugáveis (Sherdog primário, GIDStats como fallback).

Arquitetura: nenhuma lógica de site fica aqui — este script só decide
A ORDEM em que os providers são tentados e grava o resultado no banco.
Trocar a ordem, desativar um provider, ou adicionar uma terceira fonte
no futuro é uma mudança de configuração neste arquivo, não uma
reescrita do banco ou da interface (ver history_providers/base.py).

IMPORTANTE — rode isso na SUA máquina (mesmo motivo dos outros
coletores: o ambiente onde este projeto foi desenvolvido não tem
acesso de rede a sherdog.com/gidstats.com).

Uso:
    python scripts/fetch_fight_history.py --inspect "Islam Makhachev"  # debug, não grava
    python scripts/fetch_fight_history.py --limit 5                    # testa em poucos lutadores
    python scripts/fetch_fight_history.py                              # roda pra todo o banco
    python scripts/fetch_fight_history.py --verbose                    # com logs de diagnóstico
"""

from __future__ import annotations

import argparse
import sys
import time
import urllib.robotparser
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from data_quality import sanitize_fight_record_dict, describe_sanitization  # noqa: E402
from database import DatabaseManager  # noqa: E402
from history_providers.sherdog_provider import SherdogProvider, BASE_URL as SHERDOG_BASE  # noqa: E402
from history_providers.gidstats_provider import GIDStatsHistoryProvider  # noqa: E402
from models import FightRecord  # noqa: E402

USER_AGENT = "FightIQHistoryCollector/1.0 (+educational portfolio project; respects robots.txt)"
DEFAULT_DELAY_SECONDS = 2.0


def check_robots_allowed(base_url: str, paths: list[str]) -> bool:
    parser = urllib.robotparser.RobotFileParser()
    parser.set_url(f"{base_url}/robots.txt")
    try:
        parser.read()
    except Exception as exc:
        print(f"⚠ Não foi possível ler {base_url}/robots.txt ({exc}). Abortando por precaução.")
        return False
    all_allowed = True
    for path in paths:
        allowed = parser.can_fetch(USER_AGENT, path)
        print(f"  robots.txt ({base_url}): {path} -> {'permitido' if allowed else 'NÃO permitido'}")
        all_allowed = all_allowed and allowed
    return all_allowed


def _apply_sanity_check(records: list[FightRecord]) -> list[FightRecord]:
    """Passa cada registro pela validação de sanidade antes de devolver para gravação."""
    clean_records = []
    for r in records:
        raw = {
            "result": r.result, "method": r.method, "round": r.round,
            "fight_date": r.fight_date.isoformat() if r.fight_date else None,
            "weight_class": r.weight_class,
        }
        clean = sanitize_fight_record_dict(raw)
        descriptions = describe_sanitization(raw, clean)
        if descriptions:
            print(f"    ⚠ ajuste de validação em luta vs {r.opponent_name}: {'; '.join(descriptions)}")
        r.result = clean["result"]
        r.method = clean["method"]
        r.round = clean["round"]
        r.weight_class = clean["weight_class"]
        clean_records.append(r)
    return clean_records


def main() -> int:
    parser = argparse.ArgumentParser(description="Coletor de histórico de lutas (Sherdog primário, GIDStats fallback)")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--delay", type=float, default=DEFAULT_DELAY_SECONDS,
                         help="Segundos de espera entre lutadores (padrão: 2.0 — dois sites diferentes por lutador)")
    parser.add_argument("--inspect", type=str, default=None,
                         help="Modo debug: mostra o histórico extraído de UM lutador (nome completo), sem gravar")
    parser.add_argument("--verbose", action="store_true", help="Logs de diagnóstico de cada provider")
    args = parser.parse_args()

    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})

    sherdog = SherdogProvider(session=session, verbose=True)
    gidstats = GIDStatsHistoryProvider(session=session, verbose=True)

    if args.inspect:
        from models import Fighter
        fake_fighter = Fighter(fighter_id="_inspect", name=args.inspect)
        print(f"Buscando '{args.inspect}' no Sherdog (fonte primária)...")
        records = sherdog.fetch(fake_fighter)
        if not records:
            print(f"\nNão encontrado no Sherdog. Isso é esperado pra fallback funcionar — "
                  f"pra testar o GIDStats de verdade, use --inspect com um fighter_id já no banco.")
        for r in records[:5]:
            print(f"  {r.fight_date} | {r.opponent_name} | {r.result_display} | {r.method_display} | "
                  f"R{r.round} {r.time} | {r.event_name}")
        if len(records) > 5:
            print(f"  ... e mais {len(records) - 5} luta(s)")
        return 0

    print("Verificando robots.txt do Sherdog e do GIDStats...")
    sherdog_ok = check_robots_allowed(SHERDOG_BASE, ["/stats/fightfinder", "/fighter/Islam-Makhachev-76836"])
    gidstats_ok = check_robots_allowed("https://gidstats.com", ["/fighters/jon_jones.html"])
    if not sherdog_ok and not gidstats_ok:
        print("\n❌ Nenhuma das duas fontes permite coleta nos caminhos usados. Abortando.")
        return 1

    db = DatabaseManager()
    db.initialize()
    fighters = db.list_all_fighters()
    if args.limit:
        fighters = fighters[: args.limit]

    total_saved, from_sherdog, from_gidstats, not_found = 0, 0, 0, 0

    for i, fighter in enumerate(fighters, start=1):
        print(f"\n[{i}/{len(fighters)}] {fighter.name}")
        records = []
        if sherdog_ok:
            records = sherdog.fetch(fighter)
            if records:
                from_sherdog += 1
        if not records and gidstats_ok:
            records = gidstats.fetch(fighter)
            if records:
                from_gidstats += 1
        if not records:
            not_found += 1
            print(f"  ⚠ Nenhum histórico encontrado em nenhuma fonte.")
            time.sleep(args.delay)
            continue

        records = _apply_sanity_check(records)
        saved = db.save_fight_history(records)
        total_saved += saved
        print(f"  ✅ {saved} luta(s) gravada(s)")
        time.sleep(args.delay)

    print(f"\n{'=' * 60}")
    print(f"Total: {total_saved} lutas gravadas | {from_sherdog} lutadores via Sherdog | "
          f"{from_gidstats} via GIDStats (fallback) | {not_found} sem histórico em nenhuma fonte")
    return 0


if __name__ == "__main__":
    sys.exit(main())
