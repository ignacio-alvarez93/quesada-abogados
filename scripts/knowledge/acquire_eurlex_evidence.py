"""CLI operativa: adquiere evidencia bruta EUR-Lex auténtica.

Delegación pura sobre los servicios de adquisición existentes en
``backend.knowledge.eurlex.evidence``, reutilizando el
``EurLexHttpTransport`` oficial. No añade ninguna dependencia HTTP
nueva ni interpreta el contenido descargado.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.knowledge.eurlex.evidence import (  # noqa: E402
    acquire_eurlex_consolidated_evidence,
    acquire_eurlex_original_evidence,
    acquire_eurlex_tree_notice_evidence,
)
from backend.knowledge.eurlex.transport import (  # noqa: E402
    EurLexHttpTransport,
)


_MODES = ("TREE_NOTICE", "ORIGINAL", "CONSOLIDATED")

_ACQUIRE_BY_MODE = {
    "TREE_NOTICE": acquire_eurlex_tree_notice_evidence,
    "ORIGINAL": acquire_eurlex_original_evidence,
    "CONSOLIDATED": acquire_eurlex_consolidated_evidence,
}


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Adquiere evidencia bruta EUR-Lex auténtica por red y la "
            "persiste con provenance determinista. No interpreta el "
            "contenido ni lo promueve a fixture de test."
        )
    )
    parser.add_argument(
        "--mode",
        required=True,
        choices=_MODES,
        help="Tipo de evidencia a adquirir",
    )
    parser.add_argument(
        "--celex",
        required=True,
        help=(
            "CELEX/identificador solicitado (acto original para "
            "TREE_NOTICE/ORIGINAL/CONSOLIDATED)"
        ),
    )
    parser.add_argument(
        "--root-dir",
        default=None,
        help=(
            "Directorio runtime de evidencia (por defecto "
            "data/knowledge_eurlex_evidence)"
        ),
    )

    args = parser.parse_args()

    kwargs = {}

    if args.root_dir:
        kwargs["root_dir"] = args.root_dir

    transport = EurLexHttpTransport()

    acquire_fn = _ACQUIRE_BY_MODE[args.mode]

    paths = acquire_fn(
        transport,
        args.celex,
        **kwargs,
    )

    print("")
    print(f"== Evidencia EUR-Lex adquirida ({args.mode}) ==")
    print(f"Metadata: {paths.metadata_path}")
    print(f"Raw:      {paths.raw_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
