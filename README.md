# legislacao-contabil

Base de legislação contábil/tributária para consulta pela **skill contador** (RAG).
Cada norma é convertida de PDF para Markdown + chunks JSONL + CSVs de anexo pelo
conversor `legislacao-pdf-para-markdown`, e indexada no `manifest.json`.

## Estrutura

```
legislacao-contabil/
├── manifest.json          # índice leve de todas as normas (lido a cada consulta)
├── conversor/             # a skill que converte PDF -> MD/JSONL/CSV
│   ├── SKILL.md
│   ├── scripts/converter.py
│   └── references/
├── scripts/
│   └── gerar_manifest.py  # regenera o manifest varrendo as pastas
└── <slug-da-norma>/       # uma pasta por norma, ex.: lc-214-2025/
    ├── <slug>.md          # texto em Markdown, com hierarquia e âncoras por artigo
    ├── <slug>.chunks.jsonl # um chunk por artigo (unidade de recuperação do RAG)
    ├── <slug>.meta.json   # metadados da norma (nº, ano, ementa, contagens, sha)
    └── anexos/            # tabelas dos anexos, uma por CSV
```

## Como adicionar uma norma

1. Converta o PDF (de preferência a **versão consolidada** que preserve as notas de
   vigência — "(Redação dada por…)") com o conversor incluído no repo:
   ```
   python conversor/scripts/converter.py <norma>.pdf --out ./tmp
   ```
2. Mova a pasta gerada (`tmp/<slug>/`) para a raiz da base.
3. Regenere o índice:
   ```
   python scripts/gerar_manifest.py
   ```
4. Commit (se em Git) ou sincronize (se em Drive).

## Como a skill consome

1. Lê o `manifest.json` (leve) para saber **quais normas existem** — sem carregar texto.
2. Para a norma relevante, carrega `<slug>.chunks.jsonl` sob demanda.
3. **Filtra `vigente: true`** para trabalhar só com a redação em vigor. As redações
   superadas ficam com `vigente: false` (preservadas para histórico, fora da busca padrão).
4. Cita pelo `id`/`path` do chunk (ex.: `lc-214-2025--art-28`, trilha Livro › Título ›
   Capítulo › Art.).

## Schema do chunk

| campo | descrição |
|---|---|
| `id` | identificador único e estável (`<slug>--art-N`) |
| `norma` / `tipo` | ex.: `LC 214/2025` / `LC` |
| `path` | trilha hierárquica até o artigo |
| `artigo` | número do artigo (`28`, `7-A`, …) |
| `vigente` | `true` = redação em vigor; `false` = redação anterior superada |
| `texto` | caput + §/incisos/alíneas do artigo |
| `notas_vigencia` | notas do próprio texto: "(Redação dada…)", "(Revogado…)", "(Incluído…)" |
| `refs` | artigos citados no texto |
| `anexos` | CSVs de anexo da norma |
| `fonte` | arquivo PDF de origem |

## Limitação conhecida

Tabelas de anexo que atravessam várias páginas saem fragmentadas em vários CSVs
(uma por página), e às vezes a 1ª linha de dados vira cabeçalho. Os dados estão
íntegros; a junção automática está no radar do conversor.
