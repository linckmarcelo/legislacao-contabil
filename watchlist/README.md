# watchlist/

Watchlist automatizada de normas da reforma tributaria.

## Como funciona

1. **Workflow GitHub Actions** (`.github/workflows/watch-reforma.yml`) roda todo dia
   as 07:00 BRT (10:00 UTC).
2. O script `scripts/watch/watch_reforma.py` consulta o DOU (in.gov.br)
   pelos ultimos N dias (default 7) usando palavras-chave de reforma
   tributaria.
3. Para cada norma nova nao indexada no `catalogo/legislacao-tributaria.json`:
   baixa o PDF, roda `conversor/scripts/converter.py`, cria a pasta padrao
   (`<tipo>-<num>-<ano>/`), atualiza o catalogo e commita no `main`.
4. Abre uma Issue com o resumo do dia.

## Arquivos

- `watchlist.json` — estado persistido: ultima execucao + lista de todas as
  normas detectadas (indexadas, pendentes, falhas).
- `historico/YYYY-MM-DD.md` — relatorio humano de cada execucao do watcher,
  com links.

## Executar manualmente

### Dry-run (so detecta, nao commita)

```
python scripts/watch/watch_reforma.py \
  --repo-root . \
  --lookback-days 30 \
  --dry-run true \
  --summary-out _watch_summary.md
```

### Rodada real

```
python scripts/watch/watch_reforma.py \
  --repo-root . \
  --lookback-days 7 \
  --dry-run false \
  --summary-out _watch_summary.md
```

### Via GitHub Actions sob demanda

Em `Actions` → `watch-reforma-tributaria` → **Run workflow**:
- `lookback_days`: janela de dias a olhar (1 a 60; default 7).
- `dry_run`: `true` para so detectar, `false` para indexar de verdade.

## Dependencias Python

```
pip install pymupdf pdfplumber pandas requests beautifulsoup4 lxml
```

## Estado de uma entrada (`status`)

- `detectada` — achada no DOU, aguardando conversao.
- `em_conversao` — download ok, conversao em andamento.
- `indexada` — pasta criada no repo + catalogo atualizado.
- `falha` — tentou indexar e deu erro (`nota` descreve).
- `descartada` — fora do escopo (manual).
