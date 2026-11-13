#!/usr/bin/env python3
"""
watch_reforma.py — Deteccao automatica de novas normas da reforma tributaria.

Entra em acao pelo GitHub Actions (.github/workflows/watch-reforma.yml). Fluxo:

1.  Consulta o DOU (in.gov.br) pelos ultimos N dias usando palavras-chave
    de reforma tributaria.
2.  Filtra por tipo de norma relevante: LC, Decreto, MP, Ato Conjunto
    RFB/Comite Gestor do IBS, Portaria MF/Comite Gestor, IN RFB, Resolucao CGSN.
3.  Extrai (tipo, numero, ano) do titulo da materia.
4.  Cruza contra `catalogo/legislacao-tributaria.json`: ignora o que ja esta
    indexado; inclui o resto na watchlist.
5.  Para cada norma nova:
       - baixa o PDF da Imprensa Nacional;
       - roda `conversor/scripts/converter.py` apontando para a pasta
         `<tipo>-<num>-<ano>/`;
       - atualiza o catalogo + regenera o .md.
6.  Grava `watchlist/watchlist.json` e um historico em
    `watchlist/historico/YYYY-MM-DD.md`.
7.  Produz `_watch_summary.md` (passado ao job do Actions para abrir a issue).

O script e deliberadamente tolerante: se uma norma falha, registra no
log e segue com as outras.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import os
import re
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import requests

# ---------------------------------------------------------------------------
# Configuracao
# ---------------------------------------------------------------------------

UA = "legislacao-contabil-watch/1.0 (+https://github.com/linckmarcelo/legislacao-contabil)"

DOU_SEARCH_URL = "https://www.in.gov.br/consulta/-/buscar/dou"

# Palavras-chave para filtrar o DOU. A API do in.gov.br aceita busca por
# texto livre; combinamos esses termos com OR.
KEYWORDS = [
    "IBS",
    "CBS",
    "Imposto Seletivo",
    "reforma tributaria",
    "Simples Nacional",
    "Comite Gestor do IBS",
    "CGIBS",
    "LC 214",
    "cClassTrib",
    "Nanoempreendedor",
    "Lei Complementar",
    "nota tecnica NF-e",
    "contribuinte do IBS",
]

# Tipos que a gente aceita indexar.
# (regex no titulo da materia, tipo normalizado, pasta destino prefix)
TITULO_REGEXES = [
    # LEI COMPLEMENTAR Nº 123, DE 14 DE DEZEMBRO DE 2006
    (re.compile(r"LEI\s+COMPLEMENTAR\s+N[oO°º]?\s*\.?\s*(\d+)[.,]?\s*DE\s+\d+\s+DE\s+\w+\s+DE\s+(\d{4})", re.I), "LC", "lc-{num}-{ano}"),
    # LEI Nº 15.270, DE 2025
    (re.compile(r"\bLEI\s+N[oO°º]?\s*\.?\s*([\d\.]+)[.,]?\s*DE\s+\d+\s+DE\s+\w+\s+DE\s+(\d{4})", re.I), "LEI", "lei-{num}-{ano}"),
    # DECRETO Nº 13.140, DE 21 DE OUTUBRO DE 2026
    (re.compile(r"DECRETO\s+N[oO°º]?\s*\.?\s*([\d\.]+)[.,]?\s*DE\s+\d+\s+DE\s+\w+\s+DE\s+(\d{4})", re.I), "DECRETO", "decreto-{num}-{ano}"),
    # MEDIDA PROVISORIA Nº 1.399, DE 4 DE NOVEMBRO DE 2026
    (re.compile(r"MEDIDA\s+PROVIS[OÓ]RIA\s+N[oO°º]?\s*\.?\s*([\d\.]+)[.,]?\s*DE\s+\d+\s+DE\s+\w+\s+DE\s+(\d{4})", re.I), "MP", "mp-{num}-{ano}"),
    # INSTRUCAO NORMATIVA RFB Nº 2.110, DE ...
    (re.compile(r"INSTRU[CÇ][AÃ]O\s+NORMATIVA\s+(?:RFB\s+)?N[oO°º]?\s*\.?\s*([\d\.]+)[.,]?\s*DE\s+\d+\s+DE\s+\w+\s+DE\s+(\d{4})", re.I), "IN", "in-{num}-{ano}"),
    # ATO CONJUNTO ... Nº 1, DE ... 2025
    (re.compile(r"ATO\s+CONJUNTO[^\n]*N[oO°º]?\s*\.?\s*(\d+)[.,]?\s*DE\s+\d+\s+DE\s+\w+\s+DE\s+(\d{4})", re.I), "ATO CONJUNTO", "ato-conjunto-{num}-{ano}"),
    # RESOLUCAO CGSN Nº 180, DE ...
    (re.compile(r"RESOLU[CÇ][AÃ]O\s+CGSN\s+N[oO°º]?\s*\.?\s*(\d+)[.,]?\s*DE\s+\d+\s+DE\s+\w+\s+DE\s+(\d{4})", re.I), "RES-CGSN", "res-cgsn-{num}-{ano}"),
    # PORTARIA MF Nº 3.089, DE ...
    (re.compile(r"PORTARIA\s+(?:MF|MINIST[EÉ]RIO\s+DA\s+FAZENDA)[^\n]*N[oO°º]?\s*\.?\s*([\d\.]+)[.,]?\s*DE\s+\d+\s+DE\s+\w+\s+DE\s+(\d{4})", re.I), "PORTARIA-MF", "portaria-mf-{num}-{ano}"),
]

# Tipos tratados como "LC" no catalogo (familia). Mapeamento
# tipo_detectado -> familia do catalogo.
FAMILIA_CATALOGO = {
    "LC": "LC",
    "LEI": "LEI",
    "DECRETO": "DECRETO",
    "MP": "MP",
    "IN": "IN",
    "ATO CONJUNTO": "ATO CONJUNTO",
    "RES-CGSN": "RES-CGSN",
    "PORTARIA-MF": "PORTARIA",
}


# ---------------------------------------------------------------------------
# Modelo
# ---------------------------------------------------------------------------

@dataclass
class Hit:
    tipo: str
    numero: str
    ano: str
    titulo: str
    data_publicacao: str
    url_html: str
    url_pdf: str | None = None
    pasta_repo: str = ""
    codigo: str = ""   # "LC 123/2006"

    @classmethod
    def from_raw(cls, raw: dict[str, Any]) -> "Hit | None":
        titulo = (raw.get("title") or raw.get("titulo") or "").strip()
        if not titulo:
            return None
        data_pub = raw.get("pubDate") or raw.get("dataPublicacao") or ""
        url_html = raw.get("urlTitle") or raw.get("url") or raw.get("link") or ""
        for regex, tipo, pasta_tpl in TITULO_REGEXES:
            m = regex.search(titulo)
            if not m:
                continue
            numero_raw = m.group(1).replace(".", "").lstrip("0") or "0"
            ano = m.group(2)
            pasta = pasta_tpl.format(num=numero_raw, ano=ano)
            codigo_tpl = {
                "LC": f"LC {numero_raw}/{ano}",
                "LEI": f"Lei {numero_raw}/{ano}",
                "DECRETO": f"Decreto {numero_raw}/{ano}",
                "MP": f"MP {numero_raw}/{ano}",
                "IN": f"IN {numero_raw}/{ano}",
                "ATO CONJUNTO": f"Ato Conjunto {numero_raw}/{ano}",
                "RES-CGSN": f"Resolucao CGSN {numero_raw}/{ano}",
                "PORTARIA-MF": f"Portaria MF {numero_raw}/{ano}",
            }[tipo]
            return cls(
                tipo=tipo,
                numero=numero_raw,
                ano=ano,
                titulo=titulo,
                data_publicacao=data_pub,
                url_html=url_html,
                pasta_repo=pasta,
                codigo=codigo_tpl,
            )
        return None


@dataclass
class WatchlistEntry:
    codigo: str
    tipo: str
    pasta_repo: str
    titulo: str
    data_publicacao: str
    url_html: str
    url_pdf: str | None
    detectada_em: str
    status: str  # detectada | em_conversao | indexada | descartada | falha
    nota: str = ""


@dataclass
class Summary:
    indexadas: list[dict[str, Any]] = field(default_factory=list)
    detectadas_sem_pdf: list[dict[str, Any]] = field(default_factory=list)
    falhas: list[dict[str, Any]] = field(default_factory=list)
    ignoradas_ja_no_repo: list[dict[str, Any]] = field(default_factory=list)


# ---------------------------------------------------------------------------
# DOU client
# ---------------------------------------------------------------------------

def dou_search(keyword: str, days: int, log: logging.Logger) -> list[dict[str, Any]]:
    """Consulta o endpoint de busca do in.gov.br para uma keyword e janela N dias."""
    today = dt.date.today()
    start = today - dt.timedelta(days=days)
    params = {
        "q": keyword,
        "s": "do1",                         # Secao 1 do DOU
        "exactDate": "personalizado",
        "publishFrom": start.strftime("%d-%m-%Y"),
        "publishTo":   today.strftime("%d-%m-%Y"),
        "delta": "50",
        "sortType": "0",
    }
    url = f"{DOU_SEARCH_URL}?{urlencode(params)}"
    headers = {"User-Agent": UA, "Accept": "application/json"}
    try:
        r = requests.get(url, headers=headers, timeout=30)
        r.raise_for_status()
    except requests.RequestException as exc:
        log.warning("Falha ao consultar DOU (%s): %s", keyword, exc)
        return []
    # A resposta publica HTML por padrao; tentar extrair hits via o endpoint JSON
    # interno. Se falhar, cair para parsing simples.
    try:
        data = r.json()
        if isinstance(data, dict) and "jsonArray" in data:
            return data["jsonArray"] or []
    except ValueError:
        pass
    # Fallback: best-effort, usuario pode querer melhorar depois.
    log.info("Resposta do DOU para '%s' nao foi JSON — pulando parse HTML (TODO).", keyword)
    return []


def resolve_pdf_url(url_html: str, log: logging.Logger) -> str | None:
    """Dada a URL HTML da materia no in.gov.br, descobre a URL do PDF."""
    if not url_html:
        return None
    if not url_html.startswith("http"):
        url_html = "https://www.in.gov.br" + url_html
    headers = {"User-Agent": UA}
    try:
        r = requests.get(url_html, headers=headers, timeout=30)
        r.raise_for_status()
    except requests.RequestException as exc:
        log.warning("Falha ao abrir materia %s: %s", url_html, exc)
        return None
    # A pagina da materia traz um link do tipo:
    #   https://www.in.gov.br/en/web/dou/-/lei-complementar-n-235-...-634123456
    # e expoe um botao "Visualizacao certificada" apontando para
    #   https://pesquisa.in.gov.br/imprensa/jsp/visualiza/index.jsp?jornal=600&pagina=1&data=28/08/2026
    # OU um link direto do PDF em /dou/download/... — procuramos os dois.
    html = r.text
    m = re.search(r'href="(/en/web/dou/-/[^"]+-\d+)/download', html)
    if m:
        return f"https://www.in.gov.br{m.group(1)}/download"
    m = re.search(r'"urlDownload"\s*:\s*"([^"]+)"', html)
    if m:
        pdf = m.group(1).replace("\\/", "/")
        if not pdf.startswith("http"):
            pdf = "https://www.in.gov.br" + pdf
        return pdf
    return None


def download_pdf(url: str, dest: Path, log: logging.Logger) -> bool:
    headers = {"User-Agent": UA}
    try:
        r = requests.get(url, headers=headers, timeout=60, stream=True)
        r.raise_for_status()
    except requests.RequestException as exc:
        log.warning("Falha ao baixar PDF %s: %s", url, exc)
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    with dest.open("wb") as fh:
        for chunk in r.iter_content(chunk_size=65536):
            fh.write(chunk)
    size = dest.stat().st_size
    if size < 1024:
        log.warning("PDF baixado muito pequeno (%s bytes) — provavelmente invalido.", size)
        return False
    return True


# ---------------------------------------------------------------------------
# Repo integration
# ---------------------------------------------------------------------------

def load_catalog(repo_root: Path) -> tuple[dict[str, Any], set[str]]:
    cat_path = repo_root / "catalogo" / "legislacao-tributaria.json"
    if not cat_path.exists():
        raise RuntimeError(f"Catalogo nao encontrado em {cat_path}")
    data = json.loads(cat_path.read_text(encoding="utf-8"))
    codigos = {p.get("codigo", "") for p in data.get("pecas", [])}
    return data, codigos


def save_catalog(repo_root: Path, data: dict[str, Any]) -> None:
    cat_path = repo_root / "catalogo" / "legislacao-tributaria.json"
    cat_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def regenerate_catalog_md(repo_root: Path, log: logging.Logger) -> None:
    gen = repo_root / "catalogo" / "gera-md-legislacao.py"
    if not gen.exists():
        log.warning("gera-md-legislacao.py nao encontrado; .md nao sera regenerado.")
        return
    try:
        subprocess.run(
            [sys.executable, str(gen)],
            cwd=str(repo_root / "catalogo"),
            check=True,
            capture_output=True,
        )
    except subprocess.CalledProcessError as exc:
        log.warning("gera-md-legislacao.py falhou: %s", exc.stderr.decode(errors="ignore"))


def run_converter(repo_root: Path, pdf: Path, out_dir: Path, log: logging.Logger) -> bool:
    converter = repo_root / "conversor" / "scripts" / "converter.py"
    if not converter.exists():
        log.error("Converter nao encontrado em %s", converter)
        return False
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        subprocess.run(
            [sys.executable, str(converter), str(pdf), "--out", str(out_dir)],
            check=True,
            capture_output=True,
        )
    except subprocess.CalledProcessError as exc:
        log.error("converter.py falhou: %s", exc.stderr.decode(errors="ignore"))
        return False
    return True


# ---------------------------------------------------------------------------
# Watchlist storage
# ---------------------------------------------------------------------------

def load_watchlist(repo_root: Path) -> dict[str, Any]:
    wl_path = repo_root / "watchlist" / "watchlist.json"
    if wl_path.exists():
        return json.loads(wl_path.read_text(encoding="utf-8"))
    return {
        "meta": {
            "criado_em": dt.date.today().isoformat(),
            "descricao": "Watchlist automatizada de normas da reforma tributaria.",
            "fonte": "DOU - in.gov.br",
        },
        "ultimo_run": None,
        "entradas": [],
    }


def save_watchlist(repo_root: Path, data: dict[str, Any]) -> None:
    wl_dir = repo_root / "watchlist"
    wl_dir.mkdir(parents=True, exist_ok=True)
    wl_path = wl_dir / "watchlist.json"
    wl_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def append_history(repo_root: Path, summary: Summary) -> None:
    hist_dir = repo_root / "watchlist" / "historico"
    hist_dir.mkdir(parents=True, exist_ok=True)
    today = dt.date.today().isoformat()
    path = hist_dir / f"{today}.md"
    lines = [f"# Watch reforma tributaria — {today}\n"]
    lines.append(f"- Indexadas: {len(summary.indexadas)}")
    lines.append(f"- Ignoradas (ja no repo): {len(summary.ignoradas_ja_no_repo)}")
    lines.append(f"- Falhas: {len(summary.falhas)}")
    lines.append(f"- Detectadas sem PDF resolvivel: {len(summary.detectadas_sem_pdf)}\n")
    if summary.indexadas:
        lines.append("## Indexadas nesta rodada\n")
        for it in summary.indexadas:
            lines.append(f"- **{it['codigo']}** — {it['titulo'][:160]} · [materia]({it['url_html']})")
    if summary.falhas:
        lines.append("\n## Falhas\n")
        for it in summary.falhas:
            lines.append(f"- **{it['codigo']}** — {it.get('nota', '')}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", required=True)
    parser.add_argument("--lookback-days", type=int, default=7)
    parser.add_argument("--dry-run", default="false")
    parser.add_argument("--summary-out", required=True)
    args = parser.parse_args()

    repo_root = Path(args.repo_root).resolve()
    lookback = max(1, min(args.lookback_days, 60))
    dry_run = args.dry_run.lower() in ("1", "true", "yes")

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.FileHandler(repo_root / "_watch_debug.log"),
            logging.StreamHandler(),
        ],
    )
    log = logging.getLogger("watch-reforma")
    log.info("repo_root=%s lookback=%sd dry_run=%s", repo_root, lookback, dry_run)

    catalog, codigos_ja_indexados = load_catalog(repo_root)
    watchlist = load_watchlist(repo_root)
    summary = Summary()

    # 1) Coletar hits das keywords
    seen_titulos: set[str] = set()
    hits: list[Hit] = []
    for kw in KEYWORDS:
        raws = dou_search(kw, lookback, log)
        log.info("DOU '%s' -> %s materias", kw, len(raws))
        for raw in raws:
            h = Hit.from_raw(raw)
            if h is None:
                continue
            if h.titulo in seen_titulos:
                continue
            seen_titulos.add(h.titulo)
            hits.append(h)
        time.sleep(0.5)  # educado com o servidor

    log.info("Hits unicos apos parsing: %s", len(hits))

    # 2) Para cada hit: ja esta no repo? Se sim, pular. Se nao, baixar e converter.
    for h in hits:
        if h.codigo in codigos_ja_indexados:
            summary.ignoradas_ja_no_repo.append({"codigo": h.codigo, "titulo": h.titulo})
            continue

        pasta = repo_root / h.pasta_repo
        if pasta.exists():
            # pasta ja existe no repo mas sem catalogo — tratar como ja indexado
            summary.ignoradas_ja_no_repo.append({"codigo": h.codigo, "titulo": h.titulo, "nota": "pasta ja existe"})
            continue

        pdf_url = resolve_pdf_url(h.url_html, log)
        h.url_pdf = pdf_url
        if not pdf_url:
            summary.detectadas_sem_pdf.append({"codigo": h.codigo, "titulo": h.titulo, "url_html": h.url_html})
            continue

        if dry_run:
            summary.indexadas.append({  # na dry-run reportamos como "indexaria"
                "codigo": h.codigo, "titulo": h.titulo, "url_html": h.url_html,
                "url_pdf": pdf_url, "pasta_repo": h.pasta_repo, "dry_run": True,
            })
            continue

        with tempfile.TemporaryDirectory() as tmp:
            pdf_path = Path(tmp) / f"{h.pasta_repo}.pdf"
            if not download_pdf(pdf_url, pdf_path, log):
                summary.falhas.append({"codigo": h.codigo, "nota": "download do PDF falhou"})
                continue
            # converter manda a saida em `<out>/<slug>/` — usamos a propria pasta destino como parent
            if not run_converter(repo_root, pdf_path, pasta.parent, log):
                summary.falhas.append({"codigo": h.codigo, "nota": "converter.py falhou"})
                continue
            # Alguns conversores geram pasta com nome do PDF; renomear se preciso.
            # (Nosso converter.py gera `<out>/<slug>/`, onde slug e definido pela norma.)
            produced = pasta.parent / h.pasta_repo
            if not produced.exists():
                # tentar achar o unico diretorio novo criado
                candidatos = [p for p in pasta.parent.iterdir() if p.is_dir() and p.name.startswith(h.pasta_repo.split("-")[0])]
                if candidatos:
                    produced = sorted(candidatos, key=lambda p: p.stat().st_mtime)[-1]
                    if produced.name != h.pasta_repo:
                        produced.rename(pasta)
                        produced = pasta
            # copiar o PDF para dentro da pasta final tambem (padrao do repo)
            final_pdf = pasta / f"{h.pasta_repo}.pdf"
            if not final_pdf.exists():
                try:
                    import shutil
                    shutil.copy2(pdf_path, final_pdf)
                except Exception as exc:  # noqa: BLE001
                    log.warning("Nao foi possivel copiar o PDF final: %s", exc)

        # Atualizar catalogo
        catalog["pecas"].append({
            "codigo": h.codigo,
            "titulo": h.titulo,
            "familia": FAMILIA_CATALOGO[h.tipo],
            "ambito": "federal",
            "assunto": ["tributario-federal", "reforma-tributaria"],
            "data": h.data_publicacao or f"{h.ano}-01-01",
            "pasta_repo": h.pasta_repo,
            "situacao": "vigente" if h.tipo != "MP" else "vigente-provisorio",
            "tags": ["reforma-tributaria", "auto-watch"],
            "no_repo": True,
        })
        catalog["pecas"].sort(key=lambda x: x.get("data", "0000"))
        catalog["meta"]["atualizado_em"] = dt.date.today().isoformat()
        summary.indexadas.append({
            "codigo": h.codigo, "titulo": h.titulo, "url_html": h.url_html,
            "url_pdf": pdf_url, "pasta_repo": h.pasta_repo,
        })

    # 3) Persistir estado
    if not dry_run:
        save_catalog(repo_root, catalog)
        regenerate_catalog_md(repo_root, log)
        # atualizar watchlist (todas as detectadas desta rodada)
        watchlist["ultimo_run"] = dt.datetime.utcnow().isoformat() + "Z"
        existentes = {e.get("codigo") for e in watchlist.get("entradas", [])}
        for item in (*summary.indexadas, *summary.detectadas_sem_pdf, *summary.falhas):
            if item["codigo"] in existentes:
                continue
            entry = WatchlistEntry(
                codigo=item["codigo"],
                tipo="",
                pasta_repo=item.get("pasta_repo", ""),
                titulo=item.get("titulo", ""),
                data_publicacao="",
                url_html=item.get("url_html", ""),
                url_pdf=item.get("url_pdf"),
                detectada_em=dt.date.today().isoformat(),
                status=("indexada" if item in summary.indexadas
                        else "falha" if item in summary.falhas
                        else "detectada"),
                nota=item.get("nota", ""),
            )
            watchlist["entradas"].append(asdict(entry))
        save_watchlist(repo_root, watchlist)
        append_history(repo_root, summary)

    # 4) Resumo
    out = Path(args.summary_out)
    lines = [f"# Watch reforma tributaria — {dt.date.today().isoformat()}\n"]
    lines.append(f"- Hits unicos no DOU: {len(hits)}")
    lines.append(f"- Ignoradas (ja no repo): {len(summary.ignoradas_ja_no_repo)}")
    lines.append(f"- Indexadas: {len(summary.indexadas)}")
    lines.append(f"- Detectadas sem PDF resolvivel: {len(summary.detectadas_sem_pdf)}")
    lines.append(f"- Falhas: {len(summary.falhas)}")
    lines.append(f"- Dry-run: {dry_run}\n")

    def _bloco(titulo: str, items: list[dict[str, Any]]) -> None:
        if not items:
            return
        lines.append(f"## {titulo}\n")
        for it in items:
            titulo_curto = (it.get("titulo") or "").strip().replace("\n", " ")[:200]
            codigo = it.get("codigo", "?")
            url = it.get("url_html") or ""
            if url:
                lines.append(f"- **{codigo}** — {titulo_curto}{' ' if titulo_curto else ''}· [materia]({url})")
            else:
                lines.append(f"- **{codigo}** — {titulo_curto}")

    _bloco("Indexadas nesta rodada", summary.indexadas)
    _bloco("Detectadas sem PDF (precisam de atencao manual)", summary.detectadas_sem_pdf)
    _bloco("Falhas", summary.falhas)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")

    (repo_root / "_watch_added.txt").write_text(str(len(summary.indexadas)), encoding="utf-8")
    log.info("fim: %s indexadas, %s ignoradas, %s falhas, %s sem PDF",
             len(summary.indexadas), len(summary.ignoradas_ja_no_repo),
             len(summary.falhas), len(summary.detectadas_sem_pdf))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
