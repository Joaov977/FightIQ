# 🥊 FightIQ — UFC Performance Analyzer

Analisador de desempenho de atletas do UFC, desenvolvido em Python com interface
gráfica moderna (CustomTkinter), banco de dados local (SQLite) e visualizações
com Matplotlib.

O princípio central deste projeto é: **nenhum dado é inventado**. Tudo o que o
FightIQ exibe — cartel, físico, estatísticas de golpes e quedas — vem de fontes
públicas reais, com a origem de cada registro rastreável dentro do próprio banco
de dados.

---

## 📊 De onde vêm os dados

Não existe atualmente uma API pública gratuita e completa para estatísticas de
lutadores do UFC. Por isso, o FightIQ usa a estratégia recomendada para esse
cenário:

1. Os dados são coletados manualmente de fontes públicas de estatísticas de MMA
   — principalmente **[GIDStats.com](https://gidstats.com)**, que publica os
   registros oficiais de luta (cartel, golpes por minuto, precisão, quedas,
   etc.) usados por diversos veículos de mídia esportiva — e da própria
   **UFC.com**.
2. Esses dados são organizados em `assets/data/fighters_seed.csv`, com uma
   coluna `source_url` **por lutador**, apontando exatamente de onde aquele
   registro veio.
3. Na primeira execução, `database.py` lê esse CSV e popula o banco SQLite
   (`database/fightiq.db`). Isso significa que o app funciona **100% offline**
   depois da primeira inicialização.
4. Campos que não puderam ser verificados com confiança **ficam em branco**
   (`NULL` no banco, exibido como "N/D" na interface) — o sistema nunca estima,
   arredonda ou "adivinha" um valor ausente.

### Conjunto de dados incluído

Esta entrega vem com **3 lutadores totalmente verificados** como prova de
conceito (Jon Jones, Islam Makhachev e Zhang Weili), cobrindo divisões
diferentes e lutadores de ambos os gêneros. O objetivo não foi maximizar a
quantidade de registros, e sim garantir que **cada número no banco seja real e
citável** — em vez de preencher o CSV com uma lista maior de dados não
verificados.

> ⚠️ Nota de qualidade: os campos de golpes/quedas foram extraídos de forma
> semi-automática do GIDStats.com. Recomenda-se conferir os valores na fonte
> (`source_url`) antes de usar este projeto para qualquer finalidade que exija
> precisão estatística absoluta (ex.: apostas, jornalismo). Para portfólio e
> demonstração de arquitetura de software, os dados são adequados como estão.

### Como adicionar mais lutadores manualmente

Basta adicionar uma nova linha em `assets/data/fighters_seed.csv`, seguindo o
mesmo formato (preenchendo `source` e `source_url` com a referência real), e
rodar:

```python
from database import DatabaseManager
DatabaseManager().reseed()
```

### Como coletar dezenas/centenas de lutadores automaticamente

`scripts/scrape_gidstats.py` é um coletor real que lê a página pública de
rankings do GIDStats.com (que lista 150+ lutadores ativos do UFC, com link
para a página individual de cada um), visita cada página e extrai os campos
reais para o CSV — nada é inventado; campos que o parser não encontra ficam
vazios.

> Esse script **precisa ser rodado na sua máquina**, não dentro do ambiente
> onde este projeto foi originalmente montado (que não tem acesso de rede a
> gidstats.com). Ele verifica o `robots.txt` do site antes de começar e usa
> um intervalo de 1.5s entre requisições por padrão, para não sobrecarregar
> o servidor.

```bash
pip install -r requirements.txt      # já inclui beautifulsoup4

# Teste rápido em 1 lutador antes de rodar tudo (mostra os campos extraídos)
python scripts/scrape_gidstats.py --inspect jon_jones

# Coleta os primeiros 20, pra validar o resultado
python scripts/scrape_gidstats.py --limit 20

# Coleta todo mundo listado nos rankings (pode levar alguns minutos)
python scripts/scrape_gidstats.py

# Depois, carregue os dados coletados no banco:
python -c "from database import DatabaseManager; DatabaseManager().reseed()"
```

**Nota de qualidade:** os padrões (regex) de extração foram validados contra
uma amostra sintética que reproduz o formato de texto observado nas páginas
do GIDStats, mas a estrutura real do HTML pode variar ligeiramente por
lutador. Rode `--inspect <slug>` em alguns nomes antes da coleta completa
para conferir se os campos estão saindo corretos; se algum padrão não bater,
ele simplesmente fica vazio (nunca inventa um valor) e pode ser ajustado em
`parse_fighter_page()`.

### Preparado para dados ao vivo

`api.py` já contém o esqueleto (`DataUpdateService`) para conectar o FightIQ a
uma fonte de dados ao vivo (uma API própria, um serviço de terceiros, etc.) no
futuro, sem precisar alterar a interface, o banco ou a análise — apenas
implementar a chamada real dentro desse módulo.

---

## 🔍 Auditoria de qualidade de dados (v1.1)

Depois da primeira coleta em escala (~175 lutadores via
`scripts/scrape_gidstats.py`), uma auditoria encontrou inconsistências
(idade "-1", categorias faltando, altura/alcance trocados). As causas e
correções estão documentadas nos comentários de `data_quality.py` e no
cabeçalho de `scripts/scrape_gidstats.py`. Resumo:

| Problema | Causa raiz | Correção |
|---|---|---|
| Idade `-1` | Regex de data de nascimento pegava a **primeira data solta na página** (podia ser data de evento futuro) | Agora só aceita data ancorada a um rótulo real (Born/DOB); e `data_quality.py` descarta qualquer idade fora de 17–60 anos como camada extra de segurança |
| Categoria "N/D" | Regex exigia grafia e posicionamento exatos no texto da página individual | Categoria agora vem da **página de rankings** (fonte estruturada), com a página individual como fallback |
| Altura/alcance ausentes ou trocados | Regex de altura não tinha âncora ao rótulo "Height" — podia pegar o valor de "Reach" por engano | Ambos os regex agora são ancorados ao próprio rótulo; adicionado fallback para valores em metros |
| Vitórias por finalização/decisão zeradas | Regex não aceitava a forma plural ("Submissions", "Decisions") | Corrigido para aceitar singular e plural |

Toda linha, seja vinda do scraper ou de edição manual do CSV, passa por
`data_quality.sanitize_fighter_dict()` antes de entrar no banco — uma
segunda camada de defesa que descarta valores fisicamente implausíveis
(idade negativa, altura de 30cm, percentual de 140%, etc.) em vez de
gravá-los. Rode com `--inspect <slug>` para ver exatamente o que foi
extraído e o que a validação ajustou/descartou para um lutador
específico.

## 🏗️ Arquitetura

```
FightIQ/
├── main.py          # Ponto de entrada
├── interface.py      # Toda a UI (CustomTkinter): sidebar, páginas, componentes
├── api.py            # Camada de integração externa (futuras atualizações de dados)
├── database.py       # Camada SQLite: schema, seed, favoritos, histórico
├── analysis.py        # Motor de comparação e geração da "Análise Inteligente"
├── charts.py          # Geração de gráficos (radar, barras, pizza) com Matplotlib
├── data_quality.py    # Validação/normalização de dados (usado pelo scraper e pelo banco)
├── models.py           # Dataclasses do domínio (Fighter, FighterStats, etc.)
├── utils.py             # Logging, tema visual, formatação
├── scripts/
│   └── scrape_gidstats.py  # Coletor real de dados em escala (roda localmente)
├── requirements.txt
├── assets/data/          # CSV de dados reais (seed do banco)
├── database/              # Banco SQLite (gerado na primeira execução)
├── icons/ e images/        # Recursos visuais da interface
```

Cada módulo tem uma única responsabilidade e não conhece detalhes de
implementação dos outros — por exemplo, `interface.py` nunca escreve SQL
diretamente, e `analysis.py` nunca sabe que os dados vieram de um CSV.

---

## ✨ Funcionalidades

- **Tela inicial** com atalhos e lista de lutadores disponíveis.
- **Busca de lutador** por nome/apelido, com perfil completo (foto quando
  disponível, dados biográficos, cartel e estatísticas).
- **Comparação lado a lado** entre dois lutadores, com destaques automáticos de
  vantagem (alcance, altura, defesa, striking, wrestling) calculados apenas
  quando ambos os lutadores têm o dado correspondente.
- **Análise Inteligente**: texto gerado automaticamente a partir dos destaques
  reais da comparação (nunca de um template com números fictícios).
- **Dashboard** com gráfico radar de perfil de luta e gráfico de pizza de
  métodos de vitória.
- **Favoritos** e **Histórico de pesquisas**, persistidos em SQLite.
- Tratamento de erros, logging em arquivo rotativo (`logs/fightiq.log`) e
  mensagens de notificação (toast) na interface.

---

## ▶️ Como executar

```bash
pip install -r requirements.txt
python main.py
```

Na primeira execução, o banco SQLite é criado automaticamente em
`database/fightiq.db` e populado a partir do CSV de dados reais.

---

## 🧰 Tecnologias

Python 3 · CustomTkinter · SQLite3 · Pandas · Matplotlib · Requests · Pillow

---

## 📄 Licença de uso dos dados

Os dados estatísticos referenciados neste projeto pertencem às suas fontes
originais (GIDStats.com / UFC.com) e são usados aqui apenas para fins
educacionais e de demonstração de portfólio. Ao expandir o dataset, mantenha
sempre a atribuição de fonte (`source` / `source_url`) para cada registro.
