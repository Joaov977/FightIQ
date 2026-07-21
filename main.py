"""
main.py
-------
Ponto de entrada do FightIQ — UFC Performance Analyzer.

Responsável apenas por:
    - Configurar o logging inicial.
    - Instanciar a aplicação (interface.FightIQApp).
    - Capturar e logar qualquer erro fatal de inicialização, exibindo
      uma mensagem amigável em vez de um traceback cru para o usuário.

Para executar o projeto:
    python main.py
"""

from __future__ import annotations

import sys
import traceback

from utils import get_logger

logger = get_logger("fightiq.main")


def main() -> int:
    try:
        from interface import FightIQApp
    except ImportError as exc:
        logger.critical("Falha ao importar dependências da interface: %s", exc)
        print(
            "\nErro: não foi possível importar as dependências do FightIQ.\n"
            "Verifique se todos os pacotes de requirements.txt estão instalados:\n"
            "    pip install -r requirements.txt\n"
        )
        return 1

    try:
        app = FightIQApp()
        logger.info("FightIQ iniciado com sucesso.")
        app.mainloop()
        return 0
    except Exception:
        logger.critical("Erro fatal na inicialização do FightIQ:\n%s", traceback.format_exc())
        print("\nOcorreu um erro fatal ao iniciar o FightIQ. Consulte logs/fightiq.log para detalhes.\n")
        return 1


if __name__ == "__main__":
    sys.exit(main())
