---
name: conversao-legislacao-pdf-markdown
description: >
  Use esta skill SEMPRE que o usuario precisar adicionar uma nova legislacao
  (lei, decreto, IN, LC, resolucao, ato, portaria, PeR) ao repositorio
  legislacao-contabil. Cobre: leitura do PDF, conversao para Markdown
  estruturado, geracao do .meta.json e .chunks.jsonl, e commit/push.
  Acionar quando mencionar: "adicionar legislacao", "converter PDF",
  "nova norma", "incluir lei", "incluir decreto", "incluir IN",
  "adicionar na base de legislacao", "legislacao-contabil", "converter norma",
  "PDF para markdown", "chunks", "meta.json", ou qualquer pedido de
  processar PDF de legislacao para incluir no repositorio.
version: 1.0
updated: 2026-08-31
triggers:
  - adicionar legislacao
  - converter PDF
  - nova norma
  - incluir lei
  - incluir decreto
  - incluir IN
  - base de legislacao
  - legislacao-contabil
  - PDF para markdown
  - chunks
  - meta.json
---

# Conversao de Legislacao PDF para Markdown

Skill para converter PDFs de legislacao brasileira em Markdown estruturado
e incluir no repositorio `legislacao-contabil` (GitHub).

---

## REPOSITORIO

- **URL:** `github.com/linckmarcelo/legislacao-contabil`
- **Diretorio local:** procurar em `~/Documents/GitHub/legislacao-contabil` ou `~/OneDrive/Documentos/GitHub/legislacao-contabil`
- **Branch:** `main`

---

## ESTRUTURA DE CADA NORMA

Cada norma fica em uma pasta propria com 3 arquivos obrigatorios + 1 pasta opcional:

```
{slug}/
  {slug}.md              # Texto integral em Markdown
  {slug}.meta.json       # Metadados da norma
  {slug}.chunks.jsonl    # Artigos/perguntas como chunks (1 JSON por linha)
  anexos/                # (opcional) Tabelas/anexos como CSV
    anexo_01.csv
    anexo_02.csv
```

### Convencao de slug

O slug segue o padrao `{tipo}-{numero}-{ano}` em lowercase:

| Tipo da norma | Slug | Exemplo |
|---------------|------|---------|
| Lei Complementar | `lc-{num}-{ano}` | `lc-214-2025` |
| Lei Ordinaria | `lei-{num}-{ano}` | `lei-8212-1991` |
| Decreto | `decreto-{num}-{ano}` | `decreto-12955-2026` |
| Instrucao Normativa | `in-{num}-{ano}` | `in-2110-2022` |
| Ato Conjunto | `ato-conjunto-{num}-{ano}` | `ato-conjunto-1-2025` |
| Resolucao | `resolucao-{num}-{ano}` | `resolucao-6-2026` |
| Portaria | `portaria-{num}-{ano}` | `portaria-7-2026` |
| Perguntas e Respostas | `per-{tema}-{ano}` | `per-irpf-2026` |

---

## PASSO 1 — LEITURA DO PDF

1. O usuario fornece o PDF (path local ou upload)
2. Ler o PDF completo — usar a tool Read com paginas (ex: `pages: "1-20"`)
3. Identificar:
   - **Tipo** da norma (LC, Lei, Decreto, IN, etc.)
   - **Numero** e **ano**
   - **Ementa** (texto apos "O PRESIDENTE DA REPUBLICA..." ate o primeiro "Art. 1o")
   - **Estrutura** (livros, titulos, capitulos, secoes, subsecoes)
   - **Total de artigos**
   - **Anexos** (tabelas, listas)
   - **Redacoes anteriores** (texto riscado ou "(Redacao dada pela...)")

---

## PASSO 2 — GERAR O MARKDOWN ({slug}.md)

### Cabecalho YAML frontmatter

```yaml
---
identificador: "LC 214/2025"
tipo: "LC"
numero: "214"
ano: "2025"
fonte_arquivo: "Lcp 214.pdf"
sha256_16: "{primeiros 16 chars do SHA-256 do PDF}"
ementa: "Dispoe sobre..."
---
```

### Corpo do Markdown

Regras de formatacao:

1. **Titulo:** `# {identificador}` seguido da ementa em blockquote
2. **Estrutura hierarquica:**
   - Livro: `## LIVRO I — TITULO`
   - Titulo: `### TITULO I — NOME`
   - Capitulo: `#### CAPITULO I NOME`
   - Secao: `##### Secao I Nome`
   - Subsecao: `###### Subsecao I Nome`
3. **Artigos:**
   - Ancora antes: `<a id="art-1"></a>`
   - Negrito: `**Art. 1o.** Texto do caput...`
   - Paragrafos: `**§ 1o** Texto...` ou `**Paragrafo unico.** Texto...`
   - Incisos: lista com `- I – texto`
   - Alineas: lista aninhada com `  - a) texto`
   - Itens: lista aninhada com `    - 1. texto`
4. **Redacoes anteriores:** manter inline com nota `(Redacao dada pela Lei X/YYYY)`
5. **Artigos revogados:** manter com nota `(Revogado pela Lei X/YYYY)` — marcar como `vigente: false` nos chunks
6. **Tabelas:** converter para Markdown table. Se muito grandes, separar em CSV na pasta `anexos/`
7. **Notas de vigencia:** incluir apos o texto como nota: `    Producao de efeitos`

### Dicas de qualidade

- Nao truncar artigos longos — incluir texto integral
- Manter pontuacao e formatacao original (maiusculas em titulos, numeracao romana)
- Acentos: manter acentuacao original do texto legal
- Formulas e valores monetarios: manter como no original
- Tabelas complexas: preferir CSV em `anexos/` com referencia no texto

---

## PASSO 3 — GERAR O META.JSON ({slug}.meta.json)

```json
{
  "tipo": "LC",
  "numero": "214",
  "ano": "2025",
  "identificador": "LC 214/2025",
  "ementa": "Dispoe sobre...",
  "fonte_arquivo": "Lcp 214.pdf",
  "sha256_16": "abc123def456gh78",
  "n_artigos": 580,
  "n_artigos_vigentes": 575,
  "n_redacoes_anteriores": 12,
  "n_anexos_csv": 70,
  "n_paginas": 150
}
```

Campos opcionais adicionais (usar quando relevante):
- `"fonte_versao": "Texto compilado (Planalto)"` — se veio do site do Planalto
- `"atualizado_em": "2026-08-31"` — data da ultima atualizacao do texto compilado

### Como calcular sha256_16

```python
import hashlib
with open("arquivo.pdf", "rb") as f:
    sha = hashlib.sha256(f.read()).hexdigest()[:16]
```

Ou no terminal:
```bash
# Linux/Mac
sha256sum arquivo.pdf | cut -c1-16

# PowerShell
(Get-FileHash arquivo.pdf -Algorithm SHA256).Hash.Substring(0,16).ToLower()
```

---

## PASSO 4 — GERAR OS CHUNKS ({slug}.chunks.jsonl)

Cada linha do JSONL e um artigo/pergunta como objeto JSON:

```json
{
  "id": "lc-214-2025--art-1",
  "norma": "LC 214/2025",
  "tipo": "LC",
  "path": "LIVRO I > TITULO I > CAPITULO I > Art. 1o",
  "artigo": "1",
  "vigente": true,
  "texto": "Art. 1o. Texto integral do artigo com todos os paragrafos, incisos e alineas...",
  "notas_vigencia": ["(Redacao dada pela LC 227/2026)"],
  "refs": ["art-2", "art-153"],
  "anexos": ["anexo_01.csv"],
  "fonte": "Lcp 214.pdf"
}
```

### Regras dos chunks

1. **id:** `{slug}--art-{numero}` (dois hifens separando slug do artigo)
2. **path:** hierarquia completa separada por ` > ` (Livro > Titulo > Capitulo > Secao > Art.)
3. **artigo:** numero do artigo como string (ex: "1", "14-A", "348")
4. **vigente:** `true` se o artigo esta em vigor, `false` se revogado
5. **texto:** texto integral do artigo com todos os paragrafos, incisos, alineas — usar `\n` para quebras de linha
6. **notas_vigencia:** array de notas como "(Redacao dada pela...)", "(Incluido pela...)", "(Revogado pela...)"
7. **refs:** array de IDs de artigos referenciados (ex: `["art-2", "art-14"]`) — extrair de mencoes como "art. 2o", "arts. 14 e 15"
8. **anexos:** array de nomes de CSV referenciados neste artigo (ex: `["anexo_01.csv"]`)
9. **fonte:** nome do arquivo PDF original

### Para Perguntas e Respostas (PeR)

Usar formato adaptado:

```json
{
  "id": "per-irpf-2026--q-001",
  "norma": "PeR IRPF 2026",
  "tipo": "PeR",
  "path": "Obrigatoriedade > Pergunta 001",
  "artigo": "001",
  "vigente": true,
  "texto": "Pergunta: Quem esta obrigado a declarar?\nResposta: ...",
  "notas_vigencia": [],
  "refs": [],
  "anexos": [],
  "fonte": "Perguntao_IRPF_2026.pdf"
}
```

---

## PASSO 5 — ANEXOS (CSV)

Tabelas grandes (mais de 5 colunas ou 20 linhas) devem ir para `anexos/`:

- Nome: `anexo_{NN}.csv` (numero sequencial com 2 digitos)
- Encoding: UTF-8
- Separador: virgula
- Header: primeira linha com nomes das colunas
- Referencia: no chunk do artigo correspondente, incluir em `"anexos"`

---

## PASSO 6 — VALIDACAO

Antes de commitar, verificar:

1. **Contagem:** `n_artigos` no meta.json bate com total de linhas no chunks.jsonl
2. **IDs unicos:** nenhum id duplicado nos chunks
3. **Vigentes:** `n_artigos_vigentes` bate com chunks onde `vigente: true`
4. **JSON valido:** cada linha do JSONL e JSON valido (testar com `jq`)
5. **Frontmatter:** o .md tem frontmatter YAML valido e bate com meta.json
6. **Anexos:** todos os CSVs referenciados nos chunks existem na pasta

Script de validacao rapida:
```bash
# Contar chunks
wc -l {slug}.chunks.jsonl

# Verificar JSON valido
cat {slug}.chunks.jsonl | python -c "import sys,json; [json.loads(l) for l in sys.stdin]; print('OK')"

# Contar vigentes
cat {slug}.chunks.jsonl | python -c "
import sys,json
lines = [json.loads(l) for l in sys.stdin]
v = sum(1 for l in lines if l['vigente'])
print(f'Total: {len(lines)}, Vigentes: {v}')
"
```

PowerShell equivalente:
```powershell
# Contar chunks
(Get-Content {slug}.chunks.jsonl | Measure-Object -Line).Lines

# Verificar JSON valido
Get-Content {slug}.chunks.jsonl | ForEach-Object { $_ | ConvertFrom-Json } | Measure-Object | Select-Object -ExpandProperty Count
```

---

## PASSO 7 — COMMIT E PUSH

```bash
cd legislacao-contabil
git add {slug}/
git commit -m "feat: adicionar {identificador}"
git push origin main
```

Mensagem de commit padrao: `feat: adicionar {identificador}` (ex: `feat: adicionar LC 235/2026`)

---

## PASSO 8 — ATUALIZAR SKILLS (se necessario)

Se a nova norma for relevante para alguma skill existente:

1. Atualizar a tabela de normas na skill `reforma-tributaria-addendum-SKILL.md` (se for reforma tributaria)
2. Atualizar a secao "BASE DE LEGISLACAO (RAG)" no INDEX com o novo total de normas
3. Upload das skills atualizadas no Drive

---

## FLUXO RESUMIDO

```
PDF fornecido pelo usuario
    |
    v
[1] Ler PDF e identificar tipo/numero/ano/estrutura
    |
    v
[2] Gerar {slug}.md com frontmatter + corpo estruturado
    |
    v
[3] Gerar {slug}.meta.json com metadados
    |
    v
[4] Gerar {slug}.chunks.jsonl (1 artigo por linha)
    |
    v
[5] Extrair tabelas grandes para anexos/ como CSV
    |
    v
[6] Validar contagens, JSON, IDs unicos
    |
    v
[7] git add + commit + push
    |
    v
[8] Atualizar skills/INDEX se necessario
```

---

## NORMAS JA INCLUIDAS NO REPOSITORIO

Antes de converter, verificar se a norma ja existe. Normas atuais:

| Slug | Identificador |
|------|---------------|
| `lc-214-2025` | LC 214/2025 |
| `lc-224-2025` | LC 224/2025 |
| `lc-227-2026` | LC 227/2026 |
| `decreto-12955-2026` | Decreto 12.955/2026 |
| `ato-conjunto-1-2025` | Ato Conjunto 1/2025 |
| `ato-conjunto-4-2026` | Ato Conjunto 4/2026 |
| `ato-conjunto-5-2026` | Ato Conjunto 5/2026 |
| `in-2110-2022` | IN 2110/2022 |
| `in-83-2001` | IN 83/2001 |
| `lei-5172-1966` | Lei 5172/1966 (CTN) |
| `lei-8212-1991` | Lei 8.212/1991 |
| `lei-10256-2001` | Lei 10.256/2001 |
| `lei-13606-2018` | Lei 13.606/2018 |
| `per-irpf-2026` | PeR IRPF 2026 |
| `per-tributacao-altas-rendas-2025` | PeR Tributacao Altas Rendas |

Se a norma ja existir e o usuario quiser atualizar (texto compilado mais recente), sobrescrever os 3 arquivos e atualizar `atualizado_em` no meta.json.

---

## DICAS PRATICAS

- **PDFs do Planalto** (planalto.gov.br): preferir "texto compilado" que ja inclui alteracoes
- **PDFs do DOU** (in.gov.br): texto original sem alteracoes posteriores — ideal para normas novas
- **PDFs grandes (100+ paginas):** processar em lotes de 20 paginas por vez
- **Normas com muitos anexos:** criar todos os CSVs antes de gerar os chunks (para referenciar corretamente)
- **Encoding:** o .md e o .chunks.jsonl devem ser UTF-8 sem BOM
- **Fim de linha:** LF (Unix) — configurar git: `git config core.autocrlf input`
