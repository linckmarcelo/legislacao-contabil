# catalogo/

Pasta de **metadados de referência** do repositório `legislacao-contabil`. Guarda catálogos e índices estruturados que descrevem o universo normativo — não o texto integral das normas.

## Distinção estrutural do repo

O repo `legislacao-contabil` tem hoje três categorias de conteúdo:

1. **Texto integral de normas** (raiz e subpastas por família) — o corpo das normas convertidas em Markdown + chunks JSONL pela skill `legislacao-pdf-para-markdown`. É o que a `skill-contador` cita textualmente para fundamentar resposta.
2. **Tabelas paramétricas** (`tabelas-reforma/`) — CST, cClassTrib, alíquotas, versionadas em JSON para uso operacional.
3. **Catálogos e índices** (`catalogo/`, esta pasta) — metadado que descreve o que existe, como se relaciona, o que está vigente. Essencial para a skill responder sem ter necessariamente todos os textos integrais indexados.

## Arquivos desta pasta

### `normas-contabeis.json`

Fonte de verdade. Lista estruturada com uma entrada por norma. Schema:

```json
{
  "codigo": "NBC TG 47",
  "titulo": "Receita de Contrato com Cliente",
  "familia": "NBC TG",
  "correspondencia_cpc": "CPC 47",
  "situacao": "vigente",
  "aplicacao": ["geral"],
  "revoga": ["NBC TG 17 (CPC 17 R1)", "NBC TG 30 (CPC 30 R1)"],
  "revogada_por": null,
  "tags": ["receita", "reconhecimento", "contratos"],
  "no_repo": false
}
```

Campos:

- `codigo` — identificador canônico (usado como chave)
- `titulo` — nome oficial da norma
- `familia` — classificação (`NBC TG`, `NBC TG PME`, `ITG`, `CTG`, `NBC TSP`, `NBC TA`, `NBC TR`, `NBC TO`, `NBC TSC`, `NBC TP`, `NBC PG`, `NBC PA`, `NBC PP`, `CPC`, `ICPC`, `OCPC`)
- `correspondencia_cpc` — quando NBC TG, aponta o CPC equivalente
- `situacao` — `vigente` | `revogada` | `revisada`
- `aplicacao` — array: `geral`, `pme`, `microempresa`, `setor-publico`, `auditoria`, `revisao`, `outros-trabalhos-asseguracao`, `servicos-correlatos`, `pericia`, `profissional`
- `revoga` — array de códigos de normas revogadas por esta
- `revogada_por` — string com o código da norma que a revogou (ou `null`)
- `tags` — palavras-chave para busca temática
- `no_repo` — `true` quando o texto integral já está indexado no repo; `false` quando ainda precisa ser convertido

### `normas-contabeis.md`

Renderização humana do JSON, organizada por família em tabelas. Serve para leitura direta no GitHub. **Não editar manualmente** — regenerar a partir do JSON quando o catálogo mudar.

## Convenções de atualização

### Ao converter uma norma nova para o repo:

1. Rodar a skill `legislacao-pdf-para-markdown` sobre o PDF oficial
2. Commitar o Markdown + chunks JSONL na estrutura de pastas do repo
3. **Neste catálogo:** flipar `no_repo` para `true` na entrada correspondente do `normas-contabeis.json`
4. Regenerar `normas-contabeis.md` a partir do JSON atualizado
5. Bumpar `meta.versao` (patch para simples flip; minor para novos campos; major para mudança de schema) e atualizar `meta.atualizado_em`
6. Commitar tudo junto no `legislacao-contabil`
7. **Atualizar o INDEX no Drive** (regra do repo) apontando a nova norma indexada e a nova versão do catálogo

### Ao adicionar uma norma nova que ainda não existia:

Igual acima, mas antes acrescentar a entrada no JSON com `no_repo: false` (se ainda não convertida) ou `true` (se convertendo no mesmo commit).

### Ao registrar revogação:

- Na norma revogada: mudar `situacao` para `"revogada"` e preencher `revogada_por`
- Na norma revogadora: acrescentar a norma revogada em `revoga`
- Manter as duas no catálogo (histórico normativo é útil)

## Uso pela `skill-contador`

A skill carrega o `normas-contabeis.json` via `raw.githubusercontent.com` e o utiliza para:

- Responder perguntas de correspondência (CPC ↔ NBC TG)
- Filtrar normas aplicáveis a um regime (PME, setor público, auditoria)
- Sinalizar situação de vigência antes de citar
- Priorizar a busca em chunks — quando `no_repo: true`, buscar o texto integral; quando `false`, responder com metadado e link oficial
- Encadear revogações e revisões

## Estrutura futura desta pasta

Reservada para outros catálogos de mesma natureza, quando fizer sentido acrescentar:

- `pronunciamentos-cvm.json` — deliberações e ofícios circulares CVM aplicáveis a contabilidade
- `sumulas-carf.json` — súmulas vinculantes do CARF por tema tributário
- `manuais-oficiais.json` — MCASP, MTC, MSC e correlatos do setor público
- `catalogo-tributario.json` — índice de leis e ICPCs tributárias (LC 214, IN RFB, etc.)

Cada catálogo novo segue o mesmo padrão: um `.json` estruturado + um `.md` renderizado + entrada no INDEX do Drive.
