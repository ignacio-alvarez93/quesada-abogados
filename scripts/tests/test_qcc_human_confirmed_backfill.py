"""Governed HUMAN_CONFIRMED historical backfill.

QCC_AUTO_TWIN_R5F_PRIMARY_CLICK_TEACHING

Covers work-order tests G, H, I: the backfill contract reuses the SAME
canonical human-action/candidate-transition pipeline live teaching
uses, is idempotent, and never duplicates already-registered evidence.

The Mercurio-shaped fixture (test_mercurio_shaped_fixture_has_no_production_literals
below) exists ONLY here, as a fixture -- production code must contain
none of its literals.
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

from backend.qcc.context.human_confirmed_backfill import (
    QCC_HUMAN_CONFIRMED_BACKFILL_SOURCE,
    register_human_confirmed_transition,
)
from backend.qcc.navigation_learning.human_candidate_store import (
    HUMAN_NAVIGATION_CANDIDATE_STATUS_CONFIRMED,
    HumanNavigationCandidateStore,
)
from backend.qcc.navigation_knowledge.store import NavigationKnowledgeStore


SITE_CODE = "BACKFILLTWIN"
ENVIRONMENT = "TEST"

BEFORE_STATE = "STATE-FROM"
AFTER_STATE = "STATE-TARGET"

BEFORE_FP = "a" * 64
AFTER_FP = "b" * 64

ACTION_SELECTOR = "button.generic-close"

ACTION_OBSERVED_AT = datetime(
    2026, 10, 8, 19, 11, 16, tzinfo=timezone.utc
)

AFTER_OBSERVED_AT = datetime(
    2026, 10, 8, 19, 11, 26, tzinfo=timezone.utc
)


def _stores(tmp_path):
    candidate_store = HumanNavigationCandidateStore(
        root=tmp_path / "navigation_learning"
    )

    knowledge_store = NavigationKnowledgeStore(
        root=tmp_path / "navigation_knowledge"
    )

    return candidate_store, knowledge_store


def _register(candidate_store, knowledge_store, **overrides):
    kwargs = dict(
        site_code=SITE_CODE,
        environment=ENVIRONMENT,
        before_state=BEFORE_STATE,
        before_fingerprint=BEFORE_FP,
        action_kind="BUTTON",
        action_selector=ACTION_SELECTOR,
        action_frame_path="main",
        after_state=AFTER_STATE,
        after_fingerprint=AFTER_FP,
        action_observed_at=ACTION_OBSERVED_AT,
        after_observed_at=AFTER_OBSERVED_AT,
        confirmed_by="operator@example.test",
    )
    kwargs.update(overrides)

    return register_human_confirmed_transition(
        candidate_store,
        knowledge_store,
        **kwargs,
    )


def test_backfill_reaches_confirmed_and_promotes(tmp_path):
    candidate_store, knowledge_store = _stores(tmp_path)

    result = _register(candidate_store, knowledge_store)

    assert result["source"] == QCC_HUMAN_CONFIRMED_BACKFILL_SOURCE
    assert result["idempotent"] is False
    assert (
        result["candidate_status"]
        == HUMAN_NAVIGATION_CANDIDATE_STATUS_CONFIRMED
    )
    assert result["promotion_count"] == 1
    assert result["knowledge_recorded_count"] == 3

    snapshot = candidate_store.snapshot(
        SITE_CODE, environment=ENVIRONMENT
    )

    assert len(snapshot["candidates"]) == 1
    candidate = snapshot["candidates"][0]

    assert candidate["status"] == HUMAN_NAVIGATION_CANDIDATE_STATUS_CONFIRMED
    assert candidate["promoted_at"] is not None
    assert candidate["action"]["selector"] == ACTION_SELECTOR
    assert candidate["before_fingerprint"] == BEFORE_FP
    assert candidate["after_fingerprint"] == AFTER_FP


def test_backfill_is_idempotent_on_repeat(tmp_path):
    candidate_store, knowledge_store = _stores(tmp_path)

    first = _register(candidate_store, knowledge_store)
    second = _register(candidate_store, knowledge_store)

    assert first["idempotent"] is False
    assert second["idempotent"] is True

    assert second["candidate_id"] == first["candidate_id"]
    assert second["promotion_count"] == 0
    assert second["knowledge_recorded_count"] == 0

    snapshot = candidate_store.snapshot(
        SITE_CODE, environment=ENVIRONMENT
    )

    # No duplicate candidate was created, and corroboration did not
    # grow past the confirmation threshold.
    assert len(snapshot["candidates"]) == 1
    assert len(snapshot["candidates"][0]["event_ids"]) == 3


def test_backfill_requires_confirmed_by(tmp_path):
    candidate_store, knowledge_store = _stores(tmp_path)

    with pytest.raises(ValueError):
        _register(candidate_store, knowledge_store, confirmed_by="   ")


def test_backfill_distinct_facts_do_not_collide(tmp_path):
    candidate_store, knowledge_store = _stores(tmp_path)

    _register(candidate_store, knowledge_store)

    other = _register(
        candidate_store,
        knowledge_store,
        after_state="STATE-OTHER-TARGET",
        after_fingerprint="c" * 64,
    )

    snapshot = candidate_store.snapshot(
        SITE_CODE, environment=ENVIRONMENT
    )

    assert len(snapshot["candidates"]) == 2
    assert other["idempotent"] is False


def test_mercurio_shaped_fixture_registers_without_production_hardcode(
    tmp_path,
):
    """QCC_AUTO_TWIN_R5F: Mercurio is regression evidence only.

    Fixture-shaped identifiers (05/06 state ids, mdCer selector) live
    HERE ONLY. See test_human_confirmed_backfill_module_has_no_mercurio_literals.
    """

    candidate_store, knowledge_store = _stores(tmp_path)

    result = register_human_confirmed_transition(
        candidate_store,
        knowledge_store,
        site_code="MERCURIOFIXTURE",
        environment="TEST",
        before_state="AUTO_0591B65DFA33A79AB81A6223",
        before_fingerprint="d" * 64,
        action_kind="BUTTON",
        action_selector='button.mdCer[title="Cerrar la ventana"]',
        action_frame_path="main",
        after_state="AUTO_8F5F252DF61D5C02E2CA52A7",
        after_fingerprint="e" * 64,
        action_observed_at=ACTION_OBSERVED_AT,
        after_observed_at=AFTER_OBSERVED_AT,
        confirmed_by="operator@example.test",
    )

    assert (
        result["candidate_status"]
        == HUMAN_NAVIGATION_CANDIDATE_STATUS_CONFIRMED
    )


def test_human_confirmed_backfill_module_has_no_mercurio_literals():
    module_path = (
        Path(__file__).resolve().parents[2]
        / "backend"
        / "qcc"
        / "context"
        / "human_confirmed_backfill.py"
    )

    source = module_path.read_text(encoding="utf-8").lower()

    for forbidden in (
        "mercurio",
        "mdcer",
        "auto_0591b65dfa33a79ab81a6223",
        "auto_8f5f252df61d5c02e2ca52a7",
        "seleccionmodelo-33",
    ):
        assert forbidden not in source


def _run_cli(tmp_path, *, candidate_root, knowledge_root):
    repo_root = Path(__file__).resolve().parents[2]

    args = [
        sys.executable,
        str(repo_root / "scripts" / "qcc_human_confirmed_backfill.py"),
        "--site-code", SITE_CODE,
        "--environment", ENVIRONMENT,
        "--before-state", BEFORE_STATE,
        "--before-fingerprint", BEFORE_FP,
        "--action-kind", "BUTTON",
        "--action-selector", ACTION_SELECTOR,
        "--after-state", AFTER_STATE,
        "--after-fingerprint", AFTER_FP,
        "--action-observed-at", "2026-10-08T19:11:16+00:00",
        "--after-observed-at", "2026-10-08T19:11:26+00:00",
        "--confirmed-by", "operator@example.test",
        "--candidate-root", str(candidate_root),
        "--knowledge-root", str(knowledge_root),
    ]

    completed = subprocess.run(
        args,
        cwd=repo_root,
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert completed.returncode == 0, (
        completed.stdout + completed.stderr
    )

    return json.loads(completed.stdout)


def test_cli_registers_and_is_idempotent(tmp_path):
    candidate_root = tmp_path / "cand"
    knowledge_root = tmp_path / "know"

    first = _run_cli(
        tmp_path,
        candidate_root=candidate_root,
        knowledge_root=knowledge_root,
    )
    second = _run_cli(
        tmp_path,
        candidate_root=candidate_root,
        knowledge_root=knowledge_root,
    )

    assert first["idempotent"] is False
    assert first["candidate_status"] == HUMAN_NAVIGATION_CANDIDATE_STATUS_CONFIRMED
    assert second["idempotent"] is True
    assert second["candidate_id"] == first["candidate_id"]
