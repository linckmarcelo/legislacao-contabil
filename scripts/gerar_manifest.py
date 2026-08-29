#!/usr/bin/env python3
"""Regera o manifest.json varrendo as pastas de norma da base.

Idempotente: rode sempre que adicionar/atualizar uma norma. Cada norma é uma
subpasta com <slug>.meta.json (produzido pelo conversor). O manifest é o índice
leve que a skill contador lê a cada consulta para saber o que existe, antes de
carregar o .md/.chunks da norma específica sob demanda.

Uso:
    python scripts/gerar_manifest.py            # varre a pasta da base (raiz = pai deste scripts/)
    python scripts/gerar_manifest.py --raiz .   # explícito
"""
from __future__ import annotations
import argparse
import json
from datetime import date
from pathlib import Path

SCHEMA = "1.0"


def coletar_norma(pasta: Path) -> dict | None:
    metas = list(pasta.glob("*.meta.json"))
    if not metas:
        return None
    m = json.loads(metas[0].read_text(encoding="utf-8"))
    slug = pasta.name
    md = pasta / f"{slug}.md"
    chunks = pasta / f"{slug}.chunks.jsonl"
    anexos = sorted(p.name for p in (pasta / "anexos").glob("*.csv")) if (pasta / "anexos").exists() else []
    return {
        "identificador": m.get("identificador", slug),
        "slug": slug,
        "tipo": m.get("tipo"),
        "numero": m.get("numero"),
        "ano": m.get("ano"),
        "ementa": m.get("ementa"),
        "fonte_versao": m.get("fonte_versao"),
        "atualizado_em": m.get("atualizado_em"),
        "n_artigos_vigentes": m.get("n_artigos_vigentes", m.get("n_artigos")),
        "n_redacoes_anteriores": m.get("n_redacoes_anteriores", 0),
        "n_anexos": len(anexos),
        "sha256_16": m.get("sha256_16"),
        "arquivos": {
            "markdown": f"{slug}/{md.name}" if md.exists() else None,
            "chunks": f"{slug}/{chunks.name}" if chunks.exists() else None,
            "meta": f"{slug}/{metas[0].name}",
            "anexos_dir": f"{slug}/anexos/" if anexos else None,
        },
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--raiz", type=Path, default=Path(__file__).resolve().parent.parent)
    args = ap.parse_args()
    raiz: Path = args.raiz

    normas = []
    for pasta in sorted(p for p in raiz.iterdir() if p.is_dir() and p.name != "scripts"):
        entrada = coletar_norma(pasta)
        if entrada:
            normas.append(entrada)

    manifest = {
        "schema_version": SCHEMA,
        "descricao": "Base de legislacao contabil/tributaria para consulta pela skill contador (RAG).",
        "gerado_em": date.today().isoformat(),
        "total_normas": len(normas),
        "normas": normas,
    }
    destino = raiz / "manifest.json"
    destino.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"manifest.json atualizado: {len(normas)} norma(s) -> {destino}")


if __name__ == "__main__":
    main()
