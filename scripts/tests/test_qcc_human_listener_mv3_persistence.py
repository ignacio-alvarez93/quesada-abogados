import json
from pathlib import Path


ROOT = (
    Path(__file__)
    .resolve()
    .parents[2]
)

QCC = (
    ROOT
    / "chrome_extension"
    / "qcc"
)

SW = (
    QCC
    / "background"
    / "service_worker.js"
)


def source():
    return SW.read_text(
        encoding="utf-8"
    )


def block(
    text,
    start,
    end,
):
    a = text.index(
        start
    )
    b = text.index(
        end,
        a,
    )
    return text[a:b]


def test_manifest_has_storage_permission():
    manifest = json.loads(
        (
            QCC
            / "manifest.json"
        ).read_text(
            encoding="utf-8"
        )
    )

    assert (
        "storage"
        in manifest.get(
            "permissions",
            []
        )
    )


def test_human_arm_uses_session_storage_only():
    text = source()

    assert (
        "chrome.storage.session.set"
        in text
    )

    assert (
        "chrome.storage.session.get"
        in text
    )

    assert (
        "chrome.storage.session.remove"
        in text
    )

    assert (
        "chrome.storage.local"
        not in block(
            text,
            "const QCC_HUMAN_ARM_STORAGE_PREFIX",
            "async function armQccHumanClickListeners",
        )
    )


def test_arm_is_persisted_before_runtime_use():
    text = source()

    arm = block(
        text,
        "async function armQccHumanClickListeners",
        "async function forwardQccHumanDomActionSignal",
    )

    assert (
        "await persistQccHumanListenerArm("
        in arm
    )


def test_forward_takes_arm_from_mv3_safe_store():
    text = source()

    forward = block(
        text,
        "async function forwardQccHumanDomActionSignal",
        "async function inspectActiveTabDom",
    )

    assert (
        "await takeQccHumanListenerArm("
        in forward
    )

    assert (
        "qccHumanListenerArms.get("
        not in forward
    )

    assert (
        "qccHumanListenerArms.delete("
        not in forward
    )


def test_take_is_single_shot_in_memory_and_session():
    text = source()

    take = block(
        text,
        "async function takeQccHumanListenerArm",
        "async function armQccHumanClickListeners",
    )

    assert (
        "qccHumanListenerArms.delete("
        in take
    )

    assert (
        "chrome.storage.session.remove("
        in take
    )



def test_expired_human_arms_are_pruned_from_session_storage():
    text = source()

    prune = block(
        text,
        "async function pruneExpiredQccHumanListenerArms",
        "async function persistQccHumanListenerArm",
    )

    assert (
        "chrome.storage.session.get("
        in prune
    )

    assert (
        "chrome.storage.session.remove("
        in prune
    )

    assert (
        "QCC_HUMAN_ARM_STORAGE_PREFIX"
        in prune
    )

    assert (
        "expires_at"
        in prune
    )


def test_expired_human_arms_are_pruned_from_memory_cache():
    text = source()

    prune = block(
        text,
        "async function pruneExpiredQccHumanListenerArms",
        "async function persistQccHumanListenerArm",
    )

    assert (
        "qccHumanListenerArms.entries()"
        in prune
    )

    assert (
        "qccHumanListenerArms.delete("
        in prune
    )


def test_new_arm_prunes_expired_arms_first():
    text = source()

    persist = block(
        text,
        "async function persistQccHumanListenerArm",
        "async function takeQccHumanListenerArm",
    )

    prune_pos = persist.index(
        "await pruneExpiredQccHumanListenerArms();"
    )

    set_pos = persist.index(
        "qccHumanListenerArms.set("
    )

    storage_pos = persist.index(
        "chrome.storage.session.set("
    )

    assert (
        prune_pos
        < set_pos
        < storage_pos
    )


def test_service_worker_performs_best_effort_startup_prune():
    text = source()

    prefix = text[
        text.index(
            "async function pruneExpiredQccHumanListenerArms"
        ):
        text.index(
            "async function persistQccHumanListenerArm"
        )
    ]

    assert (
        "pruneExpiredQccHumanListenerArms()"
        in prefix
    )

    assert (
        ".catch("
        in prefix
    )


def test_housekeeping_does_not_change_single_shot_take():
    text = source()

    take = block(
        text,
        "async function takeQccHumanListenerArm",
        "async function armQccHumanClickListeners",
    )

    assert (
        "qccHumanListenerArms.delete("
        in take
    )

    assert (
        "chrome.storage.session.remove("
        in take
    )
