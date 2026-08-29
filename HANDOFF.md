# HANDOFF — base de legislação contábil

Contexto para continuar o projeto (inclusive no Claude Code). O `README.md` cobre a
convenção de uso; este arquivo cobre **o porquê** das decisões e o **estado atual**.

## O que é

Base de legislação contábil/tributária para consulta por uma futura **skill contador**
(RAG). É separada do ContaGestão. Pode, no futuro, ser consumida pelo bot OpenClaw
(FuriaFaturaBot) via `git pull`. Hospedada em Git/GitHub.

## Estado atual

- Repositório publicado (conta GitHub `linckmarcelo`).
- Duas normas convertidas e indexadas no `manifest.json`:
  - **LC 214/2025** — 580 artigos vigentes (versão consolidada do Planalto).
  - **Decreto 12.955/2026** — 620 artigos (regulamenta a CBS; texto publicado).
- Conversor versionado em `conversor/` (fonte da skill `legislacao-pdf-para-markdown`).

## Decisões de design (o porquê)

- **Markdown + chunks JSONL + CSV**, um chunk por artigo. Markdown preserva a hierarquia
  (Livro › Título › Capítulo › Art. › § › inciso › alínea) e permite citação precisa.
- **Slug legível**: `lc-214-2025`, `decreto-12955-2026`. Ids de chunk: `<slug>--art-N`.
- **`vigente: true/false`**: no "Texto compilado" o Planalto mostra a redação anterior E a
  vigente do mesmo artigo (quando alterado depois). A vigente é a última ocorrência (a que
  traz a nota "(Redação dada por…)"); a anterior fica `vigente: false`, preservada mas fora
  da busca padrão. Filtre `vigente: true` para trabalhar. Prefira sempre a **versão
  consolidada que preserve as notas** — entra limpa e sem duplicação.
- **`manifest.json` é índice leve** (lido a cada consulta): só metadados + caminhos, sem a
  lista de anexos (essa vive no `meta.json` da norma, carregado sob demanda).
- **`gerar_manifest.py`** reconstrói o índice varrendo as pastas (idempotente); pastas sem
  `*.meta.json` (ex.: `conversor/`, `scripts/`) são ignoradas.

## Bugs resolvidos no conversor (não regredir)

1. **Referência virando artigo**: "o art. 14 desta Lei" no início de linha era lido como
   novo artigo. Correção: só "Art." maiúsculo abre artigo; texto que começa em minúscula
   após o número é tratado como corpo.
2. **Redação anterior vs. vigente**: dedup por número, última ocorrência (ou a com nota) é a
   vigente; anteriores marcadas e com id namespaced (`--anterior-NNN`).
3. **Tipo LC vs. Decreto**: a detecção pegava a primeira menção de tipo no cabeçalho — o
   preâmbulo do decreto cita "Lei Complementar nº 214" e ele era classificado como LC.
   Correção: ancorar na **epígrafe** ("DECRETO Nº …, DE … DE ANO"), detectada no **texto
   bruto da página 1** (a epígrafe some na limpeza por se repetir como cabeçalho de página).

## Limitação conhecida (em aberto)

Tabelas de anexo que atravessam várias páginas saem **fragmentadas** (um CSV por página) e
às vezes a 1ª linha de dados vira cabeçalho. Os dados estão íntegros. Junção automática de
tabelas multipágina = próximo alvo do conversor.

## Próximos passos

- [ ] **Skill contador** (objetivo final): lê o `manifest.json`, escolhe a norma, filtra
  `vigente: true`, responde citando artigo + trilha. Definir o uso (consulta própria no
  escritório vs. resposta a cliente em linguagem acessível) — isso molda tom e estrutura.
- [ ] Empilhar mais normas (INs da reforma, etc.).
- [ ] Conversor: junção de anexos multipágina.
- [ ] (Ideia) Automação via OpenClaw: PDF por Telegram → converte, commita, push.

## Fluxo para adicionar norma

```
python conversor/scripts/converter.py <norma>.pdf --out ./tmp
mv tmp/<slug> ./<slug>
python scripts/gerar_manifest.py
git add -A && git commit -m "Add <norma>" && git push
```
