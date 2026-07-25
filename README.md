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

## 🔍 Auditoria de qualidade de dados (v1.3 — categoria e nacionalidade)

Uma terceira rodada de auditoria, também com evidência real (texto da
própria página de rankings e da página do Alex Pereira), encontrou e
corrigiu:

| Problema | Causa raiz | Correção |
|---|---|---|
| Categoria errada (ex.: Alex Pereira, Pantoja e Volkanovski como "Women's Bantamweight") | A página de rankings tem um **dropdown de filtro** ("Select other categories") listando o nome de todas as divisões dentro de `<option>` — o código antigo não distinguia isso de um cabeçalho de seção real, e "Women's Bantamweight" (última opção do dropdown) contaminava lutadores sempre que o cabeçalho real de uma seção não batia | `fetch_ranking_entries` agora remove `<select>/<option>/<nav>` da árvore antes de procurar cabeçalhos, e navega a árvore do BeautifulSoup em vez de regex sobre HTML bruto |
| Nacionalidade cortada (ex.: Alex Pereira como apenas "S") | O campo `"Born São Bernardo do Campo, São Paulo, Brazil"` tem (a) um nome de cidade acentuado, que quebrava a classe de caracteres `[A-Za-z .]` do regex antigo, e (b) duas vírgulas (cidade, estado, país), então "pegar depois da primeira vírgula" retornava o estado, não o país | Nacionalidade agora vem de um token solto que aparece de forma consistente **antes do campo "Style"** (localizado estruturalmente), em vez de tentar decompor o campo "Born" |

## 📸 Fotos dos lutadores (Wikimedia Commons)

`scripts/fetch_fighter_photos.py` busca a imagem principal do artigo da
Wikipédia de cada lutador e **verifica a licença no Wikimedia Commons
antes de baixar qualquer coisa** — só aceita licenças livres (CC-BY,
CC-BY-SA, CC0, domínio público). A licença e a atribuição do fotógrafo
ficam gravadas no banco e são exibidas no perfil do lutador na
interface (exigência das licenças Creative Commons). Lutadores sem foto
com licença confirmada simplesmente não têm foto — nunca uma imagem
"encontrada por aí" sem verificação.

```bash
python scripts/fetch_fighter_photos.py --inspect "Jon Jones"   # debug, não baixa nada
python scripts/fetch_fighter_photos.py --limit 10               # testa em poucos lutadores
python scripts/fetch_fighter_photos.py                          # roda pra todo o banco
```

## 🔎 Filtros combináveis (categoria + nacionalidade)

A tela "Buscar Lutador" agora tem dois filtros além da busca por nome —
categoria de peso e nacionalidade, populados dinamicamente a partir do
que existe no banco. Os três critérios (nome, categoria, nacionalidade)
se combinam com **E** (ex.: brasileiros da categoria peso-leve), e
qualquer um deles pode ficar vazio/"Todas" para não filtrar por aquele
critério — dá pra navegar só por categoria ou só por nacionalidade, sem
digitar nome nenhum.

## 🩹 Correção de regressão (v1.3.1)

A v1.3 introduziu duas regressões, encontradas e relatadas depois do
deploy — documentando aqui porque são o tipo de erro que vale a pena
todo mundo saber que já aconteceu e como foi evitado no futuro:

1. **Scraper zerava a coleta ("0 lutadores encontrados").** A correção
   do bug do dropdown de categorias removia `<select>`, `<option>` **e
   `<nav>`** da árvore antes de procurar cabeçalhos/links — mas só
   havia evidência real de que `<select>`/`<option>` contaminavam a
   extração. `<nav>` foi removido por precaução, sem evidência, e isso
   apagava a listagem real de lutadores sempre que ela estava dentro de
   uma tag `<nav>` (comum e semanticamente correto). **Lição: só remover
   elementos da árvore com evidência concreta de contaminação, nunca por
   suposição "por segurança".**
2. **`IndexError: No item with that key: image_license` em bancos já
   existentes.** `CREATE TABLE IF NOT EXISTS` não adiciona colunas
   novas a uma tabela que já existe — então um `database/fightiq.db`
   criado antes da funcionalidade de fotos não tinha as colunas novas.
   Agora `DatabaseManager` roda uma migração leve (`ALTER TABLE ... ADD
   COLUMN`) automaticamente toda vez que o banco é aberto, então
   atualizações que só *adicionam* colunas não exigem mais apagar o
   banco manualmente. (Mudanças de *tipo* de uma coluna já existente,
   como `fighter_id` de `INTEGER` para `TEXT` na v1.2, ainda exigem
   recriar o banco — SQLite não migra tipo de chave primária de forma
   trivial.)

Ambas têm teste de regressão dedicado em `tests/test_scraper_parsing.py`
e `tests/test_database.py`.

### Teste ao vivo (rede de segurança contra regressões de coleta)

`tests/test_scraper_live.py` verifica que a página de rankings retorna
mais de 150 lutadores — mas precisa de internet de verdade, então fica
**desligado por padrão** (não roda junto com `python -m unittest
discover tests`, pra nunca quebrar num ambiente sem rede). Rode
manualmente depois de qualquer mudança em `scripts/scrape_gidstats.py`:

```bash
FIGHTIQ_RUN_LIVE_TESTS=1 python -m unittest tests.test_scraper_live -v
```

## 🩹 Correção de regressão (v1.3.2) — "0 lutadores encontrados"

A correção da v1.3.1 (remover `<nav>` da lista de decompose) **não
resolveu** o problema — foi uma hipótese razoável, mas errada. A causa
real, encontrada buscando a página ao vivo de novo: os nomes dos
lutadores na página real vêm envoltos em **`<span>` aninhados dentro do
`<a>`** (ex.: `<a href="..."><span>Islam</span><span>1</span><span>IslamMakhachev</span></a>`),
e o código verificava se o **pai direto** do nó de texto era o `<a>` —
com spans aninhados, o pai direto é sempre o `<span>`, nunca o `<a>`, e
**nenhum link batia com essa condição**. Corrigido tratando cada `<a>`
como uma unidade (`soup.descendants` + `get_text()`), robusto a
qualquer nível de aninhamento dentro do link.

**Novidades pra evitar que isso passe despercebido de novo:**
- `python scripts/scrape_gidstats.py --verbose` mostra contadores em
  cada etapa (status HTTP, bytes recebidos, links brutos no HTML,
  cabeçalhos reconhecidos, links válidos) — sem precisar adivinhar em
  qual etapa a contagem despenca.
- O scraper agora **recusa gravar um CSV** se encontrar menos de 150
  lutadores (a menos que `--limit` tenha sido usado de propósito) — erro
  explícito, em vez de gerar silenciosamente um `fighters_seed.csv`
  vazio como aconteceu nessa regressão.

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
