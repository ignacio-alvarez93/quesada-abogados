from datetime import datetime, timezone

import pytest

from backend.qcc.context.human_policy_teaching import (
    QccHumanPolicyTeachingRecord,
)
from backend.qcc.navigation_learning.human_policy_teaching_store import (
    HumanPolicyTeachingStore,
)


FP_A = "a" * 64
NOW = datetime.now(timezone.utc)


def _record(
    *,
    teaching_id="t1",
    selector="#enviar",
    kind="LINK",
    previous_policy="NAVIGATION_CANDIDATE",
    taught_by="SIDE_PANEL",
):
    return QccHumanPolicyTeachingRecord(
        teaching_id=teaching_id,
        site_code="mercurio",
        environment="real",
        action_kind=kind,
        action_selector=selector,
        action_frame_path="main",
        before_state="STATE_A",
        before_fingerprint=FP_A,
        evidence_capture_id="cap-1",
        previous_effective_policy=previous_policy,
        resulting_restriction="HUMAN_ONLY",
        taught_by=taught_by,
        session_id="s1",
        taught_at=NOW,
    )


def test_first_teaching_is_created(tmp_path):
    store = HumanPolicyTeachingStore(root=tmp_path)

    outcome = store.record(_record())

    assert outcome["status"] == "CREATED"

    restriction = store.resolve_restriction(
        site_code="MERCURIO",
        environment="REAL",
        kind="LINK",
        selector="#enviar",
        frame_path="main",
    )

    assert restriction == "HUMAN_ONLY"


def test_repeated_teaching_is_idempotent_and_appends_history(tmp_path):
    store = HumanPolicyTeachingStore(root=tmp_path)

    store.record(_record(teaching_id="t1"))
    outcome = store.record(_record(teaching_id="t2"))

    assert outcome["status"] == "ALREADY_TAUGHT"

    snapshot = store.snapshot(
        site_code="MERCURIO",
        environment="REAL",
    )

    key = "LINK|#enviar|main"
    assert len(snapshot["history"][key]) == 2
    assert snapshot["overrides"][key]["teaching_id"] == "t2"


def test_unrelated_action_identity_has_no_restriction(tmp_path):
    store = HumanPolicyTeachingStore(root=tmp_path)

    store.record(_record(selector="#enviar"))

    assert (
        store.resolve_restriction(
            site_code="MERCURIO",
            environment="REAL",
            kind="LINK",
            selector="#other",
            frame_path="main",
        )
        is None
    )


def test_scoped_by_site_and_environment(tmp_path):
    store = HumanPolicyTeachingStore(root=tmp_path)

    store.record(_record())

    assert (
        store.resolve_restriction(
            site_code="OTHER_SITE",
            environment="REAL",
            kind="LINK",
            selector="#enviar",
            frame_path="main",
        )
        is None
    )

    assert (
        store.resolve_restriction(
            site_code="MERCURIO",
            environment="LAB",
            kind="LINK",
            selector="#enviar",
            frame_path="main",
        )
        is None
    )


def test_invalid_record_type_is_rejected(tmp_path):
    store = HumanPolicyTeachingStore(root=tmp_path)

    with pytest.raises(TypeError):
        store.record({"not": "a record"})


def test_persists_across_store_instances(tmp_path):
    HumanPolicyTeachingStore(root=tmp_path).record(_record())

    reopened = HumanPolicyTeachingStore(root=tmp_path)

    assert (
        reopened.resolve_restriction(
            site_code="MERCURIO",
            environment="REAL",
            kind="LINK",
            selector="#enviar",
            frame_path="main",
        )
        == "HUMAN_ONLY"
    )
