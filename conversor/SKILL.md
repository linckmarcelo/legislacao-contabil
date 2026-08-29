---
name: legislacao-pdf-para-markdown
description: >
  Use esta skill SEMPRE que o usuário precisar converter PDF de legislação brasileira
  (leis, leis complementares, decretos, medidas provisórias, emendas, instruções
  normativas, portarias, resoluções) em Markdown estruturado, texto limpo ou base de
  conhecimento para RAG. Extrai a hierarquia (Título, Capítulo, Seção, Art., §, inciso,
  alínea, item) com numeração preservada, separa anexos e tabelas (alíquotas, NCM, faixas)
  em CSV e gera chunks por artigo prontos para indexação. Acionar ao mencionar: "converter
  legislação", "PDF de lei", "norma em markdown", "RAG de legislação", "indexar lei",
  "limpar PDF de decreto", "extrair artigos", "reforma tributária em markdown", "IBS/CBS",
  "LC 214", ou ao enviar um PDF que seja claramente uma norma jurídica — inclusive para
  preparar material do ContaGestão ou da reforma tributária. Não confundir com a skill
  analise-processual: aqui o insumo é a NORMA, não a peça processual.
---

# Skill: Legislação (PDF) → Markdown estruturado para RAG

Converte o PDF de uma norma brasileira em arquivos limpos e hierarquizados, feitos para
duas coisas: **leitura precisa por LLM** e **indexação em base de conhecimento (RAG)**.
O trabalho pesado é determinístico e fica no script `scripts/converter.py`.

## Quando usar

Sempre que o insumo for uma **norma** (lei, LC, decreto, MP, EC, IN, portaria, resolução)
em PDF e o objetivo for lê-la, limpá-la, estruturá-la ou alimentar um índice de busca.
Para **peças processuais** (petição, sentença, contestação), use `analise-processual`.

## Saídas (em `<out>/<slug>/`)

Para cada norma o script gera:

- **`<slug>.md`** — Markdown limpo: front-matter com metadados, divisões como cabeçalhos,
  cada artigo com âncora HTML (`<a id="art-12">`), §/incisos/alíneas formatados, e um
  índice de anexos apontando para os CSVs.
- **`<slug>.chunks.jsonl`** — um objeto por artigo, **auto-contido**: identificador da
  norma, trilha hierárquica (`path`), texto do artigo, notas de vigência, referências
  cruzadas detectadas (`refs`) e lista de anexos. É a unidade natural de indexação.
- **`<slug>.meta.json`** — metadados (tipo, número, ano, ementa, hash, contagens).
- **`anexos/anexo_*.csv`** — tabelas grandes (alíquotas, NCM, faixas) em CSV. Tabelas
  pequenas ficam embutidas no próprio Markdown.

Por que artigo-por-chunk: na legislação brasileira o **artigo** é a unidade semântica
completa (carrega seus parágrafos, incisos e alíneas) e é o alvo natural de citação —
"Art. 12, §3º, II". Isso dá recuperação precisa e citação sem ambiguidade.

## Fluxo de trabalho

### 1. Localize o PDF
Verifique os anexos da conversa e `/mnt/user-data/uploads`. Se o usuário mencionar uma
norma mas não anexar o arquivo, peça o PDF (não invente o texto da norma de memória).

### 2. Instale dependências se necessário
```bash
pip install pymupdf pdfplumber pandas --break-system-packages -q
# OCR de PDFs escaneados (opcional, só se houver páginas em imagem):
#   apt-get install -y tesseract-ocr-por
```

### 3. Rode o conversor
```bash
python scripts/converter.py "<caminho-do-pdf>" --out /mnt/user-data/outputs
```
Opções úteis:
- `--ocr auto|force|off` — fallback de OCR. `auto` (padrão) só aplica OCR em páginas sem
  texto extraível; `force` reprocessa tudo; `off` desliga.
- `--csv-threshold-rows N` — tabelas com ≥ N linhas viram CSV; menores ficam inline
  (padrão 8).

### 4. Inspecione antes de entregar
Leia o `meta.json` e confira: `numero`, `ano`, `n_artigos` e `n_anexos_csv` fazem sentido?
Abra o `.md` e verifique o começo e o fim. Sinais de alerta e o que fazer:

- **`numero`/`ano` nulos** → a epígrafe pode estar em imagem; rode com `--ocr force`.
- **Poucos artigos para uma norma longa** → provável PDF escaneado; use `--ocr force`.
- **Texto de tabela vazando no corpo** → confirme que o cabeçalho do anexo começa com
  "ANEXO"; se usar outro rótulo, veja `references/estrutura-legislativa.md`.
- **Numeração quebrada** (ex.: "Art. 1" sem o "º") → o display já reaplica o ordinal até
  o 9º; para casos exóticos, ajuste `art_display` no script.

### 5. Entregue
Apresente os arquivos com `present_files` (o `.md` primeiro). Resuma em uma linha o que
saiu: nº de artigos, nº de anexos em CSV, e qualquer ressalva da inspeção.

## Notas e limites

- **Texto compilado e redação vigente.** Em versões "Texto compilado" do Planalto, o mesmo
  artigo aparece duas vezes quando foi alterado depois (redação anterior + vigente). O
  script mantém a **vigente** como canônica (`art-N`, a que traz "(Redação dada por…)") e
  marca a anterior com `vigente: false` e id próprio (`art-N--anterior-NNN`). Assim o RAG
  indexa a redação em vigor sem descartar o histórico. Filtre por `vigente: true` para a
  base de trabalho.
- **Notas de vigência.** As notas do próprio texto ("(Redação dada por…)", "(Revogado…)",
  "(Incluído…)") ficam em `notas_vigencia` no chunk — essenciais para saber o que vale.
  O script **não** consolida alterações sozinho; converta a versão já consolidada.
- **Leis alteradas por citação.** Quando a norma altera outra lei ("A Lei X passa a vigorar
  com as seguintes alterações: 'Art. Y…'"), o trecho citado (entre aspas) é absorvido no
  artigo que faz a alteração, e não vira um artigo solto — evita poluir a contagem.
- **Referências cruzadas.** "o art. 14 desta Lei" (minúsculo) não é confundido com um novo
  artigo; só "Art." maiúsculo inicia artigo.
- **Anexos multipágina (limitação conhecida).** O pdfplumber extrai cada página de tabela
  como um CSV separado; uma tabela de anexo que atravessa várias páginas sai fragmentada em
  vários `anexo_*.csv`, e às vezes a primeira linha de dados vira cabeçalho. Os dados estão
  lá, mas podem precisar de junção manual. Melhoria de junção automática está no radar.
- **Anexos são terminais.** A partir do primeiro "ANEXO", o texto sai do fluxo dos artigos
  (as tabelas já vão para CSV). Anexos puramente textuais podem exigir tratamento manual.
- **Não buscar a norma na web.** Esta skill converte o PDF fornecido.

Para a gramática completa da estrutura legislativa (LC 95/1998), padrões de numeração e
casos de borda de parsing, consulte `references/estrutura-legislativa.md`.
