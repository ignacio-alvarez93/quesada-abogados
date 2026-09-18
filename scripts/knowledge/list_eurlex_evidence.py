"""CLI operativa: lista el catálogo verificado de evidencia EUR-Lex.

Delegación pura sobre
``backend.knowledge.eurlex.evidence_catalog.build_eurlex_evidence_catalog``.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.knowledge.eurlex.evidence_catalog import (  # noqa: E402
    build_eurlex_evidence_catalog,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Escanea y reverifica el árbol runtime de evidencia EUR-Lex, "
            "mostrando artefactos válidos y descartados."
        )
    )
    parser.add_argument(
        "--root-dir",
        default=None,
        help=(
            "Directorio runtime de evidencia (por defecto "
            "data/knowledge_eurlex_evidence)"
        ),
    )
    parser.add_argument(
        "--requested-identifier",
        default=None,
        help="Filtra por requested_identifier exacto",
    )
    parser.add_argument(
        "--canonical-identifier",
        default=None,
        help="Filtra por canonical_identifier exacto",
    )
    parser.add_argument(
        "--artifact-id",
        default=None,
        help="Filtra por artifact_id exacto",
    )

    args = parser.parse_args()

    kwargs = {}

    if args.root_dir:
        kwargs["root_dir"] = args.root_dir

    catalog = build_eurlex_evidence_catalog(
        requested_identifier=args.requested_identifier,
        canonical_identifier=args.canonical_identifier,
        artifact_id=args.artifact_id,
        **kwargs,
    )

    print("")
    print(f"== Evidencia EUR-Lex verificada ({len(catalog.verified)}) ==")
    for entry in catalog.verified:
        print(
            f"- {entry.artifact_id} "
            f"requested={entry.requested_identifier} "
            f"canonical={entry.canonical_identifier} "
            f"sha256={entry.sha256}"
        )

    print("")
    print(f"== Evidencia EUR-Lex descartada ({len(catalog.rejected)}) ==")
    for rejection in catalog.rejected:
        print(f"- {rejection.stem}: {rejection.reason}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
