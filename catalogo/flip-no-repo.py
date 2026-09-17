#!/usr/bin/env python3
"""
flip-no-repo.py — Marca `no_repo: true` para as normas já indexadas no repo.

Uso:
    python flip-no-repo.py "NBC TG 47" "NBC TG 48" "CPC 26"
"""

import json
import re
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
JSON_PATH = SCRIPT_DIR / "normas-contabeis.json"


def normalizar(s: str) -> str:
    """Normaliza para comparação: uppercase, sem revisão '(R1)', sem espaços duplos."""
    s = s.strip().upper()
    s = re.sub(r"\s*\(R\d+\)\s*", "", s)
    s = re.sub(r"\s+", " ", s)
    return s


def main() -> None:
    if len(sys.argv) < 2:
        print("Uso: python flip-no-repo.py \"NBC TG 47\" \"NBC TG 48\" ...")
        sys.exit(1)

    alvos = [normalizar(a) for a in sys.argv[1:]]

    with JSON_PATH.open(encoding="utf-8") as f:
        data = json.load(f)

    achados = []
    ja_marcados = []
    nao_achados = list(alvos)

    for norma in data["normas"]:
        codigo_norma = normalizar(norma["codigo"])
        correspondencia = normalizar(norma.get("correspondencia_cpc", ""))
        for alvo in list(nao_achados):
            if alvo in (codigo_norma, correspondencia):
                if norma.get("no_repo"):
                    ja_marcados.append((alvo, norma["codigo"]))
                else:
                    norma["no_repo"] = True
                    achados.append((alvo, norma["codigo"]))
                nao_achados.remove(alvo)
                break

    JSON_PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8"
    )

    print(f"OK: {len(achados)} norma(s) marcada(s) como indexada(s):")
    for alvo, codigo in achados:
        note = f" (via {alvo})" if alvo != normalizar(codigo) else ""
        print(f"    - {codigo}{note}")

    if ja_marcados:
        print(f"\nInfo: {len(ja_marcados)} ja estava(m) marcada(s):")
        for alvo, codigo in ja_marcados:
            print(f"    - {codigo}")

    if nao_achados:
        print(f"\nAviso: {len(nao_achados)} nao encontrada(s) no catalogo:")
        for alvo in nao_achados:
            print(f"    - {alvo}")

    print("\nProximo passo: python gera-md.py")


if __name__ == "__main__":
    main()