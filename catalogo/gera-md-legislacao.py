#!/usr/bin/env python3
"""
gera-md-legislacao.py — Regenera legislacao-tributaria.md a partir do JSON.

Uso:
    python gera-md-legislacao.py
"""

import json
from pathlib import Path
from collections import defaultdict

SCRIPT_DIR = Path(__file__).parent
JSON_PATH = SCRIPT_DIR / "legislacao-tributaria.json"
MD_PATH = SCRIPT_DIR / "legislacao-tributaria.md"


def status_icon(peca):
    if peca.get("situacao") == "revogada":
        return "[REV]"
    return "[OK]" if peca.get("no_repo") else "[  ]"


def render_tabela(pecas):
    linhas = ["| Codigo | Titulo | Data | Pasta no repo | Status |",
              "|---|---|---|---|---|"]
    for p in sorted(pecas, key=lambda x: x.get("data", "0000")):
        pasta = p.get("pasta_repo", "—")
        pasta_link = f"[`{pasta}`](../{pasta}/)" if pasta != "—" else "—"
        linhas.append(f"| {p['codigo']} | {p['titulo']} | {p.get('data', '')} | {pasta_link} | {status_icon(p)} |")
    return "\n".join(linhas)


def main():
    with JSON_PATH.open(encoding="utf-8") as f:
        data = json.load(f)

    meta = data["meta"]
    pecas = data["pecas"]

    por_assunto = defaultdict(list)
    for p in pecas:
        for a in p.get("assunto", ["outros"]):
            por_assunto[a].append(p)

    total = len(pecas)
    indexadas = sum(1 for p in pecas if p.get("no_repo"))

    L = []
    L.append("# Catalogo de Legislacao Tributaria, Trabalhista e Societaria\n")
    L.append(f"> **Versao:** {meta['versao']} - **Atualizado em:** {meta['atualizado_em']}\n")
    L.append(f"> **Cobertura:** {total} pecas indexadas ({indexadas} com texto integral no repo)\n")
    L.append("Este catalogo complementa [`normas-contabeis.md`](./normas-contabeis.md), que cobre CFC/CPC.\n")
    L.append("Legenda: [OK] indexada no repo, [  ] pendente de conversao, [REV] revogada\n")
    L.append("---\n")

    ordem_assunto = [
        ("reforma-tributaria", "Reforma Tributaria (IBS/CBS/IS)"),
        ("tributario-federal", "Tributario Federal (geral)"),
        ("irpf", "IRPF"),
        ("previdenciario", "Previdenciario"),
        ("agrario", "Agrario / Atividade Rural"),
        ("trabalhista", "Trabalhista"),
        ("societario", "Societario"),
        ("administrativo", "Administrativo (Atos Conjuntos, etc)"),
    ]

    ja_listadas = set()
    for i, (chave, titulo) in enumerate(ordem_assunto, 1):
        grupo = por_assunto.get(chave, [])
        grupo_novo = [p for p in grupo if p["codigo"] not in ja_listadas]
        if grupo_novo:
            L.append(f"## {i}. {titulo}\n")
            L.append(render_tabela(grupo_novo) + "\n")
            for p in grupo_novo:
                ja_listadas.add(p["codigo"])

    # Qualquer coisa que sobrou
    sobra = [p for p in pecas if p["codigo"] not in ja_listadas]
    if sobra:
        L.append("## Outros\n")
        L.append(render_tabela(sobra) + "\n")

    L.append("---\n")
    L.append("## Ordem cronologica (referencia rapida)\n")
    L.append(render_tabela(pecas) + "\n")

    L.append("---\n")
    L.append("*Renderizado a partir de `legislacao-tributaria.json`. Regere com `python gera-md-legislacao.py`.*\n")

    MD_PATH.write_text("\n".join(L), encoding="utf-8")
    print(f"OK: gerado {MD_PATH.name}")
    print(f"Total: {total} pecas | Indexadas: {indexadas}")


if __name__ == "__main__":
    main()
