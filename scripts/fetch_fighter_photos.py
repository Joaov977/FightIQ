"""
scripts/fetch_fighter_photos.py
--------------------------------
Coleta fotos de lutadores a partir do Wikimedia Commons, com
verificação de licença ANTES de baixar qualquer imagem.

Por que Wikimedia Commons e não outra fonte:
    - Toda imagem no Commons tem metadado de licença estruturado e
      público, acessível via API (`imageinfo` + `extmetadata`).
    - Isso permite checar programaticamente se a licença é livre
      (CC-BY, CC-BY-SA, CC0, domínio público) ANTES de baixar — em vez
      de assumir que "está na internet, então pode usar".
    - Fotos de outras fontes (sites de notícia, redes sociais, sites de
      estatísticas) normalmente não têm licença de redistribuição clara;
      baixá-las e embutir no projeto seria o cenário de maior risco.

Fluxo, por lutador:
    1. Busca o artigo da Wikipédia (en.wikipedia.org) com o nome do lutador.
    2. Pega o arquivo de imagem principal do artigo (pageimage).
    3. Consulta o Commons para os metadados de licença desse arquivo.
    4. Só baixa e salva localmente se a licença for reconhecidamente
       livre; caso contrário, o lutador fica sem foto (nunca inventa
       nem usa uma imagem sem confirmar a licença).
    5. Grava caminho local + licença + atribuição + URL de origem no
       banco — a interface exibe a atribuição junto da foto.

IMPORTANTE — rode isso na SUA máquina (mesmo motivo do scraper
principal: o ambiente onde este projeto foi desenvolvido não tem
acesso de rede a wikipedia.org/wikimedia.org).

Uso:
    python scripts/fetch_fighter_photos.py                # todos os lutadores do banco
    python scripts/fetch_fighter_photos.py --limit 10
    python scripts/fetch_fighter_photos.py --inspect "Jon Jones"   # debug de 1 lutador, não baixa
"""

from __future__ import annotations

import argparse
import re
import sys
import time
from pathlib import Path
from typing import Optional

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from database import DatabaseManager  # noqa: E402
from utils import IMAGES_DIR, get_logger  # noqa: E402

logger = get_logger(__name__)

WIKIPEDIA_API = "https://en.wikipedia.org/w/api.php"
COMMONS_API = "https://commons.wikimedia.org/w/api.php"
USER_AGENT = "FightIQPhotoCollector/1.0 (+educational portfolio project)"
REQUEST_TIMEOUT = 15
DEFAULT_DELAY_SECONDS = 1.0

# Licenças aceitas (case-insensitive, checagem por substring no nome
# curto da licença retornado pelo Commons). Só licenças livres para
# reuso — nada de "fair use" ou "todos os direitos reservados".
ALLOWED_LICENSE_KEYWORDS = ("cc0", "cc-by", "public domain", "pd-", "cc by")

PHOTOS_DIR = Path(IMAGES_DIR) / "fighters"


def _get_json(session: requests.Session, url: str, params: dict) -> Optional[dict]:
    try:
        response = session.get(url, params=params, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as exc:
        logger.warning("Falha ao consultar %s: %s", url, exc)
        return None


def find_wikipedia_lead_image(session: requests.Session, fighter_name: str) -> Optional[str]:
    """Busca o artigo da Wikipédia do lutador e retorna o nome do arquivo de imagem principal."""
    data = _get_json(session, WIKIPEDIA_API, {
        "action": "query", "format": "json",
        "prop": "pageimages", "piprop": "name",
        "titles": fighter_name, "redirects": 1,
    })
    if not data:
        return None
    pages = data.get("query", {}).get("pages", {})
    for page in pages.values():
        image_name = page.get("pageimage")
        if image_name:
            return image_name
    return None


def get_commons_license(session: requests.Session, file_name: str) -> Optional[dict]:
    """
    Consulta o Commons pelos metadados de licença de um arquivo.
    Retorna um dict {license, artist, source_url} só se a licença for
    reconhecidamente livre; None caso contrário (arquivo sem licença
    clara, licença restritiva, ou erro de rede).
    """
    data = _get_json(session, COMMONS_API, {
        "action": "query", "format": "json",
        "titles": f"File:{file_name}",
        "prop": "imageinfo", "iiprop": "url|extmetadata",
    })
    if not data:
        return None

    pages = data.get("query", {}).get("pages", {})
    for page in pages.values():
        imageinfo = page.get("imageinfo")
        if not imageinfo:
            continue
        info = imageinfo[0]
        metadata = info.get("extmetadata", {})
        license_short = metadata.get("LicenseShortName", {}).get("value", "")
        if not any(keyword in license_short.lower() for keyword in ALLOWED_LICENSE_KEYWORDS):
            logger.info("Licença não-livre ou não reconhecida para %s: %r — pulando.", file_name, license_short)
            return None
        artist_html = metadata.get("Artist", {}).get("value", "")
        artist = re.sub(r"<[^>]+>", "", artist_html).strip() or "Wikimedia Commons"
        return {
            "license": license_short,
            "artist": artist,
            "image_url": info.get("url"),
            "source_url": f"https://commons.wikimedia.org/wiki/File:{file_name}",
        }
    return None


def download_image(session: requests.Session, image_url: str, dest_path: Path) -> bool:
    try:
        response = session.get(image_url, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
    except requests.RequestException as exc:
        logger.warning("Falha ao baixar imagem %s: %s", image_url, exc)
        return False
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    dest_path.write_bytes(response.content)
    return True


def fetch_photo_for_fighter(session: requests.Session, fighter_id: str, fighter_name: str,
                             dry_run: bool = False) -> Optional[dict]:
    """
    Pipeline completo para um lutador: Wikipédia -> Commons -> checagem
    de licença -> download. Retorna metadados prontos para gravar no
    banco, ou None se não achou uma imagem com licença livre confirmada.
    """
    image_name = find_wikipedia_lead_image(session, fighter_name)
    if not image_name:
        logger.info("Sem imagem principal na Wikipédia para '%s'.", fighter_name)
        return None

    license_info = get_commons_license(session, image_name)
    if not license_info:
        return None

    if dry_run:
        return license_info

    ext = Path(license_info["image_url"]).suffix or ".jpg"
    local_path = PHOTOS_DIR / f"{fighter_id}{ext}"
    if not download_image(session, license_info["image_url"], local_path):
        return None

    return {
        "local_image_path": str(local_path),
        "image_license": license_info["license"],
        "image_attribution": license_info["artist"],
        "image_source_url": license_info["source_url"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Coletor de fotos de lutadores (Wikimedia Commons)")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--delay", type=float, default=DEFAULT_DELAY_SECONDS)
    parser.add_argument("--inspect", type=str, default=None,
                         help="Modo debug: mostra a licença encontrada para um nome, sem baixar nem gravar")
    args = parser.parse_args()

    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})

    if args.inspect:
        image_name = find_wikipedia_lead_image(session, args.inspect)
        print(f"Imagem principal na Wikipédia: {image_name!r}")
        if image_name:
            info = get_commons_license(session, image_name)
            print(f"Metadados de licença (Commons): {info}")
        return 0

    db = DatabaseManager()
    db.initialize()
    fighters = db.list_all_fighters()
    if args.limit:
        fighters = fighters[: args.limit]

    found, skipped = 0, 0
    for i, fighter in enumerate(fighters, start=1):
        result = fetch_photo_for_fighter(session, fighter.fighter_id, fighter.name)
        if result:
            db.set_fighter_photo(fighter.fighter_id, **result)
            found += 1
            print(f"[{i}/{len(fighters)}] ✅ {fighter.name}: foto salva "
                  f"({result['image_license']}, {result['image_attribution']})")
        else:
            skipped += 1
            print(f"[{i}/{len(fighters)}] ⚠ {fighter.name}: nenhuma foto com licença livre encontrada")
        time.sleep(args.delay)

    print(f"\n✅ {found} foto(s) salva(s) | ⚠ {skipped} lutador(es) sem foto (licença não encontrada/confirmada)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
