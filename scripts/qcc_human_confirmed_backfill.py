"""Governed CLI: register an operator-confirmed historical transition.

QCC_HUMAN_CONFIRMED_BACKFILL_V1

Use this ONLY for historical cases where a BEFORE state, an AFTER
state and the causal DOM action are already known but no live
right-click/primary-click signal was ever captured for them (REAL is
not revisited to get one).

This is a thin CLI wrapper around
``backend.qcc.context.human_confirmed_backfill
.register_human_confirmed_transition``: it never hand-edits
navigation_transitions.json and never mutates an immutable
materialized revision. It writes only into the governed
HumanNavigationCandidateStore / NavigationKnowledgeStore roots (which
default to the production paths; pass ``--candidate-root`` /
``--knowledge-root`` to target a local/temp root instead, e.g. for
tests).

Usage:

    python scripts/qcc_human_confirmed_backfill.py \\
        --site-code SITE --environment PROD \\
        --before-state STATE_A --before-fingerprint <sha256> \\
        --action-kind BUTTON --action-selector "button.close" \\
        --after-state STATE_B --after-fingerprint <sha256> \\
        --action-observed-at 2026-10-08T19:11:16+00:00 \\
        --after-observed-at 2026-10-08T19:11:26+00:00 \\
        --confirmed-by operator@example.com
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(
    0,
    str(Path(__file__).resolve().parents[1]),
)

from backend.qcc.context.human_confirmed_backfill import (  # noqa: E402
    register_human_confirmed_transition,
)
from backend.qcc.navigation_knowledge.store import (  # noqa: E402
    DEFAULT_NAVIGATION_KNOWLEDGE_ROOT,
    NavigationKnowledgeStore,
)
from backend.qcc.navigation_learning.human_candidate_store import (  # noqa: E402
    DEFAULT_HUMAN_NAVIGATION_CANDIDATE_ROOT,
    HumanNavigationCandidateStore,
)


def _parse_args(argv):
    parser = argparse.ArgumentParser(
        description=(
            "Governed registration of an operator-confirmed "
            "historical navigation transition."
        ),
    )

    parser.add_argument("--site-code", required=True)
    parser.add_argument("--environment", required=True)

    parser.add_argument("--before-state")
    parser.add_argument("--before-fingerprint", required=True)

    parser.add_argument("--action-kind", required=True)
    parser.add_argument("--action-selector", required=True)
    parser.add_argument("--action-frame-path", default="main")
    parser.add_argument(
        "--action-policy",
        default="NAVIGATION_CANDIDATE",
    )

    parser.add_argument("--after-state")
    parser.add_argument("--after-fingerprint", required=True)

    parser.add_argument("--action-observed-at", required=True)
    parser.add_argument("--after-observed-at", required=True)

    parser.add_argument("--confirmed-by", required=True)

    parser.add_argument(
        "--candidate-root",
        default=str(
            DEFAULT_HUMAN_NAVIGATION_CANDIDATE_ROOT
        ),
    )

    parser.add_argument(
        "--knowledge-root",
        default=str(
            DEFAULT_NAVIGATION_KNOWLEDGE_ROOT
        ),
    )

    return parser.parse_args(argv)


def run(argv=None) -> dict:
    args = _parse_args(argv)

    candidate_store = HumanNavigationCandidateStore(
        root=args.candidate_root,
    )

    knowledge_store = NavigationKnowledgeStore(
        root=args.knowledge_root,
    )

    return register_human_confirmed_transition(
        candidate_store,
        knowledge_store,
        site_code=args.site_code,
        environment=args.environment,
        before_state=args.before_state,
        before_fingerprint=args.before_fingerprint,
        action_kind=args.action_kind,
        action_selector=args.action_selector,
        action_frame_path=args.action_frame_path,
        action_policy=args.action_policy,
        after_state=args.after_state,
        after_fingerprint=args.after_fingerprint,
        action_observed_at=args.action_observed_at,
        after_observed_at=args.after_observed_at,
        confirmed_by=args.confirmed_by,
    )


def main(argv=None) -> int:
    result = run(argv)

    print(
        json.dumps(
            result,
            indent=2,
            sort_keys=True,
        )
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
