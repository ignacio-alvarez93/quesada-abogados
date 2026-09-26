"""CLI operativa: selecciona evidencia EUR-Lex verificada para forense.

Delegación pura sobre
``backend.knowledge.eurlex.forensic_selection.select_eurlex_forensic_evidence``.
Nunca copia bytes crudos ni promueve el artefacto a fixture de test.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.knowledge.eurlex.forensic_selection import (  # noqa: E402
    select_eurlex_forensic_evidence,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Selecciona deliberadamente evidencia EUR-Lex ya verificada "
            "para análisis forense del parser, escribiendo un manifiesto "
            "que referencia el artefacto sin copiar sus bytes."
        )
    )
    parser.add_argument(
        "--artifact-id",
        required=True,
        help="artifact_id de la evidencia verificada a seleccionar",
    )
    parser.add_argument(
        "--selection-id",
        required=True,
        help="Identidad de selección declarada por el operador",
    )
    parser.add_argument(
        "--evidence-root",
        default=None,
        help=(
            "Directorio runtime de evidencia (por defecto "
            "data/knowledge_eurlex_evidence)"
        ),
    )
    parser.add_argument(
        "--selection-root",
        default=None,
        help=(
            "Directorio runtime de selección forense (por defecto "
            "data/knowledge_eurlex_forensic_selection)"
        ),
    )

    args = parser.parse_args()

    kwargs = {}

    if args.evidence_root:
        kwargs["evidence_root"] = args.evidence_root

    if args.selection_root:
        kwargs["selection_root"] = args.selection_root

    selection = select_eurlex_forensic_evidence(
        artifact_id=args.artifact_id,
        selection_id=args.selection_id,
        **kwargs,
    )

    print("")
    print("== Evidencia EUR-Lex seleccionada para forense ==")
    print(f"Manifest:  {selection.manifest_path}")
    print(f"artifact_id: {selection.artifact_id}")
    print(f"sha256:      {selection.sha256}")
    print(f"identity_sha256: {selection.identity_sha256}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
