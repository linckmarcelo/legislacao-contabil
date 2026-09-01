# Tabelas de Classificação Tributária — IBS/CBS (Reforma)

Dados paramétricos do **Informe Técnico IT 2025.002** (CGIBS/Receita Federal),
usados nos Documentos Fiscais Eletrônicos da reforma tributária (NF-e, NFS-e,
CT-e, etc.) para classificar a tributação de cada item.

## Fonte oficial

- **IT 2025.002** — Tabelas: Código de Classificação Tributária, CST,
  Classificação do Crédito Presumido do IBS e da CBS.
- Publicado por: CGIBS + Receita Federal do Brasil.
- Versão atual: **1.60** (22/06/2026).
- Histórico completo de versões no PDF original (`fonte/`).
- Tabelas online: https://dfe-portal.svrs.rs.gov.br/DFE/TabelaClassificacaoTributaria

## Arquivos

```
tabelas-reforma/
├── README.md              ← este arquivo
├── cst.json               ← Tabela CST-IBS/CBS (19 registros)
├── cclasstrib.json        ← Tabela cClassTrib (142 registros, 39 campos)
└── fonte/
    ├── IT_2025_002_v1.60.pdf           ← manual completo (PDF original)
    └── CST_cClassTrib_v1.60.xlsx       ← planilha original (fonte dos JSONs)
```

## O que é cada tabela

### CST-IBS/CBS (19 códigos)
O **Código de Situação Tributária** classifica a situação geral do item no
documento fiscal: tributação integral (000), com redução (200), isenta (400),
suspensa (500), monofásica (550), etc.

Campos principais: código, descrição, indicadores de preenchimento por grupo
XML (ind_gIBSCBS, ind_gIBSCBSMono, ind_gRed, ind_gDif, ind_gTransfCred,
ind_gCredPresIBSZFM, ind_gAjusteCompet) e indicadores por tipo de DF-e.

### cClassTrib (142 códigos)
A **Classificação Tributária** detalha a situação específica dentro de cada CST.
Os três primeiros dígitos do cClassTrib são sempre iguais ao CST correspondente.
Cada código está vinculado a um dispositivo da LC 214/2025 e do Decreto
12.955/2026.

Campos principais: código, nome, descrição, artigo da LC 214, tipo de alíquota,
percentuais de redução (pRedIBS, pRedCBS), indicadores de grupos XML,
indicadores por tipo de DF-e, anexo da LC 214, vigência (dIniVig, dFimVig).

### cCredPres (crédito presumido)
Tabela de hipóteses legais de crédito presumido do IBS e da CBS. **Não incluída
nesta versão do Excel** — será adicionada quando disponível. Campos esperados:
código, descrição, dispositivo da LC 214, indicadores de apropriação (via NF ou
via evento), alíquotas CBS/IBS, vigência.

## Como usar (na skill contador)

1. Carregue o `cclasstrib.json` sob demanda (142 registros, ~247 KB).
2. Busque pelo `cClassTrib` (ex.: "200001") ou filtre pelo `CST-IBS/CBS` (ex.:
   todos com CST "200").
3. O campo `LC 214/25` diz o artigo relevante — cruze com a base de legislação
   (`legislacao-contabil/lc-214-2025/`) pra ver o texto do artigo.
4. Os indicadores `ind_*` e `ind*` dizem o que é obrigatório/permitido/vedado
   em cada tipo de DF-e — essenciais pra validação de NF-e.
5. Filtre `dFimVig != null` pra excluir códigos encerrados (hoje: nenhum).

## Alíquotas padrão (2026–2028)

| Ano  | pIBSUF (%) | pIBSMun (%) | pCBS (%) |
|------|-----------|------------|---------|
| 2026 | 0,1       | 0          | 0,9     |
| 2027 | 0,05      | 0,05       | Aguardar |
| 2028 | 0,05      | 0,05       | Aguardar |

## Como atualizar

Quando sair uma nova versão do IT (1.70, 1.80…):

1. Baixe o novo Excel do portal (https://dfe-portal.svrs.rs.gov.br).
2. Substitua o arquivo em `fonte/`.
3. Rode a conversão (ou me mande o Excel que eu gero os JSONs).
4. `git diff` mostra exatamente o que mudou entre versões.
5. Commit + push.

O `git diff` nos JSONs é o **changelog automático** — mais confiável do que
depender das notas de versão do IT, que às vezes omitem mudanças sutis nos
indicadores.
