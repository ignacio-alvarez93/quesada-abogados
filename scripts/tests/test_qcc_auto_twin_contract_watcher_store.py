import json

import pytest

from backend.qcc.auto_twin.contract_watcher import (
    CONTRACT_WATCHER_EVIDENCE_TYPE,
    build_contract_watcher_evidence,
)
from backend.qcc.auto_twin.contract_watcher_store import (
    CONTRACT_WATCHER_EVIDENCE_FILENAME,
    ContractWatcherEvidenceStore,
)


def _evidence(**overrides):
    before = {
        "schema_version": 1,
        "page": {"pathname": "/step/1"},
        "elements": (),
        "catalogs": (),
    }

    after = dict(before)

    kwargs = {
        "contract_key": "mercurio-ex01-personal",
        "before": before,
        "after": after,
        "before_reference": "capture-1",
        "after_reference": "capture-2",
    }

    kwargs.update(overrides)

    return build_contract_watcher_evidence(**kwargs)


def test_store_writes_exact_evidence_layout(tmp_path):
    store = ContractWatcherEvidenceStore(root=tmp_path)
    record = _evidence()

    saved = store.save(record)

    path = (
        tmp_path
        / record["contract_key"]
        / record["evidence_id"]
        / CONTRACT_WATCHER_EVIDENCE_FILENAME
    )

    assert path.is_file()

    persisted = json.loads(path.read_text(encoding="utf-8"))

    assert persisted == saved
    assert persisted["evidence_type"] == CONTRACT_WATCHER_EVIDENCE_TYPE


def test_save_is_idempotent_for_same_identity(tmp_path):
    store = ContractWatcherEvidenceStore(root=tmp_path)
    record = _evidence()

    first = store.save(record)
    second = store.save(record)

    assert first == second

    evidence_dirs = list((tmp_path / record["contract_key"]).iterdir())

    assert len(evidence_dirs) == 1


def test_get_returns_persisted_evidence(tmp_path):
    store = ContractWatcherEvidenceStore(root=tmp_path)
    record = _evidence()

    store.save(record)

    fetched = store.get(
        contract_key=record["contract_key"],
        evidence_id=record["evidence_id"],
    )

    assert fetched == record


def test_get_returns_none_for_missing_evidence(tmp_path):
    store = ContractWatcherEvidenceStore(root=tmp_path)

    assert store.get(
        contract_key="unknown-contract",
        evidence_id="cwev-" + "0" * 24,
    ) is None


def test_list_returns_all_persisted_evidence_for_contract(tmp_path):
    store = ContractWatcherEvidenceStore(root=tmp_path)

    record_a = _evidence(
        before_reference="capture-1",
        after_reference="capture-2",
    )

    record_b = _evidence(
        before_reference="capture-2",
        after_reference="capture-3",
    )

    store.save(record_a)
    store.save(record_b)

    listed = store.list(contract_key=record_a["contract_key"])

    assert {item["evidence_id"] for item in listed} == {
        record_a["evidence_id"],
        record_b["evidence_id"],
    }


def test_list_without_contract_key_covers_all_contracts(tmp_path):
    store = ContractWatcherEvidenceStore(root=tmp_path)

    record_a = _evidence(contract_key="mercurio-ex01-personal")
    record_b = _evidence(contract_key="mercurio-ex01-authorization")

    store.save(record_a)
    store.save(record_b)

    listed = store.list()

    assert {item["evidence_id"] for item in listed} == {
        record_a["evidence_id"],
        record_b["evidence_id"],
    }


def test_reading_tampered_evidence_fails_closed(tmp_path):
    store = ContractWatcherEvidenceStore(root=tmp_path)
    record = _evidence()

    store.save(record)

    path = store.evidence_path(
        contract_key=record["contract_key"],
        evidence_id=record["evidence_id"],
    )

    tampered = json.loads(path.read_text(encoding="utf-8"))
    tampered["watch_state"] = "REBUILD_REQUIRED"

    path.write_text(json.dumps(tampered), encoding="utf-8")

    with pytest.raises(ValueError):
        store.get(
            contract_key=record["contract_key"],
            evidence_id=record["evidence_id"],
        )


def test_save_rejects_non_dict_record(tmp_path):
    store = ContractWatcherEvidenceStore(root=tmp_path)

    with pytest.raises(TypeError):
        store.save("not a dict")


def test_save_rejects_unsafe_contract_key(tmp_path):
    store = ContractWatcherEvidenceStore(root=tmp_path)
    record = _evidence(contract_key="../escape")

    with pytest.raises(ValueError):
        store.save(record)


def test_store_never_persists_raw_page_content(tmp_path):
    store = ContractWatcherEvidenceStore(root=tmp_path)
    record = _evidence()

    saved = store.save(record)

    serialized = json.dumps(saved)

    for forbidden in ("<html", "cookie", "password", "NIE"):
        assert forbidden not in serialized
