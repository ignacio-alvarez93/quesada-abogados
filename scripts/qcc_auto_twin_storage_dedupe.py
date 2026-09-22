"""Migrador gobernado de deduplicación física (hardlinks) AUTO TWIN.

Uso:

    python scripts/qcc_auto_twin_storage_dedupe.py --root <twin_root>            # dry-run
    python scripts/qcc_auto_twin_storage_dedupe.py --root <twin_root> --apply

Por defecto es dry-run. ``--apply`` es explícito. Opera únicamente dentro
del twin root indicado (revisiones matrev-*), nunca borra archivos ni
revisiones y falla cerrado ante cualquier verificación distinta.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

sys.path.insert(
    0,
    str(Path(__file__).resolve().parents[1]),
)

from backend.qcc.auto_twin.materialized_storage_dedupe import (  # noqa: E402
    AUTO_TWIN_STORAGE_DEDUPE_MIN_BYTES,
    AUTO_TWIN_STORAGE_HARDLINK_TARGET_MAX,
    apply_plan,
    plan_twin_root,
)


def _summary(plan) -> dict:
    return {
        key: plan[key]
        for key in (
            "revision_count",
            "file_count",
            "logical_bytes",
            "current_physical_bytes",
            "unique_content_bytes",
            "duplicate_bytes",
            "files_dedupable",
            "expected_physical_savings",
            "estimated_post_migration_bytes",
            "already_shared_files",
        )
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--root", required=True)
    parser.add_argument(
        "--min-bytes",
        type=int,
        default=AUTO_TWIN_STORAGE_DEDUPE_MIN_BYTES,
    )
    parser.add_argument(
        "--link-cap",
        type=int,
        default=AUTO_TWIN_STORAGE_HARDLINK_TARGET_MAX,
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")

    args = parser.parse_args(argv)

    plan = plan_twin_root(
        args.root,
        min_bytes=args.min_bytes,
        link_cap=args.link_cap,
    )

    print("MODE=" + ("APPLY" if args.apply else "DRY_RUN"))
    print("ROOT=" + str(plan["root"]))
    print("MIN_BYTES=" + str(plan["min_bytes"]))

    for key, value in _summary(plan).items():
        print(f"{key.upper()}={value}")

    print("HASH_ERRORS=" + str(len(plan["hash_errors"])))
    print("LINK_CAP=" + str(plan["link_cap"]))
    print("DUPLICATED_HASHES=" + str(len(plan["shards_by_hash"])))
    print(
        "MULTI_SHARD_HASHES="
        + str(sum(1 for n in plan["shards_by_hash"].values() if n > 1))
    )
    print(
        "MAX_SHARDS_PER_HASH="
        + str(max(plan["shards_by_hash"].values(), default=0))
    )

    if not args.apply:
        return 0

    report = apply_plan(plan)

    print("LINKED=" + str(report["linked"]))
    print("ALREADY_LINKED=" + str(report["already_linked"]))
    print("FAILURES=" + str(len(report["failures"])))

    for path, reason in report["failures"]:
        print("FAILURE " + path + " " + reason)

    return 0 if report["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
