#!/usr/bin/env python3
"""
gera-md.py — Regenera normas-contabeis.md a partir de normas-contabeis.json.
"""

import json
from pathlib import Path
from collections import defaultdict

SCRIPT_DIR = Path(__file__).parent
JSON_PATH = SCRIPT_DIR / "normas-contabeis.json"
MD_PATH = SCRIPT_DIR / "normas-contabeis.md"


def status_icon(norma):
    if norma.get("situacao") == "revogada":
        rev_por = norma.get("revogada_por")
        return f"[REV] (rev. {rev_por})" if rev_por else "[REV]"
    return "[OK]" if norma.get("no_repo") else "[  ]"


def render_tabela_simples(normas):
    linhas = ["| Código | Título | Status |", "|---|---|---|"]
    for n in normas:
        linhas.append(f"| {n['codigo']} | {n['titulo']} | {status_icon(n)} |")
    return "\n".join(linhas)


def render_tabela_com_correspondencia(normas):
    linhas = ["| Código | Correspondência | Título | Status |", "|---|---|---|---|"]
    for n in normas:
        corr = n.get("correspondencia_cpc", "—")
        linhas.append(f"| {n['codigo']} | {corr} | {n['titulo']} | {status_icon(n)} |")
    return "\n".join(linhas)


def filtrar_nbc_ta_por_bloco(normas, inicio, fim):
    result = []
    for n in normas:
        if n["familia"] != "NBC TA":
            continue
        codigo = n["codigo"].replace("NBC TA ", "")
        if codigo.isdigit() and inicio <= int(codigo) <= fim:
            result.append(n)
    return result


def main():
    with JSON_PATH.open(encoding="utf-8") as f:
        data = json.load(f)

    meta = data["meta"]
    normas = data["normas"]

    por_familia = defaultdict(list)
    for n in normas:
        por_familia[n["familia"]].append(n)

    total = len(normas)
    indexadas = sum(1 for n in normas if n.get("no_repo"))
    revogadas = sum(1 for n in normas if n.get("situacao") == "revogada")

    L = []
    L.append("# Catalogo de Normas Contabeis Brasileiras\n")
    L.append(f"> **Versao:** {meta['versao']} - **Atualizado em:** {meta['atualizado_em']}\n")
    L.append(f"> **Cobertura:** {total} normas ({indexadas} indexadas, {total - indexadas - revogadas} pendentes, {revogadas} revogadas)\n")
    L.append("Legenda: [OK] indexada no repo, [  ] pendente de conversao, [REV] revogada\n")
    L.append("---\n")

    L.append("## 1. NBC TG - Tecnica Geral\n")
    nbc_tg = sorted(por_familia.get("NBC TG", []), key=lambda x: x["codigo"])
    L.append(render_tabela_com_correspondencia(nbc_tg) + "\n")

    if por_familia.get("NBC TG PME") or any(n["codigo"] == "ITG 1000" for n in por_familia.get("ITG", [])):
        L.append("## 2. PME e Microempresa\n")
        pme = list(por_familia.get("NBC TG PME", [])) + [n for n in por_familia.get("ITG", []) if n["codigo"] == "ITG 1000"]
        L.append(render_tabela_simples(pme) + "\n")

    itgs = [n for n in por_familia.get("ITG", []) if n["codigo"] != "ITG 1000"]
    if itgs:
        L.append("## 3. ITG - Interpretacoes Tecnicas Gerais\n")
        L.append(render_tabela_simples(itgs) + "\n")

    for titulo, fam in [("4. ICPC", "ICPC"), ("5. OCPC", "OCPC"), ("6. CTG", "CTG"), ("7. NBC TSP - Setor Publico", "NBC TSP")]:
        if por_familia.get(fam):
            L.append(f"## {titulo}\n")
            L.append(render_tabela_simples(por_familia[fam]) + "\n")

    if por_familia.get("NBC TA"):
        L.append("## 8. NBC TA - Auditoria\n")
        estrutura = [n for n in por_familia["NBC TA"] if "Estrutura" in n["codigo"]]
        if estrutura:
            L.append("### Estrutura\n")
            L.append(render_tabela_simples(estrutura) + "\n")
        for tit, ini, fim in [("Principios Gerais (200-299)", 200, 299), ("Avaliacao de Riscos (300-499)", 300, 499),
                              ("Evidencia (500-599)", 500, 599), ("Trabalho de Terceiros (600-699)", 600, 699),
                              ("Relatorio (700-799)", 700, 799), ("Areas Especializadas (800-899)", 800, 899)]:
            grupo = filtrar_nbc_ta_por_bloco(normas, ini, fim)
            if grupo:
                L.append(f"### {tit}\n")
                L.append(render_tabela_simples(grupo) + "\n")

    correlatos = por_familia.get("NBC TR", []) + por_familia.get("NBC TO", []) + por_familia.get("NBC TSC", [])
    if correlatos:
        L.append("## 9. NBC TR / TO / TSC\n")
        tab = ["| Codigo | Familia | Titulo | Status |", "|---|---|---|---|"]
        for n in correlatos:
            tab.append(f"| {n['codigo']} | {n['familia']} | {n['titulo']} | {status_icon(n)} |")
        L.append("\n".join(tab) + "\n")

    pericia = por_familia.get("NBC TP", []) + por_familia.get("NBC PP", [])
    if pericia:
        L.append("## 10. NBC TP / NBC PP - Pericia\n")
        tab = ["| Codigo | Familia | Titulo | Status |", "|---|---|---|---|"]
        for n in pericia:
            tab.append(f"| {n['codigo']} | {n['familia']} | {n['titulo']} | {status_icon(n)} |")
        L.append("\n".join(tab) + "\n")

    if por_familia.get("NBC PG") or por_familia.get("NBC PA"):
        L.append("## 11. NBC PG / NBC PA - Normas Profissionais\n")
        if por_familia.get("NBC PG"):
            L.append("### Geral (PG)\n")
            L.append(render_tabela_simples(por_familia["NBC PG"]) + "\n")
        if por_familia.get("NBC PA"):
            L.append("### Auditor (PA)\n")
            L.append(render_tabela_simples(por_familia["NBC PA"]) + "\n")

    L.append("---\n")
    L.append("*Renderizado a partir de `normas-contabeis.json`. Regere com `python gera-md.py`.*\n")

    MD_PATH.write_text("\n".join(L), encoding="utf-8")
    print(f"OK: gerado {MD_PATH.name}")
    print(f"Total: {total} | Indexadas: {indexadas} | Pendentes: {total - indexadas - revogadas} | Revogadas: {revogadas}")


if __name__ == "__main__":
    main()