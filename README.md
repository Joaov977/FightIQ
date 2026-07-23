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
```

**Depois de coletar, carregue os dados no banco** — este é o comando
canônico, funciona tanto numa instalação nova (banco ainda nem existe)
quanto para atualizar um banco já existente:

```bash
python -c "from database import DatabaseManager; DatabaseManager().reseed()"
```

`reseed()` garante o schema do banco antes de fazer qualquer outra coisa,
então é seguro rodá-lo como o primeiro comando depois do scraper, mesmo em
um clone limpo do repositório — não é necessário rodar nenhum outro passo
"oculto" antes. (`python main.py` também inicializa o banco sozinho, via
`DatabaseManager().initialize()`, caso você só queira abrir o app sem
recoletar nada.)

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

## 🔍 Auditoria de qualidade de dados (v1.2 — investigação com dados reais)

Depois da v1.1, uma segunda rodada de auditoria usou o texto **real** da
página `gidstats.com/fighters/miesha_tate.html` (obtido via busca na web)
para localizar a causa raiz exata de cada campo perdido — em vez de
corrigir por tentativa e erro. Principais descobertas e mudanças:

| Campo | O que a investigação encontrou | Correção |
|---|---|---|
| Idade | O site **não publica data de nascimento** em formato numérico — só uma idade já calculada (`"Age 39"`) e o **local** de nascimento (`"Born Tacoma, United States"`, que eu confundia com data) | `Fighter.age_reported` captura a idade direto da fonte; `Fighter.age` usa isso como *fallback* quando não há data de nascimento exata (marcado na interface com `*`) |
| Altura / Alcance | Rótulo (`"Height"`) e valor (`"66 inch 168 cm"`) ficam em **elementos HTML diferentes** — um regex que exige "mesma linha de texto" nunca encontrava o valor | Extração agora **navega a árvore do BeautifulSoup** (localiza o nó exato do rótulo e lê os próximos nós de texto), em vez de regex sobre texto achatado |
| Nacionalidade | Não existe rótulo `"Country:"` na página — a única fonte confiável é o país dentro do campo `"Born <Cidade>, <País>"` | Extração passou a usar esse campo |
| "Reach" vs "Leg Reach" | Ambos aparecem na mesma página; `"Reach"` é substring de `"Leg Reach"` | Busca estrutural por **string exata** do rótulo evita a confusão (testado explicitamente) |

Toda essa extração estrutural, mais os 4 campos investigados, tem testes
automatizados dedicados em `tests/test_scraper_parsing.py` — rode
`python -m unittest discover tests -v` a qualquer momento para conferir
que nada regrediu.

## 🆔 IDs estáveis por slug

`fighter_id` deixou de ser um número sequencial (atribuído pela ordem de
aparição no scraping) e passou a ser o **slug da URL de origem** (ex.:
`"miesha_tate"`). Isso evita que favoritos, histórico de pesquisas e
overrides manuais fiquem apontando para o lutador errado se a posição de
alguém no ranking mudar entre duas coletas.

> ⚠️ **Se você já tinha um `database/fightiq.db` de antes da v1.2**,
> apague o arquivo antes de rodar — o tipo da chave primária mudou
> (era `INTEGER`, agora é `TEXT`), e `CREATE TABLE IF NOT EXISTS` não
> migra tabelas existentes automaticamente.

## ✏️ Curadoria manual (`assets/data/manual_overrides.csv`)

Além da coleta automática, o FightIQ agora suporta uma camada de
correções manuais — útil para os poucos casos em que você (que acompanha
o UFC de perto) sabe que um dado está errado ou ausente e quer corrigir
sem esperar o site de origem atualizar.

**Como funciona:**
- O arquivo fica em `assets/data/manual_overrides.csv`, separado do CSV
  gerado pelo scraper — rodar o scraper de novo **nunca apaga** suas
  correções.
- Cada linha usa o `fighter_id` (slug, ex. `jon_jones`) para identificar
  o lutador, e só as **colunas preenchidas** sobrescrevem o dado
  correspondente — o resto do registro continua vindo do scraper.
- Os overrides são reaplicados automaticamente toda vez que o app abre
  (não precisa rodar `reseed()` manualmente depois de editar o arquivo).
- Todo valor manual passa pela mesma validação de sanidade do resto do
  pipeline (`data_quality.py`) — um erro de digitação (ex. altura de
  "18" em vez de "180") também é pego aqui.
- A interface mostra "✏️ Campos verificados manualmente: ..." no perfil
  de qualquer lutador com correções, para deixar a proveniência clara.

**Exemplo** — corrigindo só o alcance do Islam Makhachev, sem tocar em
mais nada:

```csv
fighter_id,reach_cm,note
islam_makhachev,183,alcance real conferido manualmente pelo usuário
```

(As demais colunas do arquivo podem ficar em branco — veja o cabeçalho
completo já presente no arquivo template.)

**Por que essa arquitetura, e não editar o CSV do scraper direto:** é o
mesmo padrão usado em sistemas de dados profissionais (MDM / "golden
records") — pipeline automático faz o volume, uma camada de curadoria
humana clara e auditável tem a palavra final em casos específicos, sem
que as duas coisas se misturem num único arquivo que o scraper
sobrescreve a cada execução.

## 🧪 Testes automatizados

```bash
python -m unittest discover tests -v
```

41 testes cobrindo `data_quality.py` (validação/normalização),
`scripts/scrape_gidstats.py` (extração estrutural de idade, altura,
alcance e nacionalidade — incluindo o caso "Reach vs Leg Reach") e
`database.py` (IDs estáveis por slug, overrides parciais, persistência
entre reaberturas do app). Rode isso sempre que mexer no scraper ou no
banco, antes de considerar uma mudança pronta.

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
├── tests/                  # Testes automatizados (unittest)
├── requirements.txt
├── assets/data/          # CSV de dados reais (seed do banco) + manual_overrides.csv
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
