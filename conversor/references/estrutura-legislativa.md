# Estrutura da legislação brasileira (referência de parsing)

Base normativa: **Lei Complementar nº 95/1998** (técnica legislativa) e praxe do DOU.
Consulte quando precisar ajustar os regexes do `converter.py` ou entender um caso de borda.

## Hierarquia (do maior para o menor)

Agrupadores (viram cabeçalhos no Markdown):
1. **Parte** (Geral/Especial) — rara
2. **Livro**
3. **Título**
4. **Capítulo**
5. **Seção**
6. **Subseção**

Unidade básica e suas subdivisões:
- **Artigo** (`Art.`) — unidade fundamental. É o chunk de RAG.
  - **Parágrafo** (`§`) ou **Parágrafo único** — desdobra o caput.
  - **Inciso** — algarismo romano (`I`, `II`, `III`…), sempre com travessão: `I –`.
    - **Alínea** — letra minúscula com parêntese: `a)`, `b)`.
      - **Item** — algarismo arábico com parêntese: `1)`, `2)`.

Regra de ouro da LC 95: o caput enumera em **incisos**; o inciso desdobra em **alíneas**;
a alínea desdobra em **itens**. O parágrafo é desdobramento do próprio artigo, não do inciso.

## Numeração — convenções que o parser precisa respeitar

- **Artigos e parágrafos** usam ordinal até o 9 (`Art. 1º`, `§ 9º`) e cardinal a partir do
  10 (`Art. 10`, `§ 10`). A função `art_display` reaplica o `º` até o 9º.
- **Artigos acrescentados** ganham sufixo em letra maiúscula: `Art. 5º-A`, `Art. 5º-B`.
  O parser normaliza para o id `art-5-A` e exibe `Art. 5º-A`.
- **Incisos** em romano; **alíneas** em minúsculas; **itens** em arábico.
- Um "Art." pode iniciar a linha como `Art.`, `Art` ou `Artigo`.

## Epígrafe e ementa

- **Epígrafe**: linha de identificação — `LEI COMPLEMENTAR Nº 214, DE 16 DE JANEIRO DE 2025`.
  O parser extrai tipo/número/ano dela.
- **Ementa**: parágrafo logo abaixo, resumindo o objeto — "Institui o Imposto sobre Bens…".
  Quando epígrafe e ementa caem na mesma linha extraída, o parser remove o prefixo da
  epígrafe por regex.

## Notas de alteração (vigência)

Preservadas como `notas_vigencia` no chunk e mantidas no texto:
- `(Redação dada pela Lei nº X, de ANO)`
- `(Incluído pela Lei nº X, de ANO)`
- `(Revogado pela Lei nº X, de ANO)`
- `(Vide Lei nº X)` / `(Vigência)`

São essenciais para saber **qual redação está valendo**. O script não consolida alterações
automaticamente — trabalhe sobre a versão consolidada que você já tem.

## Ruído comum do PDF/DOU (removido na limpeza)

- Cabeçalho/rodapé repetido ("Diário Oficial da União - Seção 1", "Imprensa Nacional").
- Numeração de página ("Página 1 de 2", "fl. 3", número solto).
- Rodapé "Este texto não substitui o publicado no DOU".
- Hifenização de fim de linha (`contri-\nbuição` → `contribuição`).

A detecção de cabeçalho/rodapé exige que a linha apareça em **pelo menos 2 páginas** — isso
evita apagar conteúdo legítimo no limite entre páginas em documentos curtos.

## Anexos e tabelas

- Anexos são **terminais**: a partir de `ANEXO` o texto sai do fluxo dos artigos.
- Tabelas são extraídas com pdfplumber. Grandes (≥ limiar) → `anexos/anexo_NN.csv` com
  referência no Markdown; pequenas → tabela Markdown embutida.
- Em matéria tributária os anexos costumam trazer alíquotas por setor, faixas de receita
  e listas de **NCM** — manter em CSV permite lookup exato no RAG em vez de busca semântica
  sobre número.

## Casos de borda conhecidos

- **PDF escaneado**: `get_text` volta vazio; o modo `--ocr auto` aciona o tesseract (idioma
  `por`). Sem o pacote `por`, cai para `eng` e a qualidade em português piora — instale
  `tesseract-ocr-por`.
- **Duas colunas**: layouts em coluna dupla podem embaralhar a ordem de leitura; se notar
  texto fora de ordem, considere pré-processar o PDF ou revisar manualmente.
- **Anexo textual** (fórmulas, modelos de formulário, mapas): não vira CSV nem fica no fluxo
  de artigos; sinalize ao usuário que aquele anexo precisa de tratamento à parte.
- **Rótulo de anexo diferente** ("APÊNDICE", "ANEXO ÚNICO"): ajuste `RX_ANEXO` no script.
