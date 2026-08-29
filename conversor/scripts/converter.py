#!/usr/bin/env python3
"""
converter.py — Converte PDF de legislação brasileira em Markdown estruturado,
otimizado para leitura por LLM e para bases de conhecimento (RAG).

Saídas (em <out>/<slug>/):
  <slug>.md            Markdown limpo e hierarquizado, com âncoras por artigo.
  <slug>.meta.json     Metadados da norma (tipo, número, ano, ementa, fonte, hash).
  <slug>.chunks.jsonl  Um chunk por artigo, auto-contido (para indexação/RAG).
  anexos/anexo_*.csv   Tabelas/anexos grandes exportados em CSV.

Uso:
  python converter.py entrada.pdf --out ./saida
  python converter.py entrada.pdf --out ./saida --ocr auto --csv-threshold-rows 8

Dependências: pymupdf, pdfplumber, pandas; pytesseract + tesseract (com 'por')
para o fallback de OCR de PDFs escaneados.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import unicodedata
from collections import Counter
from dataclasses import dataclass, field, asdict
from pathlib import Path

import pymupdf  # PyMuPDF
import pdfplumber


# ---------------------------------------------------------------------------
# 1. EXTRAÇÃO DE TEXTO (nativo, com fallback de OCR por página)
# ---------------------------------------------------------------------------

def _page_needs_ocr(text: str, min_chars: int = 40) -> bool:
    """Página com quase nenhum texto extraível provavelmente é imagem/escaneada."""
    return len((text or "").strip()) < min_chars


def _ocr_page(page: "pymupdf.Page", lang: str) -> str:
    try:
        import pytesseract
        from PIL import Image
        import io
        pix = page.get_pixmap(dpi=300)
        img = Image.open(io.BytesIO(pix.tobytes("png")))
        return pytesseract.image_to_string(img, lang=lang)
    except Exception as e:  # OCR é best-effort
        sys.stderr.write(f"[aviso] OCR falhou na página: {e}\n")
        return ""


def _best_ocr_lang() -> str:
    """Prefere português; cai para inglês se o pacote 'por' não existir."""
    try:
        import pytesseract
        langs = pytesseract.get_languages(config="")
        return "por" if "por" in langs else "eng"
    except Exception:
        return "eng"


def extract_pages(pdf_path: Path, ocr_mode: str = "auto") -> list[str]:
    """Retorna o texto de cada página, aplicando OCR conforme o modo escolhido."""
    lang = _best_ocr_lang() if ocr_mode != "off" else None
    if ocr_mode != "off" and lang == "eng":
        sys.stderr.write(
            "[aviso] pacote de idioma 'por' do tesseract ausente; "
            "OCR usará 'eng' e a qualidade em português cai. "
            "Instale com: apt-get install tesseract-ocr-por\n"
        )
    pages: list[str] = []
    doc = pymupdf.open(pdf_path)
    try:
        for page in doc:
            text = page.get_text("text")
            do_ocr = ocr_mode == "force" or (ocr_mode == "auto" and _page_needs_ocr(text))
            if do_ocr:
                ocr_text = _ocr_page(page, lang or "eng")
                if len(ocr_text.strip()) > len(text.strip()):
                    text = ocr_text
            pages.append(text)
    finally:
        doc.close()
    return pages


# ---------------------------------------------------------------------------
# 2. LIMPEZA DE RUÍDO (cabeçalho/rodapé repetido, nº de página, hifenização)
# ---------------------------------------------------------------------------

_PAGE_NOISE = [
    re.compile(r"^\s*p[áa]gina\s+\d+\s*(de\s+\d+)?\s*$", re.I),
    re.compile(r"^\s*fls?\.?\s*\d+\s*$", re.I),
    re.compile(r"^\s*\d{1,4}\s*$"),                       # número solto de página
    re.compile(r"^\s*di[áa]rio\s+oficial.*$", re.I),      # boilerplate DOU
    re.compile(r"^\s*imprensa\s+nacional.*$", re.I),
    re.compile(r"^\s*este\s+texto\s+n[ãa]o\s+substitui.*$", re.I),
    re.compile(r"^\s*www\.\S+$", re.I),
]


def _detect_repeated_lines(pages: list[str], band: int = 3, min_ratio: float = 0.5) -> set[str]:
    """Linhas que se repetem no topo/rodapé da maioria das páginas = cabeçalho/rodapé."""
    counter: Counter[str] = Counter()
    n = max(len(pages), 1)
    for text in pages:
        lines = [l.strip() for l in text.splitlines() if l.strip()]
        for l in lines[:band] + lines[-band:]:
            if 3 <= len(l) <= 120:
                counter[l] += 1
    # Só é cabeçalho/rodapé se aparece em PELO MENOS 2 páginas E na maioria delas.
    # (Sem o c >= 2, num doc de 2 páginas toda linha de banda de uma página seria
    #  apagada — inclusive a epígrafe e artigos no limite entre páginas.)
    return {line for line, c in counter.items() if c >= 2 and c / n >= min_ratio}


def clean_text(pages: list[str]) -> str:
    repeated = _detect_repeated_lines(pages)
    kept: list[str] = []
    for text in pages:
        for raw in text.splitlines():
            line = raw.rstrip()
            stripped = line.strip()
            if not stripped:
                kept.append("")
                continue
            if stripped in repeated:
                continue
            if any(rx.match(stripped) for rx in _PAGE_NOISE):
                continue
            kept.append(line)
    joined = "\n".join(kept)
    # De-hifenização: "traba-\nlho" -> "trabalho"
    joined = re.sub(r"(\w)-\n(\w)", r"\1\2", joined)
    # Junta quebras dentro do mesmo parágrafo, preservando quebras estruturais.
    joined = _rejoin_soft_breaks(joined)
    # Normaliza espaços múltiplos e linhas em branco excessivas.
    joined = re.sub(r"[ \t]+", " ", joined)
    joined = re.sub(r"\n{3,}", "\n\n", joined)
    return joined.strip()


# Marcadores que SEMPRE iniciam nova unidade estrutural (não juntar com a linha anterior).
_STRUCT_START = re.compile(
    r"^\s*("
    r"LIVRO|T[ÍI]TULO|CAP[ÍI]TULO|SE[ÇC][ÃA]O|SUBSE[ÇC][ÃA]O|"          # divisões
    r"Art\.?\s*\d|Artigo\s*\d|"                                          # artigo
    r"§\s*\d|Par[áa]grafo\s+[úu]nico|"                                    # parágrafo
    r"[IVXLCDM]{1,6}\s*[-–—]\s|"                                          # inciso
    r"[a-z]\)\s|"                                                         # alínea
    r"\d{1,2}\)\s"                                                        # item
    r")",
    re.I,
)


def _rejoin_soft_breaks(text: str) -> str:
    """Junta linhas que foram quebradas no meio de um parágrafo (não estruturais)."""
    out: list[str] = []
    for line in text.splitlines():
        s = line.strip()
        if not s:
            out.append("")
            continue
        if out and out[-1] and not _STRUCT_START.match(s) and not out[-1].endswith((".", ":", ";")):
            # continuação do parágrafo anterior
            out[-1] = out[-1] + " " + s
        else:
            out.append(s)
    return "\n".join(out)


# ---------------------------------------------------------------------------
# 3. METADADOS DA NORMA
# ---------------------------------------------------------------------------

_TIPOS = {
    "LEI COMPLEMENTAR": "LC", "EMENDA CONSTITUCIONAL": "EC",
    "MEDIDA PROVISÓRIA": "MP", "INSTRUÇÃO NORMATIVA": "IN",
    "LEI": "Lei", "DECRETO-LEI": "Decreto-Lei", "DECRETO": "Decreto",
    "PORTARIA": "Portaria", "RESOLUÇÃO": "Resolução",
    "CONSTITUIÇÃO": "Constituição",
}

_NUM_RX = re.compile(r"n[º°o]?\.?\s*([\d][\d\.]*)", re.I)
_ANO_RX = re.compile(r"\b(19|20)\d{2}\b")


def detect_metadata(text: str, pdf_path: Path) -> dict:
    head = "\n".join(text.splitlines()[:15]).upper()
    tipo = next((v for k, v in _TIPOS.items() if k in head), None)
    num = None
    m = _NUM_RX.search(head)
    if m:
        num = m.group(1).replace(".", "")
    anos = _ANO_RX.findall(text[:1200])
    ano = None
    m2 = _ANO_RX.search(text[:1200])
    if m2:
        ano = m2.group(0)
    # Ementa: no layout do Planalto, o topo traz navegação ("Presidência da República",
    # "Mensagem de veto", "Texto compilado", "(Vide ...)") antes da ementa real, que
    # começa com um verbo típico (Institui, Dispõe, Altera...).
    nav = re.compile(
        r"^(Presid[êe]ncia|Casa Civil|Secretaria|Subchefia|Mensagem de veto|"
        r"Produ[çc][ãa]o de efeitos|Texto compilado|Vig[êe]ncia|\(Promulga[çc][ãa]o|"
        r"\(Vide|LEI COMPLEMENTAR|LEI |DECRETO|MEDIDA PROVIS)", re.I)
    ementa_start = re.compile(
        r"^(Institui|Disp[õo]e|Altera|Regulamenta|Estabelece|Cria|Aprova|Define|"
        r"Reduz|Concede|Autoriza|Fixa|Revoga|Acresce|Consolida)", re.I)
    ementa = None
    for para in text.split("\n"):
        p = para.strip()
        if ementa_start.match(p) and len(p) > 40:
            ementa = p
            break
    if not ementa:  # fallback: primeira linha substancial que não é navegação/upper
        for para in text.split("\n"):
            p = para.strip()
            if len(p) > 60 and not nav.match(p) and not _STRUCT_START.match(p) and not p.isupper():
                ementa = p
                break
    sha = hashlib.sha256(pdf_path.read_bytes()).hexdigest()[:16]
    return {
        "tipo": tipo,
        "numero": num,
        "ano": ano,
        "identificador": _norma_id(tipo, num, ano, pdf_path),
        "ementa": ementa,
        "fonte_arquivo": pdf_path.name,
        "sha256_16": sha,
    }


def _norma_id(tipo, num, ano, pdf_path: Path) -> str:
    if tipo and num:
        base = f"{tipo} {num}" + (f"/{ano}" if ano else "")
        return base
    return pdf_path.stem


def slugify(value: str) -> str:
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    value = value.replace("/", "-")  # "LC 214/2025" -> "lc-214-2025", não "lc-2142025"
    value = re.sub(r"[^\w\s-]", "", value).strip().lower()
    return re.sub(r"[\s_]+", "-", value) or "norma"


# ---------------------------------------------------------------------------
# 4. PARSE DA ESTRUTURA HIERÁRQUICA
# ---------------------------------------------------------------------------

RX_DIVISAO = re.compile(
    r"^(LIVRO|T[ÍI]TULO|CAP[ÍI]TULO|SE[ÇC][ÃA]O|SUBSE[ÇC][ÃA]O)\b(.*)$", re.I
)
# Cabeçalho de artigo: exige "Art."/"Artigo" com A MAIÚSCULO. Referências no corpo
# ("o art. 14 desta Lei", "do art. 195 da Constituição") usam minúscula e NÃO devem
# ser confundidas com o início de um novo artigo.
RX_ARTIGO = re.compile(r"^(?:Art\.|Artigo)\s*(\d+[ºo]?(?:-[A-Z])?)\s*[\.\-–—]?\s*(.*)$")
# Se o texto após o número começa com um conector em minúscula, é referência/fragmento,
# não um caput de artigo (que sempre começa com maiúscula).
RX_REF_TAIL = re.compile(r"^[a-zà-ú]")
RX_NOTA = re.compile(r"\((?:Reda[çc][ãa]o|Revogad|Inclu[íi]d|Vide|Vigência)[^)]*\)")
RX_REF = re.compile(r"art(?:igo|\.)?\s*(\d+[ºo]?(?:-[A-Z])?)", re.I)
# Anexos são terminais na norma; dali em diante o texto vira material de anexo
# (as tabelas já são capturadas em CSV pelo pdfplumber).
RX_ANEXO = re.compile(r"^ANEXO\b", re.I)
# Sub-unidades do artigo, para formatação em lista no Markdown.
RX_PARAG = re.compile(r"^(§\s*\d+[ºo]?|Par[áa]grafo\s+[úu]nico)\.?\s*(.*)$", re.I)
RX_INCISO = re.compile(r"^([IVXLCDM]{1,6})\s*[-–—]\s*(.*)$")
RX_ALINEA = re.compile(r"^([a-z])\)\s*(.*)$")
RX_ITEM = re.compile(r"^(\d{1,2})\)\s*(.*)$")

_NIVEL_DIV = {"LIVRO": 1, "TÍTULO": 2, "TITULO": 2, "CAPÍTULO": 3, "CAPITULO": 3,
              "SEÇÃO": 4, "SECÇÃO": 4, "SECAO": 4, "SEÇAO": 4,
              "SUBSEÇÃO": 5, "SUBSECÇÃO": 5, "SUBSECAO": 5}


def _crumb_level(part: str) -> int:
    """Nível de cabeçalho Markdown p/ uma divisão (abaixo do H1 do título)."""
    palavra = part.split()[0].upper() if part.split() else ""
    return min(_NIVEL_DIV.get(palavra, 3) + 1, 6)


@dataclass
class Artigo:
    numero: str
    texto: str
    breadcrumb: str
    notas: list[str] = field(default_factory=list)
    refs: list[str] = field(default_factory=list)
    anexos: list[str] = field(default_factory=list)
    redacao_anterior: bool = False   # redação superada (texto compilado mostra a antiga)


@dataclass
class Documento:
    divisoes_render: list[tuple[int, str]] = field(default_factory=list)
    artigos: list[Artigo] = field(default_factory=list)


def _norm_art(num: str) -> str:
    return re.sub(r"[ºo]", "", num).strip()


def _norm_ref(num: str) -> str:
    return "art-" + _norm_art(num)


def art_display(num_norm: str) -> str:
    """1 -> 1º, 9 -> 9º, 10 -> 10, 3-A -> 3º-A (convenção da LC 95/1998)."""
    m = re.match(r"(\d+)(-[A-Z])?$", num_norm)
    if not m:
        return num_norm
    n, suf = m.group(1), m.group(2) or ""
    return f"{n}º{suf}" if int(n) <= 9 else f"{n}{suf}"


def parse_structure(text: str) -> Documento:
    doc = Documento()
    breadcrumb: dict[int, str] = {}
    cur: Artigo | None = None

    def flush():
        nonlocal cur
        if cur is not None:
            cur.texto = cur.texto.strip()
            cur.notas = RX_NOTA.findall(cur.texto)
            refs = {_norm_ref(r) for r in RX_REF.findall(cur.texto)}
            refs.discard(_norm_ref(cur.numero))
            cur.refs = sorted(refs)
            doc.artigos.append(cur)
            cur = None

    in_anexo = False
    for line in text.splitlines():
        s = line.strip()
        if not s:
            if cur and not in_anexo:
                cur.texto += "\n"
            continue
        if RX_ANEXO.match(s):
            flush()
            in_anexo = True
            continue
        if in_anexo:
            if RX_ARTIGO.match(s) or RX_DIVISAO.match(s):
                in_anexo = False
            else:
                continue
        mdiv = RX_DIVISAO.match(s)
        if mdiv and len(s) < 120:
            flush()
            palavra = mdiv.group(1).upper()
            nivel = _NIVEL_DIV.get(palavra, 3)
            breadcrumb = {k: v for k, v in breadcrumb.items() if k < nivel}
            breadcrumb[nivel] = s
            doc.divisoes_render.append((nivel, s))
            continue
        mart = RX_ARTIGO.match(s)
        if mart:
            resto = (mart.group(2) or "").strip()
            # Referência cruzada ("art. 14 desta Lei") disfarçada de cabeçalho: o texto
            # após o número começa em minúscula. Trata como corpo do artigo atual.
            if resto and RX_REF_TAIL.match(resto):
                if cur is not None:
                    cur.texto += ("\n" + s)
                continue
            flush()
            crumb = " > ".join(breadcrumb[k] for k in sorted(breadcrumb))
            cur = Artigo(numero=_norm_art(mart.group(1)), texto=resto, breadcrumb=crumb)
            continue
        if cur is not None:
            cur.texto += ("\n" + s)
    flush()

    # Supersessão de redação: no "Texto compilado" o Planalto mostra a redação anterior
    # e a vigente do mesmo artigo. A vigente é a última ocorrência (a que traz a nota
    # "(Redação dada por...)"); as anteriores ficam marcadas como redacao_anterior.
    from collections import defaultdict
    posicoes: dict[str, list[int]] = defaultdict(list)
    for i, a in enumerate(doc.artigos):
        posicoes[a.numero].append(i)
    for numero, pos in posicoes.items():
        if len(pos) > 1:
            com_nota = [p for p in pos if doc.artigos[p].notas]
            vigente = com_nota[-1] if com_nota else pos[-1]
            for p in pos:
                if p != vigente:
                    doc.artigos[p].redacao_anterior = True
    return doc


def split_subunits(texto: str):
    """Separa o caput do artigo de suas sub-unidades (§, incisos, alíneas, itens)."""
    caput_parts: list[str] = []
    unidades: list[tuple[int, str, str]] = []
    started = False
    for raw in texto.splitlines():
        s = raw.strip()
        if not s:
            continue
        for rx, nivel in ((RX_PARAG, 1), (RX_INCISO, 2), (RX_ALINEA, 3), (RX_ITEM, 4)):
            m = rx.match(s)
            if m:
                unidades.append((nivel, m.group(1).strip(), m.group(2).strip()))
                started = True
                break
        else:
            if started and unidades:
                lvl, rot, cont = unidades[-1]
                unidades[-1] = (lvl, rot, (cont + " " + s).strip())
            else:
                caput_parts.append(s)
    return " ".join(caput_parts).strip(), unidades


def body_to_markdown(texto: str) -> str:
    caput, unidades = split_subunits(texto)
    out = [caput] if caput else []
    indent = {1: "", 2: "  ", 3: "    ", 4: "      "}
    for nivel, rotulo, cont in unidades:
        if nivel == 1:
            label = f"**{rotulo}**" if rotulo.startswith("§") else f"**{rotulo}.**"
            out.append(f"\n{label} {cont}".rstrip())
        else:
            out.append(f"{indent[nivel]}- {rotulo}) {cont}" if nivel in (3, 4)
                       else f"{indent[nivel]}- {rotulo} – {cont}")
    return "\n".join(out).strip()


def body_to_text(texto: str) -> str:
    caput, unidades = split_subunits(texto)
    lines = [caput] if caput else []
    for nivel, rotulo, cont in unidades:
        if nivel in (3, 4):
            sep = ")"
        elif nivel == 2:
            sep = " –"
        elif rotulo.startswith("§"):
            sep = ""
        else:
            sep = "."
        lines.append(f"{rotulo}{sep} {cont}".strip())
    return "\n".join(lines).strip()


def extract_tables(pdf_path: Path, out_dir: Path, threshold_rows: int, threshold_cols: int = 3):
    """Extrai tabelas; grandes -> CSV, pequenas -> markdown inline."""
    import pandas as pd
    csvs: list[dict] = []
    inline: list[dict] = []
    anexos_dir = out_dir / "anexos"
    idx = 0
    with pdfplumber.open(pdf_path) as pdf:
        for pageno, page in enumerate(pdf.pages, 1):
            for tbl in page.extract_tables() or []:
                if not tbl or len(tbl) < 2:
                    continue
                rows = [[(c or "").strip() for c in row] for row in tbl]
                header, *body = rows
                ncols = max(len(r) for r in rows)
                if len(body) >= threshold_rows or (ncols >= threshold_cols and len(body) >= 4):
                    idx += 1
                    anexos_dir.mkdir(parents=True, exist_ok=True)
                    fname = f"anexo_{idx:02d}.csv"
                    df = pd.DataFrame(body, columns=[h or f"col{i}" for i, h in enumerate(header)])
                    df.to_csv(anexos_dir / fname, index=False)
                    csvs.append({"arquivo": f"anexos/{fname}", "linhas": len(body),
                                 "colunas": ncols, "pagina": pageno,
                                 "cabecalho": [h for h in header if h]})
                else:
                    inline.append({"pagina": pageno, "rows": rows})
    return csvs, inline


def _md_table(rows: list[list[str]]) -> str:
    if not rows:
        return ""
    header, body = rows[0], rows[1:]
    out = ["| " + " | ".join(header) + " |",
           "| " + " | ".join("---" for _ in header) + " |"]
    for r in body:
        r = r + [""] * (len(header) - len(r))
        out.append("| " + " | ".join(r[:len(header)]) + " |")
    return "\n".join(out)


def render_markdown(meta: dict, doc: Documento, csvs: list[dict], inline: list[dict]) -> str:
    out: list[str] = ["---"]
    for k in ("identificador", "tipo", "numero", "ano", "fonte_arquivo", "sha256_16"):
        if meta.get(k):
            out.append(f"{k}: {json.dumps(meta[k], ensure_ascii=False)}")
    if meta.get("ementa"):
        out.append(f"ementa: {json.dumps(meta['ementa'], ensure_ascii=False)}")
    out.append("---\n")
    out.append(f"# {meta.get('identificador','Norma')}\n")
    if meta.get("ementa"):
        out.append(f"> {meta['ementa']}\n")

    if csvs:
        out.append("## Anexos e tabelas\n")
        for c in csvs:
            cab = ", ".join(c["cabecalho"][:6]) if c["cabecalho"] else "—"
            out.append(f"- **Anexo {Path(c['arquivo']).stem.split('_')[-1]}** "
                       f"({c['linhas']} linhas · p. {c['pagina']}) → `{c['arquivo']}`  \n"
                       f"  Colunas: {cab}")
        out.append("")

    last_parts: list[str] = []
    ant_n = 0
    for art in doc.artigos:
        if art.redacao_anterior:
            ant_n += 1
            anchor = f"{_norm_ref(art.numero)}--anterior-{ant_n:03d}"
        else:
            anchor = _norm_ref(art.numero)
        parts = art.breadcrumb.split(" > ") if art.breadcrumb else []
        i = 0
        while i < len(parts) and i < len(last_parts) and parts[i] == last_parts[i]:
            i += 1
        if parts[i:]:
            out.append("")
            for part in parts[i:]:
                out.append(f"{'#' * _crumb_level(part)} {part}")
        last_parts = parts
        out.append(f'\n<a id="{anchor}"></a>')
        body = body_to_markdown(art.texto)
        if art.redacao_anterior:
            out.append(f"> _(Art. {art_display(art.numero)} — redação anterior, superada)_  \n> {body}".strip())
        else:
            out.append(f"**Art. {art_display(art.numero)}.** {body}".strip())

    for t in inline:
        out.append(f"\n> Tabela (p. {t['pagina']}):\n")
        out.append(_md_table(t["rows"]))
    return "\n".join(out).strip() + "\n"


def render_chunks(meta: dict, doc: Documento, csvs: list[dict]) -> str:
    lines: list[str] = []
    norma = meta.get("identificador", meta.get("fonte_arquivo"))
    anexos_all = [c["arquivo"] for c in csvs]
    ant_counter = 0
    for art in doc.artigos:
        disp = art_display(art.numero)
        if art.redacao_anterior:
            ant_counter += 1
            chunk_id = f"{slugify(str(norma))}--{_norm_ref(art.numero)}--anterior-{ant_counter:03d}"
        else:
            chunk_id = f"{slugify(str(norma))}--{_norm_ref(art.numero)}"
        chunk = {
            "id": chunk_id,
            "norma": norma,
            "tipo": meta.get("tipo"),
            "path": (art.breadcrumb + " > " if art.breadcrumb else "") + f"Art. {disp}",
            "artigo": art.numero,
            "vigente": not art.redacao_anterior,
            "texto": f"Art. {disp}. {body_to_text(art.texto)}".strip(),
            "notas_vigencia": art.notas,
            "refs": art.refs,
            "anexos": anexos_all,
            "fonte": meta.get("fonte_arquivo"),
        }
        lines.append(json.dumps(chunk, ensure_ascii=False))
    return "\n".join(lines) + ("\n" if lines else "")


def convert(pdf_path: Path, out_root: Path, ocr_mode: str, threshold_rows: int) -> dict:
    pages = extract_pages(pdf_path, ocr_mode)
    text = clean_text(pages)
    meta = detect_metadata(text, pdf_path)
    slug = slugify(str(meta["identificador"]))
    out_dir = out_root / slug
    out_dir.mkdir(parents=True, exist_ok=True)

    csvs, inline = extract_tables(pdf_path, out_dir, threshold_rows)
    doc = parse_structure(text)

    (out_dir / f"{slug}.md").write_text(render_markdown(meta, doc, csvs, inline), encoding="utf-8")
    (out_dir / f"{slug}.chunks.jsonl").write_text(render_chunks(meta, doc, csvs), encoding="utf-8")
    n_ant = sum(1 for a in doc.artigos if a.redacao_anterior)
    (out_dir / f"{slug}.meta.json").write_text(
        json.dumps({**meta, "n_artigos": len(doc.artigos),
                    "n_artigos_vigentes": len(doc.artigos) - n_ant,
                    "n_redacoes_anteriores": n_ant,
                    "n_anexos_csv": len(csvs), "n_paginas": len(pages)},
                   ensure_ascii=False, indent=2), encoding="utf-8")

    return {"slug": slug, "out_dir": str(out_dir), "artigos": len(doc.artigos),
            "vigentes": len(doc.artigos) - n_ant, "redacoes_anteriores": n_ant,
            "anexos_csv": len(csvs), "tabelas_inline": len(inline), "paginas": len(pages),
            "meta": meta}


def main():
    ap = argparse.ArgumentParser(description="Converte PDF de legislação em Markdown/JSONL/CSV para RAG.")
    ap.add_argument("pdf", type=Path)
    ap.add_argument("--out", type=Path, default=Path("./saida"))
    ap.add_argument("--ocr", choices=["auto", "force", "off"], default="auto")
    ap.add_argument("--csv-threshold-rows", type=int, default=8)
    args = ap.parse_args()
    if not args.pdf.exists():
        sys.exit(f"Arquivo não encontrado: {args.pdf}")
    res = convert(args.pdf, args.out, args.ocr, args.csv_threshold_rows)
    print(json.dumps(res, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
