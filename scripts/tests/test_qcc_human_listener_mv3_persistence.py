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
