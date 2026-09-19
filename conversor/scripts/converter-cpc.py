#!/usr/bin/env python3
"""
converter-cpc.py — Converte PDF de Pronunciamento Técnico CPC / NBC TG em Markdown
estruturado + chunks JSONL + metadata, para RAG.

Diferente do converter.py (que atende legislação: Lei, LC, Decreto, IN, MP),
este script trata a estrutura própria de pronunciamentos do Comitê de Pronunciamentos
Contábeis (CPC) e das NBC TG do CFC:

  - Header: "PRONUNCIAMENTO TÉCNICO CPC XX (RN)" (não "LEI Nº X, DE...")
  - Unidade semântica: ITEM NUMERADO ("1.", "2.", ..., "129.", "B15.") — não "Art."
  - Anexos: "Apêndice A", "Apêndice B" — não "ANEXO I"
  - Correlação IFRS declarada explicitamente
  - Seções em MAIÚSCULO (OBJETIVO, ALCANCE, RECONHECIMENTO, MENSURAÇÃO, DIVULGAÇÃO)

Saídas (em <out>/<slug>/):
  <slug>.md            Markdown com âncoras por item, sub-alíneas formatadas
  <slug>.meta.json     tipo=CPC, numero, revisao, correlacao_ifrs, ementa (objetivo)
  <slug>.chunks.jsonl  1 chunk por item, com path (seção > item), texto e refs
  anexos/anexo_*.csv   tabelas grandes em CSV

Uso:
  python converter-cpc.py "pdf-do-pronunciamento.pdf" --out ./saida
  python converter-cpc.py entrada.pdf --out ./saida --ocr auto

Dependências: pymupdf, pdfplumber, pandas (mesmas do converter.py).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import pymupdf
import pdfplumber


# ---------------------------------------------------------------------------
# 1. EXTRAÇÃO DE TEXTO (idêntico ao converter.py — mantém compatibilidade)
# ---------------------------------------------------------------------------

def _page_needs_ocr(text: str, min_chars: int = 40) -> bool:
    return len((text or "").strip()) < min_chars


def _ocr_page(page: "pymupdf.Page", lang: str) -> str:
    try:
        import pytesseract
        from PIL import Image
        import io
        pix = page.get_pixmap(dpi=300)
        img = Image.open(io.BytesIO(pix.tobytes("png")))
        return pytesseract.image_to_string(img, lang=lang)
    except Exception as e:
        sys.stderr.write(f"[aviso] OCR falhou na página: {e}\n")
        return ""


def _best_ocr_lang() -> str:
    try:
        import pytesseract
        langs = pytesseract.get_languages(config="")
        return "por" if "por" in langs else "eng"
    except Exception:
        return "eng"


def extract_pages(pdf_path: Path, ocr_mode: str = "auto") -> list[str]:
    lang = _best_ocr_lang() if ocr_mode != "off" else None
    if ocr_mode != "off" and lang == "eng":
        sys.stderr.write(
            "[aviso] pacote de idioma 'por' do tesseract ausente; "
            "OCR usará 'eng' e a qualidade em português cai.\n"
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
# 2. LIMPEZA DE RUÍDO
# ---------------------------------------------------------------------------

_PAGE_NOISE = [
    re.compile(r"^\s*p[áa]gina\s+\d+\s*(de\s+\d+)?\s*$", re.I),
    re.compile(r"^\s*\d{1,4}\s*$"),
    re.compile(r"^\s*www\.\S+$", re.I),
    # Ruído típico de PDFs do CPC:
    re.compile(r"^\s*comit[êe]\s+de\s+pronunciamentos?\s+cont[áa]beis?\s*$", re.I),
    re.compile(r"^\s*CPC\s+\d+.*p[áa]gina.*\d+.*$", re.I),
]


def _detect_repeated_lines(pages: list[str], band: int = 3, min_ratio: float = 0.5) -> set[str]:
    counter: Counter[str] = Counter()
    n = max(len(pages), 1)
    for text in pages:
        lines = [l.strip() for l in text.splitlines() if l.strip()]
        for l in lines[:band] + lines[-band:]:
            if 3 <= len(l) <= 120:
                counter[l] += 1
    return {line for line, c in counter.items() if c >= 2 and c / n >= min_ratio}


# Marcadores estruturais de CPC: seções em MAIÚSCULO, itens numerados, alíneas.
_STRUCT_START_CPC = re.compile(
    r"^\s*("
    r"[A-ZÁÉÍÓÚÂÊÔÃÕÇ][A-ZÁÉÍÓÚÂÊÔÃÕÇ\s\-]{3,}\s*$|"   # linha só em maiúsculo (seção)
    r"AP[ÊE]NDICE\s+[A-Z]|"                                # apêndice
    r"\d+[A-Z]?\.\s|"                                      # item numerado (1., 129., 112A.)
    r"[A-Z]\d+[A-Z]?\.\s|"                                 # item de apêndice (B1., B15.)
    r"\([a-z]\)\s"                                         # alínea
    r")",
)


def _rejoin_soft_breaks(text: str) -> str:
    out: list[str] = []
    for line in text.splitlines():
        s = line.strip()
        if not s:
            out.append("")
            continue
        if out and out[-1] and not _STRUCT_START_CPC.match(s) and not out[-1].endswith((".", ":", ";")):
            out[-1] = out[-1] + " " + s
        else:
            out.append(s)
    return "\n".join(out)


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
    joined = re.sub(r"(\w)-\n(\w)", r"\1\2", joined)
    # Padrão CPC: itens vêm quebrados como "1.\n\nO objetivo..." — juntar o "N."
    # sozinho com o próximo parágrafo não-vazio.
    joined = _merge_orphan_numbers(joined)
    joined = _merge_uppercase_titles(joined)
    joined = _rejoin_soft_breaks(joined)
    joined = re.sub(r"[ \t]+", " ", joined)
    joined = re.sub(r"\n{3,}", "\n\n", joined)
    return joined.strip()


def _merge_uppercase_titles(text: str) -> str:
    """Junta linhas MAIÚSCULAS consecutivas em um único título.

    Títulos longos de seção no PDF quebram em duas ou mais linhas curtas em CAIXA ALTA:
        APRESENTAÇÃO DOS FLUXOS DE CAIXA DAS ATIVIDADES DE
        INVESTIMENTO E DE FINANCIAMENTO
    Sem esse merge, cada linha vira uma "seção" distinta e o detector se perde.
    Só mescla quando ambas as linhas: (a) são >=3 chars, (b) estão em CAIXA ALTA
    (permitindo dígitos, hífen, espaço, cedilha, acentos), (c) nenhuma delas
    termina em ponto/vírgula (que indicariam frase).
    """
    lines = text.splitlines()
    is_title_line = re.compile(
        r"^[A-ZÁÉÍÓÚÂÊÔÃÕÇ][A-ZÁÉÍÓÚÂÊÔÃÕÇ0-9\s\-]{2,}$"
    )
    # Detecta espaçamento decorativo: "M O D E L O S", "P L A N O S"
    # (letras isoladas separadas por espaço, com pelo menos 3 letras)
    is_spaced_title = re.compile(r"^(?:[A-ZÁÉÍÓÚÂÊÔÃÕÇ]\s+){2,}[A-ZÁÉÍÓÚÂÊÔÃÕÇ]$")
    out: list[str] = []
    i = 0
    while i < len(lines):
        cur = lines[i].rstrip()
        stripped = cur.strip()
        # Normalizar espaçamento decorativo antes das outras checagens
        if is_spaced_title.match(stripped):
            stripped = re.sub(r"\s+", "", stripped)
            cur = stripped
        # Ignora linhas com pontuação de fim (não são pedaço de título)
        if (
            stripped
            and is_title_line.match(stripped)
            and not stripped.endswith((".", ",", ":", ";"))
            and len(stripped) <= 80
        ):
            merged = stripped
            j = i + 1
            # Mescla linhas em branco não contam; mas para o merge exigimos
            # linhas ADJACENTES (título quebrado geralmente é linha seguinte)
            while j < len(lines):
                nxt = lines[j].strip()
                if not nxt:
                    break
                if (
                    is_title_line.match(nxt)
                    and not nxt.endswith((".", ",", ":", ";"))
                    and len(nxt) <= 80
                ):
                    merged += " " + nxt
                    j += 1
                    continue
                break
            if j > i + 1:
                out.append(merged)
                i = j
                continue
        out.append(cur)
        i += 1
    return "\n".join(out)


def _merge_orphan_numbers(text: str) -> str:
    """Junta linha só com 'N.', 'N.º', ou 'N.M.P' (hierárquico) com a próxima linha não-vazia."""
    lines = text.splitlines()
    out: list[str] = []
    i = 0
    # Formato simples: "1.", "129.", "112A."
    orphan_rx = re.compile(r"^(\d+[A-Z]?)\.\s*$")
    # Formato hierárquico: "2.4", "3.3.1", "6.5.11" (SEM ponto no final)
    orphan_hier_rx = re.compile(r"^(\d+(?:\.\d+)+[A-Z]?)\s*$")
    # Formato apêndice: "B1.", "B15A.", "B5.4"
    orphan_apx_rx = re.compile(r"^([A-Z])\.?(\d+(?:\.\d+)*[A-Z]?)\.?\s*$")
    while i < len(lines):
        s = lines[i].strip()
        m = orphan_rx.match(s) or orphan_hier_rx.match(s) or orphan_apx_rx.match(s)
        if m and len(s) <= 12:  # limite pra evitar falsos positivos (linhas curtas)
            j = i + 1
            while j < len(lines) and not lines[j].strip():
                j += 1
            if j < len(lines):
                out.append(f"{s} {lines[j].strip()}")
                i = j + 1
                continue
        out.append(lines[i])
        i += 1
    return "\n".join(out)


# ---------------------------------------------------------------------------
# 3. METADADOS DO PRONUNCIAMENTO
# ---------------------------------------------------------------------------

# Header: "PRONUNCIAMENTO TÉCNICO CPC 47" ou "PRONUNCIAMENTO TÉCNICO CPC 00 (R2)"
_RX_HEADER = re.compile(
    r"PRONUNCIAMENTO\s+T[ÉE]CNICO\s+CPC\s+(\d+)(?:\s*\(R(\d+)\))?",
    re.I,
)
# NBC TG: "NBC TG 47" ou "NBC TG 00 (R2)"
_RX_HEADER_NBC = re.compile(
    r"NBC\s+TG\s+(\d+)(?:\s*\(R(\d+)\))?",
    re.I,
)
# Correlação IFRS
_RX_IFRS = re.compile(
    r"Correla[çc][ãa]o\s+[àa]s?\s+Normas.*?(IAS|IFRS|IFRIC|SIC)\s+(\d+)",
    re.I | re.DOTALL,
)


_TITLE_LOWER = {"a", "à", "as", "às", "ao", "aos", "com", "da", "das", "de", "do", "dos",
                "e", "em", "na", "nas", "no", "nos", "o", "os", "ou", "para", "por",
                "que", "sem", "sob", "sobre"}


def _pt_title_case(s: str) -> str:
    """Title case em português: preposições e artigos ficam em minúsculas."""
    words = s.strip().split()
    if not words:
        return s
    out = [words[0].capitalize()]
    for w in words[1:]:
        out.append(w.lower() if w.lower() in _TITLE_LOWER else w.capitalize())
    return " ".join(out)


_TITULO_BLOCK_PREFIXES = (
    "Correla", "IFRS", "IAS", "COMIT", "Este material", "Termos", "Os pronunc",
    "Pronunciamentos", "República", "Federativa", "Notice", "Reproduced",
    "CPC/CPC", "Committee", "Support", "Foundation", "Accounting",
    "Pronounc", "* ", "de outras partes", "deverá ser", "são emitidos",
    "não devem ser", "não foram", "contém material", "in respect", "This material",
    "Todos esses", "organismo",
)


def _extract_title(head_text: str, header_match_end: int) -> str | None:
    """Extrai o título do pronunciamento após o header.

    Tenta, em ordem: (1) uma linha em CAIXA ALTA (padrão antigo, ex: CPC 47);
    (2) linha em Title Case curta (padrão dos CPCs de estrutura mais enxuta,
    ex: 'Estoques' no CPC 16); (3) linha longa em Title Case (fallback).
    """
    tail = head_text[header_match_end:header_match_end + 800]
    # Passo 1: procurar CAIXA ALTA
    for line in tail.splitlines():
        s = line.strip()
        if not s:
            continue
        if s.isupper() and 5 <= len(s) <= 150 and not any(x in s for x in ("CORRELA", "IFRS", "IAS")):
            return _pt_title_case(s)
        # Se já cruzou uma linha significativa não-UPPER, para o passo 1
        if len(s) > 40:
            break
    # Passo 2: título curto em Title Case ("Estoques", "Impairment", "Combinação de Negócios")
    for line in tail.splitlines():
        s = line.strip()
        if not s:
            continue
        if s.startswith(_TITULO_BLOCK_PREFIXES):
            continue
        if 3 <= len(s) <= 60 and s[0].isupper() and not s.endswith(".") and not s.endswith(","):
            # Não pode conter dígitos de artigo ou ser algo estruturado
            if not re.match(r"^\d", s) and not s.startswith("("):
                return s
    # Passo 3: fallback antigo — linha longa em Title Case
    for line in tail.splitlines():
        s = line.strip()
        if not s or s.startswith(_TITULO_BLOCK_PREFIXES):
            continue
        if len(s) > 15:
            words = s.split()
            if len(words) >= 3 and sum(1 for w in words if w[0].isupper()) >= len(words) * 0.6:
                return s
    return None


def _extract_nbc_titulo(text: str, numero: str) -> str | None:
    """Título da NBC TG vem depois em linha 'NBC TG XXXX – TÍTULO EM MAIÚSCULO'."""
    # Espaço literal (não \s) pra parar em quebra de linha; máx 100 chars
    m = re.search(
        rf"NBC\s+TG\s+{re.escape(numero)}\s*[–\-—]\s*([A-ZÁÉÍÓÚÂÊÔÃÕÇ][A-ZÁÉÍÓÚÂÊÔÃÕÇ ,]{{5,100}})",
        text,
    )
    if m:
        return _pt_title_case(m.group(1).strip().rstrip(","))
    return None


def _extract_ementa_nbc(text: str) -> str | None:
    """Ementa NBC vem da linha 'Aprova a NBC TG XXXX, que dispõe sobre...'."""
    m = re.search(
        r"Aprova\s+a\s+NBC\s+TG\s+\d+[,]?\s*(?:que\s+)?(disp[õo]e\s+sobre[^.]+\.)",
        text, re.IGNORECASE | re.DOTALL,
    )
    if m:
        return re.sub(r"\s+", " ", m.group(1).strip())
    return None


def _extract_objetivo(text: str) -> str | None:
    """O item 1 do CPC tipicamente enuncia o objetivo — funciona como ementa."""
    # Buscar padrão "OBJETIVO\n1. ..." ou logo o "1. " após o header
    m = re.search(r"^\s*OBJETIVO\s*$", text, re.MULTILINE)
    if m:
        after = text[m.end():m.end() + 2000]
        # próximo bloco não-vazio começando com "1."
        m2 = re.search(r"^\s*1\.\s+(.+?)(?=^\s*(?:2\.|[A-Z]{4,})\s)", after, re.MULTILINE | re.DOTALL)
        if m2:
            texto = m2.group(1).strip()
            return re.sub(r"\s+", " ", texto)[:500]
    # Fallback: primeiro item "1. ..." após o header — para no próximo item, alínea,
    # linha em title case iniciando outra seção, ou linha em CAIXA ALTA
    m = re.search(
        r"^\s*1\.\s+(.{40,600}?)(?=\n\s*(?:2\.|\(a\)|[A-Z][a-záéíóúãõç]+\s*$|[A-ZÁÉÍÓÚÂÊÔÃÕÇ ]{3,}$))",
        text, re.MULTILINE | re.DOTALL,
    )
    if m:
        return re.sub(r"\s+", " ", m.group(1).strip())[:500]
    return None


def detect_metadata(text: str, raw_head: str, pdf_path: Path) -> dict:
    tipo = "CPC"
    numero = None
    revisao = None
    titulo = None
    correlacao = None

    source = raw_head if raw_head else text

    # 1) Tentar header CPC
    m = _RX_HEADER.search(source)
    if m:
        numero = m.group(1)
        revisao = f"R{m.group(2)}" if m.group(2) else "Original"
        titulo = _extract_title(source, m.end())
    else:
        # 2) Fallback: NBC TG (formato "NORMA BRASILEIRA DE CONTABILIDADE, NBC TG XXXX, DE ...")
        m = _RX_HEADER_NBC.search(source)
        if m:
            tipo = "NBC TG"
            numero = m.group(1)
            revisao = f"R{m.group(2)}" if m.group(2) else "Original"
            # Formato típico das NBC TG 1001/1002: "NBC TG 1001 – CONTABILIDADE PARA PEQUENAS EMPRESAS"
            titulo_nbc = _extract_nbc_titulo(source, numero)
            titulo = titulo_nbc or _extract_title(source, m.end())

    # 3) Correlação IFRS
    mifrs = _RX_IFRS.search(source[:2000])
    if mifrs:
        correlacao = f"{mifrs.group(1).upper()} {mifrs.group(2)}"

    # 4) Ementa (objetivo do pronunciamento)
    ementa = _extract_ementa_nbc(source) if tipo == "NBC TG" else None
    if not ementa:
        ementa = _extract_objetivo(text)

    # 5) Identificador canônico — usa tipo detectado (CPC ou NBC TG)
    if numero:
        base_id = f"{tipo} {numero}"
        if revisao and revisao != "Original":
            base_id += f" ({revisao})"
        identificador = base_id
    else:
        identificador = pdf_path.stem

    sha = hashlib.sha256(pdf_path.read_bytes()).hexdigest()[:16]
    return {
        "tipo": tipo,
        "numero": numero,
        "revisao": revisao,
        "titulo": titulo,
        "correlacao_ifrs": correlacao,
        "identificador": identificador,
        "ementa": ementa,
        "fonte_arquivo": pdf_path.name,
        "sha256_16": sha,
    }


def slugify(value: str) -> str:
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    value = value.replace("/", "-").replace("(", "").replace(")", "")
    value = re.sub(r"[^\w\s-]", "", value).strip().lower()
    return re.sub(r"[\s_]+", "-", value) or "cpc"


# ---------------------------------------------------------------------------
# 4. PARSE DA ESTRUTURA DE UM CPC
# ---------------------------------------------------------------------------

# Item principal: "1. Este Pronunciamento..." ou "129. A entidade..." ou "112A. ..."
RX_ITEM_CPC = re.compile(r"^(\d+[A-Z]?)\.\s+(.+)$")
# Item com prefixo (NBC TG 1001/1002): "P1", "P2", "P25A" — sem ponto no final
RX_ITEM_PREFIX = re.compile(r"^(P\d+[A-Z]?)\s+(.+)$")
# Item HIERÁRQUICO: "2.4 Este pronunciamento..." ou "3.3.1 A entidade..." (SEM ponto no final)
# Usado por CPC 48 (Instrumentos Financeiros), CPC 50 e afins que herdam a estrutura IFRS moderna.
RX_ITEM_HIER = re.compile(r"^(\d+(?:\.\d+)+[A-Z]?)\s+(.+)$")
# Item de apêndice: "B1. ..." ou "B15A. ..." (formato CPC 47)
RX_ITEM_APENDICE = re.compile(r"^([A-Z])(\d+[A-Z]?)\.\s+(.+)$")
# Item de apêndice HIERÁRQUICO: "B5.4 ..." ou "A.1.2 ..." (formato CPC 48)
RX_ITEM_APENDICE_HIER = re.compile(r"^([A-Z])\.?(\d+(?:\.\d+)*[A-Z]?)\s+(.+)$")
# Alínea: "(a) ..." ou "(b) ..."
RX_ALINEA = re.compile(r"^\(([a-z])\)\s+(.+)$")
# Sub-item: "(i) ..." ou "(ii) ..." (romanos minúsculos entre parênteses)
RX_SUBITEM = re.compile(r"^\(([ivxlcdm]+)\)\s+(.+)$")
# Seção: linha inteira em MAIÚSCULO (>3 chars, isolada)
RX_SECAO = re.compile(r"^([A-ZÁÉÍÓÚÂÊÔÃÕÇ][A-ZÁÉÍÓÚÂÊÔÃÕÇ\s\-]{2,})$")
# Seções conhecidas de CPC/NBC TG em title case (não são MAIÚSCULO no PDF)
_SECOES_CPC_KNOWN = {
    # Genéricas (aparecem em quase todo CPC)
    "objetivo", "alcance", "escopo", "reconhecimento", "mensuração", "mensuracao",
    "divulgação", "divulgacao", "definições", "definicoes",
    "apresentação", "apresentacao", "identificação", "identificacao",
    "vigência", "vigencia", "transição", "transicao",
    "introdução", "introducao",
    # CPC 47 (Receita)
    "custos do contrato", "obrigações de desempenho", "obrigacoes de desempenho",
    "obrigações de performance", "obrigacoes de performance",
    "preço da transação", "preco da transacao",
    "alocação do preço", "alocacao do preco",
    "modificação do contrato", "modificacao do contrato",
    "contrato com cliente", "receita de contrato com cliente",
    # CPC 26 (Apresentação de DCs)
    "conjunto completo de demonstrações contábeis",
    "conjunto completo de demonstracoes contabeis",
    "considerações gerais", "consideracoes gerais",
    "apresentação apropriada e conformidade",
    "apresentacao apropriada e conformidade",
    "continuidade", "regime de competência", "regime de competencia",
    "materialidade e agregação", "materialidade e agregacao",
    "compensação", "compensacao",
    "frequência de apresentação de relatório",
    "frequencia de apresentacao de relatorio",
    "informação comparativa", "informacao comparativa",
    "consistência de apresentação", "consistencia de apresentacao",
    "estrutura e conteúdo", "estrutura e conteudo",
    "estrutura", "identificação das demonstrações contábeis",
    "identificacao das demonstracoes contabeis",
    "balanço patrimonial", "balanco patrimonial",
    "informação a ser apresentada", "informacao a ser apresentada",
    "distinção entre ativo circulante e não circulante",
    "distincao entre ativo circulante e nao circulante",
    "ativo circulante", "passivo circulante",
    "demonstração do resultado", "demonstracao do resultado",
    "demonstração do resultado abrangente",
    "demonstracao do resultado abrangente",
    "outros resultados abrangentes",
    "ajustes de reclassificação", "ajustes de reclassificacao",
    "demonstração das mutações do patrimônio líquido",
    "demonstracao das mutacoes do patrimonio liquido",
    "demonstração dos fluxos de caixa",
    "demonstracao dos fluxos de caixa",
    "notas explicativas",
    "divulgação das políticas contábeis",
    "divulgacao das politicas contabeis",
    "fontes de incerteza acerca de estimativas",
    "capital", "outras divulgações", "outras divulgacoes",
    # Comum em outros CPCs
    "objetivo do pronunciamento", "objetivos",
    "princípios gerais", "principios gerais",
    "hierarquia do valor justo", "abordagem", "abordagens de avaliação",
    "técnicas de avaliação", "tecnicas de avaliacao",
    "método da equivalência patrimonial",
    "metodo da equivalencia patrimonial",
    "combinação de negócios", "combinacao de negocios",
    "goodwill", "ativos intangíveis", "ativos intangiveis",
    "depreciação", "depreciacao", "amortização", "amortizacao",
    "custo histórico", "custo historico",
    "valor recuperável", "valor recuperavel",
    "impairment", "redução ao valor recuperável",
    "reducao ao valor recuperavel",
    "arrendamento", "arrendamentos",
    "provisões", "provisoes", "passivos contingentes",
    "eventos subsequentes", "políticas contábeis", "politicas contabeis",
    "mudanças em estimativas", "mudancas em estimativas",
    "erros", "retificação de erros", "retificacao de erros",
    # Fluxos, ativos, passivos
    "atividades operacionais", "atividades de investimento",
    "atividades de financiamento",
    # CPC 03 R2 (DFC)
    "benefícios da informação dos fluxos de caixa",
    "beneficios da informacao dos fluxos de caixa",
    "apresentação da demonstração dos fluxos de caixa",
    "apresentacao da demonstracao dos fluxos de caixa",
    "apresentação dos fluxos de caixa das atividades operacionais",
    "apresentacao dos fluxos de caixa das atividades operacionais",
    "apresentação dos fluxos de caixa das atividades de investimento e de financiamento",
    "apresentacao dos fluxos de caixa das atividades de investimento e de financiamento",
    "apresentação dos fluxos de caixa em base líquida",
    "apresentacao dos fluxos de caixa em base liquida",
    "fluxos de caixa em moeda estrangeira",
    "juros e dividendos",
    "imposto de renda e contribuição social sobre o lucro líquido",
    "imposto de renda e contribuicao social sobre o lucro liquido",
    "investimento em controlada, coligada e empreendimento controlado em conjunto",
    "alteração da participação em controlada e em outros negócios",
    "alteracao da participacao em controlada e em outros negocios",
    "transação que não envolve caixa ou equivalentes de caixa",
    "transacao que nao envolve caixa ou equivalentes de caixa",
    "alteração passivo decorrente atividade financiamento",
    "alteracao passivo decorrente atividade financiamento",
    "componentes de caixa e equivalentes de caixa",
    "compomentes de caixa e equivalentes de caixa",  # typo real no PDF
    # CPC 16 R1 (Estoques)
    "mensuração de estoque", "mensuracao de estoque",
    "mensuração dos estoques", "mensuracao dos estoques",
    "custos do estoque", "custos dos estoques",
    "custos de aquisição", "custos de aquisicao",
    "custos de transformação", "custos de transformacao",
    "outros custos", "custos de estoque de prestador de serviços",
    "custos de estoque de prestador de servicos",
    "custo do produto agrícola colhido proveniente de ativo biológico",
    "custo do produto agricola colhido proveniente de ativo biologico",
    "outras formas para mensuração do custo",
    "outras formas para mensuracao do custo",
    "critérios de valoração de estoque", "criterios de valoracao de estoque",
    "valor realizável líquido", "valor realizavel liquido",
    "reconhecimento no resultado", "reconhecimento como despesa no resultado",
    # CPC 09 R1 (DVA)
    "alcance e apresentação", "alcance e apresentacao",
    "características das informações da dva", "caracteristicas das informacoes da dva",
    "formação da riqueza", "formacao da riqueza",
    "distribuição da riqueza", "distribuicao da riqueza",
    "casos especiais – alguns exemplos", "casos especiais - alguns exemplos",
    "casos especiais alguns exemplos",
    "atividade de intermediação financeira (bancária)",
    "atividade de intermediacao financeira (bancaria)",
    "atividade de seguro e resseguro",
    "atividades de seguro e resseguro",
    "modelos", "modelo geral",
    "modelo para instituições financeiras",
    "modelo para instituicoes financeiras",
    "modelo para seguradoras e resseguradoras",
    "pressupostos para a elaboração da dva",
    "pressupostos para a elaboracao da dva",
    "bases para conclusões", "bases para conclusoes",
    "origem e razões conceituais para a elaboração e divulgação da dva",
    "origem e razoes conceituais para a elaboracao e divulgacao da dva",
    "utilidade da dva e sua relação com as informações ambientais, sociais e de governança (asg)",
    "utilidade da dva e sua relacao com as informacoes ambientais, sociais e de governanca (asg)",
    "histórico da dva", "historico da dva",
    "primórdios da dva na europa", "primordios da dva na europa",
    "surgimento da dva no brasil",
    "conceito de valor adicionado e sua destinação",
    "conceito de valor adicionado e sua destinacao",
    "diferenças entre critérios econômicos e critérios contábeis",
    "diferencas entre criterios economicos e criterios contabeis",
    "dre é a base fundamental para a elaboração da dva",
    "dre e a base fundamental para a elaboracao da dva",
    # CPC 04 R1 (Intangível)
    "reconhecimento e mensuração", "reconhecimento e mensuracao",
    "reconhecimento de despesa",
    "mensuração após reconhecimento", "mensuracao apos reconhecimento",
    "vida útil", "vida util",
    "ativo intangível com vida útil definida", "ativo intangivel com vida util definida",
    "ativo intangível com vida útil indefinida", "ativo intangivel com vida util indefinida",
    "recuperação do valor contábil – perda por redução ao valor recuperável de ativos",
    "recuperacao do valor contabil - perda por reducao ao valor recuperavel de ativos",
    "baixa e alienação", "baixa e alienacao",
    "disposições transitórias", "disposicoes transitorias",
    "interpretação técnica do cpc 04", "interpretacao tecnica do cpc 04",
    "exemplos de aplicação", "exemplos de aplicacao",
    "período de amortização e método de amortização",
    "periodo de amortizacao e metodo de amortizacao",
    "valor residual",
    "revisão do período e do método de amortização",
    "revisao do periodo e do metodo de amortizacao",
    "ativos intangíveis gerados internamente",
    "ativos intangiveis gerados internamente",
    "fase de pesquisa", "fase de desenvolvimento",
    "custo de ativo intangível gerado internamente",
    "custo de ativo intangivel gerado internamente",
    "aquisição separada", "aquisicao separada",
    "aquisição como parte de combinação de negócios",
    "aquisicao como parte de combinacao de negocios",
    "aquisição por meio de subvenção ou assistência governamentais",
    "aquisicao por meio de subvencao ou assistencia governamentais",
    "permutas de ativos", "ágio derivado da expectativa de rentabilidade futura (goodwill)",
    "agio derivado da expectativa de rentabilidade futura (goodwill)",
    # CPC 01 R1 (Impairment)
    "identificação de ativo que pode estar desvalorizado",
    "identificacao de ativo que pode estar desvalorizado",
    "mensuração do valor recuperável", "mensuracao do valor recuperavel",
    "reconhecimento e mensuração de perda por desvalorização",
    "reconhecimento e mensuracao de perda por desvalorizacao",
    "unidade geradora de caixa e ágio por expectativa de rentabilidade futura (goodwill)",
    "unidade geradora de caixa e agio por expectativa de rentabilidade futura (goodwill)",
    "unidade geradora de caixa",
    "ágio por expectativa de rentabilidade futura (goodwill)",
    "agio por expectativa de rentabilidade futura (goodwill)",
    "reversão de perda por desvalorização", "reversao de perda por desvalorizacao",
    "valor recuperável", "valor recuperavel", "valor em uso", "valor justo líquido de despesa de venda",
    "valor justo liquido de despesa de venda",
    "base para determinação do valor em uso", "base para determinacao do valor em uso",
    "composição de estimativas de fluxos de caixa futuros",
    "composicao de estimativas de fluxos de caixa futuros",
    "fluxos de caixa em moeda estrangeira", "taxa de desconto",
    "reversão de perda por desvalorização para ativo individual",
    "reversao de perda por desvalorizacao para ativo individual",
    "reversão de perda por desvalorização para uma unidade geradora de caixa",
    "reversao de perda por desvalorizacao para uma unidade geradora de caixa",
    "reversão de perda por desvalorização do ágio por expectativa de rentabilidade futura (goodwill)",
    "reversao de perda por desvalorizacao do agio por expectativa de rentabilidade futura (goodwill)",
    "ativo corporativo",
    "desvalorização em uma unidade geradora de caixa",
    "desvalorizacao em uma unidade geradora de caixa",
    "momento dos testes de redução ao valor recuperável",
    "momento dos testes de reducao ao valor recuperavel",
    "alocação do ágio por expectativa de rentabilidade futura (goodwill) a unidade geradora de caixa",
    "alocacao do agio por expectativa de rentabilidade futura (goodwill) a unidade geradora de caixa",
    "testando unidade geradora de caixa com ágio por expectativa de rentabilidade futura (goodwill) para redução ao valor recuperável",
    "testando unidade geradora de caixa com agio por expectativa de rentabilidade futura (goodwill) para reducao ao valor recuperavel",
    "estimativas utilizadas para mensurar o valor recuperável de unidade geradora de caixa contendo ágio por expectativa de rentabilidade futura (goodwill) ou ativo intangível com vida útil indefinida",
    "estimativas utilizadas para mensurar o valor recuperavel de unidade geradora de caixa contendo agio por expectativa de rentabilidade futura (goodwill) ou ativo intangivel com vida util indefinida",
    "disposições transitórias", "disposicoes transitorias",
    "revogação de outro pronunciamento", "revogacao de outro pronunciamento",
    "exemplos ilustrativos",
    "nota explicativa ao pronunciamento",
    "ativos financeiros", "passivos financeiros",
    "hedge", "hedge contábil", "hedge contabil",
    "contabilidade de hedge",
    "instrumentos derivativos",
    # PME
    "conceitos e princípios", "conceitos e principios",
    "seção", "secao",
}
# Apêndice header
RX_APENDICE = re.compile(r"^AP[ÊE]NDICE\s+([A-Z])(?:\s*[–\-—]\s*(.+))?", re.I)
# Notas de vigência (algumas NBC TG têm)
RX_NOTA = re.compile(r"\((?:Reda[çc][ãa]o|Revogad|Inclu[íi]d|Vide|Vig[êe]ncia)[^)]*\)")
# Ref cruzada dentro do texto: "item 47", "conforme item 12"
RX_REF = re.compile(r"\bitem\s+(\d+[A-Z]?)\b", re.I)


@dataclass
class Item:
    numero: str                    # ex: "1", "129", "112A", "B15"
    texto: str
    secao: str                     # nome da seção ancestral
    apendice: str | None = None    # "A", "B", "C" se estiver em apêndice
    alineas: list[tuple[str, str]] = field(default_factory=list)  # (letra, texto)
    subitens: list[tuple[str, str]] = field(default_factory=list) # (romano, texto)
    notas: list[str] = field(default_factory=list)
    refs: list[str] = field(default_factory=list)
    redacao_anterior: bool = False   # texto original superado por Revisão CPC


@dataclass
class Documento:
    secoes_render: list[str] = field(default_factory=list)  # ordem das seções
    itens: list[Item] = field(default_factory=list)


def _classify_line(s: str) -> tuple[str, dict]:
    """Classifica uma linha; retorna (tipo, dados)."""
    m = RX_APENDICE.match(s)
    if m:
        return "apendice", {"letra": m.group(1), "titulo": (m.group(2) or "").strip()}

    # Ordem importa: tentar formatos MAIS ESPECÍFICOS primeiro
    m = RX_ITEM_APENDICE_HIER.match(s)
    if m and "." in m.group(2):  # exige numeração hierárquica pra evitar falso positivo com B1
        return "item_apendice", {"apendice": m.group(1), "numero": m.group(2), "texto": m.group(3).strip()}

    m = RX_ITEM_APENDICE.match(s)
    if m:
        return "item_apendice", {"apendice": m.group(1), "numero": m.group(2), "texto": m.group(3).strip()}

    m = RX_ITEM_HIER.match(s)
    if m:
        return "item", {"numero": m.group(1), "texto": m.group(2).strip()}

    m = RX_ITEM_CPC.match(s)
    if m:
        return "item", {"numero": m.group(1), "texto": m.group(2).strip()}

    # Item com prefixo alfanumérico (NBC TG 1001/1002: P1, P2, P25A)
    m = RX_ITEM_PREFIX.match(s)
    if m:
        return "item", {"numero": m.group(1), "texto": m.group(2).strip()}

    m = RX_ALINEA.match(s)
    if m:
        return "alinea", {"letra": m.group(1), "texto": m.group(2).strip()}

    m = RX_SUBITEM.match(s)
    if m:
        return "subitem", {"romano": m.group(1), "texto": m.group(2).strip()}

    m = RX_SECAO.match(s)
    if m and 3 <= len(s) <= 100:
        return "secao", {"nome": s.strip()}

    # Seções em title case conhecidas do CPC
    if 3 <= len(s) <= 80 and s.lower().strip() in _SECOES_CPC_KNOWN:
        return "secao", {"nome": s.strip()}

    return "texto", {"linha": s}


def parse_structure_cpc(text: str) -> Documento:
    doc = Documento()
    cur_secao = "OBJETIVO"           # default se o parser começar antes da 1ª seção
    cur_apendice: str | None = None
    cur_apendice_titulo: str | None = None
    cur: Item | None = None

    def flush():
        nonlocal cur
        if cur is not None:
            cur.texto = cur.texto.strip()
            cur.notas = RX_NOTA.findall(cur.texto)
            refs = {r for r in RX_REF.findall(cur.texto)}
            refs.discard(cur.numero)
            cur.refs = sorted(refs)
            doc.itens.append(cur)
            cur = None

    for line in text.splitlines():
        s = line.strip()
        if not s:
            if cur is not None:
                cur.texto += "\n"
            continue

        tipo, data = _classify_line(s)

        if tipo == "secao":
            flush()
            cur_secao = data["nome"]
            # Reset apendice quando entra numa seção que NÃO é apêndice
            if not cur_secao.upper().startswith("APÊNDICE") and not cur_secao.upper().startswith("APENDICE"):
                cur_apendice = None
            if cur_secao not in doc.secoes_render:
                doc.secoes_render.append(cur_secao)
            continue

        if tipo == "apendice":
            flush()
            cur_apendice = data["letra"]
            cur_apendice_titulo = data["titulo"]
            label = f"APÊNDICE {cur_apendice}"
            if cur_apendice_titulo:
                label += f" – {cur_apendice_titulo}"
            cur_secao = label
            if label not in doc.secoes_render:
                doc.secoes_render.append(label)
            continue

        if tipo == "item":
            flush()
            cur = Item(numero=data["numero"], texto=data["texto"],
                       secao=cur_secao, apendice=cur_apendice)
            continue

        if tipo == "item_apendice":
            flush()
            numero = f"{data['apendice']}{data['numero']}"
            cur = Item(numero=numero, texto=data["texto"],
                       secao=cur_secao, apendice=data["apendice"])
            continue

        if tipo == "alinea":
            if cur is not None:
                cur.alineas.append((data["letra"], data["texto"]))
            continue

        if tipo == "subitem":
            if cur is not None:
                cur.subitens.append((data["romano"], data["texto"]))
            continue

        # texto solto: anexa ao item atual
        if cur is not None:
            cur.texto += "\n" + s

    flush()

    # Dedup: só marca como redação anterior quando há evidência EXPLÍCITA de
    # substituição por revisão — texto contém "(Alterada pela Revisão CPC XX)",
    # "(Substituída pela...)", "(Nova redação dada pela...)" ou similar.
    # Se o mesmo número aparece 2x mas nenhum traz marca de revisão, os itens
    # são de contextos distintos (ex: corpo principal x notas explicativas
    # renumeradas a partir de 1., como no CPC 09 R1) — mantém todos vigentes.
    _RX_REV_NOTA = re.compile(r"\((?:Alterad|Revis[ãa]o|Substitu[íi]d|Nova\s+reda)", re.I)
    posicoes: dict[tuple[str, str | None], list[int]] = defaultdict(list)
    for i, it in enumerate(doc.itens):
        posicoes[(it.numero, it.apendice)].append(i)
    for chave, pos in posicoes.items():
        if len(pos) > 1:
            com_rev = [p for p in pos if _RX_REV_NOTA.search(doc.itens[p].texto)]
            if not com_rev:
                # Nenhum traz marca de revisão → não é caso de dedup por revisão.
                # Mantém todos como vigentes (contextos distintos).
                continue
            # O último item com marca de revisão é o vigente; demais anteriores.
            vigente = com_rev[-1]
            for p in pos:
                if p != vigente:
                    doc.itens[p].redacao_anterior = True

    return doc


# ---------------------------------------------------------------------------
# 5. TABELAS (idêntico ao converter.py)
# ---------------------------------------------------------------------------

def extract_tables(pdf_path: Path, out_dir: Path, threshold_rows: int, threshold_cols: int = 3):
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
                # Detectar sumário no topo: se as células têm padrão "TEXTO ...... 1-5",
                # é o índice do documento e não uma tabela real
                if pageno <= 2 and any("Item" in "".join(r) or "Sum" in "".join(r) for r in rows):
                    continue
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


# ---------------------------------------------------------------------------
# 6. RENDER MARKDOWN E CHUNKS
# ---------------------------------------------------------------------------

def _item_ref(numero: str) -> str:
    """Âncora HTML para o item: '47' -> 'item-47', 'B15' -> 'item-b15'."""
    return "item-" + numero.lower()


def _item_body_md(item: Item) -> str:
    """Renderiza o texto do item + alíneas + sub-itens em Markdown."""
    lines = [item.texto.strip()]
    for letra, texto in item.alineas:
        lines.append(f"  - **({letra})** {texto}")
    for romano, texto in item.subitens:
        lines.append(f"    - **({romano})** {texto}")
    return "\n".join(lines).strip()


def _item_body_text(item: Item) -> str:
    """Renderiza o texto do item em texto plano (para o chunk)."""
    lines = [item.texto.strip()]
    for letra, texto in item.alineas:
        lines.append(f"({letra}) {texto}")
    for romano, texto in item.subitens:
        lines.append(f"({romano}) {texto}")
    return "\n".join(lines).strip()


def render_markdown(meta: dict, doc: Documento, csvs: list[dict], inline: list[dict]) -> str:
    out: list[str] = ["---"]
    for k in ("identificador", "tipo", "numero", "revisao", "titulo",
              "correlacao_ifrs", "fonte_arquivo", "sha256_16"):
        if meta.get(k):
            out.append(f"{k}: {json.dumps(meta[k], ensure_ascii=False)}")
    if meta.get("ementa"):
        out.append(f"ementa: {json.dumps(meta['ementa'], ensure_ascii=False)}")
    out.append("---\n")

    titulo_h1 = meta.get("titulo") or meta.get("identificador", "Pronunciamento CPC")
    out.append(f"# {meta.get('identificador','CPC')} — {titulo_h1}\n")

    if meta.get("correlacao_ifrs"):
        out.append(f"> **Correlação:** {meta['correlacao_ifrs']}\n")
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

    cur_secao = None
    ant_counter = 0
    for item in doc.itens:
        if item.secao != cur_secao:
            out.append(f"\n## {item.secao}\n")
            cur_secao = item.secao
        if item.redacao_anterior:
            ant_counter += 1
            anchor = f"{_item_ref(item.numero)}--anterior-{ant_counter:03d}"
            out.append(f'\n<a id="{anchor}"></a>')
            out.append(f"> _(Item {item.numero} — redação anterior, superada por revisão)_  \n> {_item_body_md(item)}".strip())
        else:
            anchor = _item_ref(item.numero)
            out.append(f'\n<a id="{anchor}"></a>')
            out.append(f"**{item.numero}.** {_item_body_md(item)}".strip())

    for t in inline:
        out.append(f"\n> Tabela (p. {t['pagina']}):\n")
        out.append(_md_table(t["rows"]))

    return "\n".join(out).strip() + "\n"


def render_chunks(meta: dict, doc: Documento, csvs: list[dict]) -> str:
    lines: list[str] = []
    norma = meta.get("identificador", meta.get("fonte_arquivo"))
    anexos_all = [c["arquivo"] for c in csvs]
    ant_counter = 0
    for item in doc.itens:
        if item.redacao_anterior:
            ant_counter += 1
            chunk_id = f"{slugify(str(norma))}--{_item_ref(item.numero)}--anterior-{ant_counter:03d}"
        else:
            chunk_id = f"{slugify(str(norma))}--{_item_ref(item.numero)}"
        chunk = {
            "id": chunk_id,
            "norma": norma,
            "tipo": meta.get("tipo"),
            "numero_norma": meta.get("numero"),
            "revisao": meta.get("revisao"),
            "correlacao_ifrs": meta.get("correlacao_ifrs"),
            "path": f"{item.secao} > Item {item.numero}",
            "secao": item.secao,
            "item": item.numero,
            "apendice": item.apendice,
            "vigente": not item.redacao_anterior,
            "texto": f"Item {item.numero}. {_item_body_text(item)}".strip(),
            "notas_vigencia": item.notas,
            "refs": [f"item-{r.lower()}" for r in item.refs],
            "anexos": anexos_all,
            "fonte": meta.get("fonte_arquivo"),
        }
        lines.append(json.dumps(chunk, ensure_ascii=False))
    return "\n".join(lines) + ("\n" if lines else "")


# ---------------------------------------------------------------------------
# 7. PIPELINE
# ---------------------------------------------------------------------------

def convert(pdf_path: Path, out_root: Path, ocr_mode: str, threshold_rows: int) -> dict:
    pages = extract_pages(pdf_path, ocr_mode)
    text = clean_text(pages)
    meta = detect_metadata(text, "\n".join(pages[:3]), pdf_path)
    # Slug sempre pelo tipo+número (sem revisão), pra manter consistência:
    # CPC 26 R1 -> cpc-26; CPC 47 Original -> cpc-47
    if meta.get("numero"):
        slug = slugify(f"{meta.get('tipo', 'CPC')} {meta['numero']}")
    else:
        slug = slugify(str(meta["identificador"]))
    out_dir = out_root / slug
    out_dir.mkdir(parents=True, exist_ok=True)

    csvs, inline = extract_tables(pdf_path, out_dir, threshold_rows)
    doc = parse_structure_cpc(text)

    (out_dir / f"{slug}.md").write_text(render_markdown(meta, doc, csvs, inline), encoding="utf-8")
    (out_dir / f"{slug}.chunks.jsonl").write_text(render_chunks(meta, doc, csvs), encoding="utf-8")

    n_apendice = sum(1 for i in doc.itens if i.apendice and not i.redacao_anterior)
    n_alineas = sum(len(i.alineas) for i in doc.itens if not i.redacao_anterior)
    n_ant = sum(1 for i in doc.itens if i.redacao_anterior)
    n_vigentes = len(doc.itens) - n_ant
    (out_dir / f"{slug}.meta.json").write_text(
        json.dumps({**meta,
                    "n_itens": len(doc.itens),
                    "n_itens_vigentes": n_vigentes,
                    "n_itens_apendice": n_apendice,
                    "n_redacoes_anteriores": n_ant,
                    "n_alineas": n_alineas,
                    "n_secoes": len(doc.secoes_render),
                    "secoes": doc.secoes_render,
                    "n_anexos_csv": len(csvs),
                    "n_paginas": len(pages)},
                   ensure_ascii=False, indent=2), encoding="utf-8")

    return {"slug": slug, "out_dir": str(out_dir),
            "itens": len(doc.itens), "vigentes": n_vigentes,
            "itens_apendice": n_apendice, "redacoes_anteriores": n_ant,
            "alineas": n_alineas, "secoes": len(doc.secoes_render),
            "anexos_csv": len(csvs), "tabelas_inline": len(inline), "paginas": len(pages),
            "meta": meta}


def main():
    ap = argparse.ArgumentParser(description="Converte PDF de Pronunciamento CPC/NBC TG em Markdown/JSONL/CSV para RAG.")
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
