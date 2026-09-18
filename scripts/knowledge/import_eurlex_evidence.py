from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.knowledge.eurlex.evidence import (  # noqa: E402
    import_eurlex_evidence_file,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Importa un payload EUR-Lex ya descargado por el operador "
            "como evidencia bruta auténtica con provenance determinista. "
            "No interpreta el contenido ni lo promueve a fixture de test."
        )
    )
    parser.add_argument(
        "file",
        help="Ruta local al payload EUR-Lex ya descargado",
    )
    parser.add_argument(
        "--requested-identifier",
        required=True,
        help="CELEX o URI exactamente como fue solicitado",
    )
    parser.add_argument(
        "--source-url",
        required=True,
        help="URL exacta de origen del payload",
    )
    parser.add_argument(
        "--canonical-identifier",
        default=None,
        help="CELEX/ELI canónico resuelto, si se conoce",
    )
    parser.add_argument(
        "--content-type",
        default=None,
        help="Content-Type declarado por el origen, si se conoce",
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

    paths = import_eurlex_evidence_file(
        source_path=args.file,
        requested_identifier=args.requested_identifier,
        source_url=args.source_url,
        canonical_identifier=args.canonical_identifier,
        content_type=args.content_type,
        **kwargs,
    )

    print("")
    print("== Evidencia EUR-Lex importada ==")
    print(f"Metadata: {paths.metadata_path}")
    print(f"Raw:      {paths.raw_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
