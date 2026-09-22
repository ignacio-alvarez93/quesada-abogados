import json
import shutil
import subprocess
from pathlib import Path

import pytest


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

HARNESS = (
    Path(__file__)
    .resolve()
    .parent
    / "qcc_listener_lifecycle_harness.js"
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


NODE = shutil.which(
    "node"
)


def run_scenario(
    name,
):
    if NODE is None:
        pytest.skip(
            "node is required for behavioural lifecycle tests"
        )

    completed = subprocess.run(
        [
            NODE,
            str(HARNESS),
            name,
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert completed.returncode == 0, (
        completed.stdout
        + completed.stderr
    )

    assert (
        "OK::" + name
        in completed.stdout
    )


# ---------------------------------------------------------------
# Behavioural (node + vm + mocked chrome API)
# ---------------------------------------------------------------

SCENARIOS = [
    # R0.C: bounded renewal.
    "renewal_alarm_scheduled_after_arm",
    "duplicate_arm_cycles_keep_single_alarm",
    "renewal_not_due_is_noop_and_idempotent",
    "renewal_reinstalls_before_expiry",
    "renewal_document_changed_fails_closed",
    "renewal_retries_are_bounded_then_gives_up",
    "renewal_closed_tab_clears_everything",
    # R0.C: stale-arm hygiene.
    "install_failure_leaves_no_stale_storage_arm",
    "clear_arms_removes_both_memory_and_storage",
    # R0.C: MV3 service-worker restart survivability.
    "sw_restart_recovers_arm_for_click_via_storage",
    # R0.C: contextmenu causal identity / wrong tab-session rejection.
    "forward_uses_fresh_evidence_and_is_single_shot",
    "forward_rejects_wrong_tab_document_frame",
    # R1 UI: teachable-action detection.
    "pointerdown_action_is_never_teachable",
    "contextmenu_success_becomes_teachable",
    "describe_teachable_action_absent_by_default",
    "describe_teachable_action_absent_without_active_tab",
    "teachable_action_labels_are_generic_and_non_identifying",
    # R1 UI: teaching Bridge contract.
    "teach_rejects_when_no_trusted_action",
    "teach_rejects_unknown_actor",
    "teach_sends_bridge_contract_shape_and_created_response",
    "teach_already_taught_response_is_not_an_error",
    "teach_stale_evidence_is_rejected",
    "teach_bridge_http_down_is_rejected_without_consuming_action",
    "teach_expired_trusted_action_is_rejected",
    # R1 UI + keyboard shortcut: shared code path.
    "shortcut_and_sidepanel_use_identical_teaching_path",
]


@pytest.mark.parametrize(
    "scenario",
    SCENARIOS,
)
def test_listener_lifecycle_behaviour(
    scenario,
):
    run_scenario(
        scenario
    )


# ---------------------------------------------------------------
# Static invariants (no node required)
# ---------------------------------------------------------------

def test_manifest_adds_only_alarms_permission_and_teach_command():
    manifest = json.loads(
        (
            QCC
            / "manifest.json"
        ).read_text(
            encoding="utf-8"
        )
    )

    assert manifest["permissions"] == [
        "sidePanel",
        "scripting",
        "activeTab",
        "storage",
        "alarms",
    ]

    assert manifest["host_permissions"] == [
        "http://127.0.0.1:8766/*"
    ]

    command = manifest["commands"]["qcc-teach-human-only"]

    # Deliberately no default keybinding: MV3/Chrome reserves and can
    # silently reject many combinations, so the command is declared
    # without forcing one (user opts in from chrome://extensions/shortcuts).
    assert "suggested_key" not in command


def test_no_static_content_scripts_regression():
    manifest = json.loads(
        (
            QCC
            / "manifest.json"
        ).read_text(
            encoding="utf-8"
        )
    )

    assert "content_scripts" not in manifest

    # Dynamic injection stays the only installation mechanism.
    text = source()

    assert "chrome.scripting.executeScript(" in text
    assert '"--load-extension"' not in text
    assert "load_extension" not in text


def test_renewal_alarm_is_one_shot_not_periodic():
    text = source()

    schedule = block(
        text,
        "function qccScheduleHumanListenerRenewal(",
        "function qccCancelHumanListenerRenewal(",
    )

    assert "when:" in schedule
    assert "periodInMinutes" not in schedule
    assert "periodInMinutes" not in text
    assert "setInterval" not in schedule

    # Exactly one alarm-name prefix is ever used for renewal, so
    # re-arming/re-creating always replaces the SAME alarm (idempotent).
    assert text.count(
        'const QCC_HUMAN_LISTENER_RENEWAL_ALARM_PREFIX =\n  "qcc:human-renew:";'
    ) == 1


def test_alarm_listener_is_the_only_alarms_consumer():
    text = source()

    assert "chrome.alarms.onAlarm.addListener(" in text
    assert text.count("chrome.alarms.onAlarm.addListener(") == 1


def test_teaching_reuses_single_certified_bridge_route():
    text = source()

    # Exactly one place in the extension builds the teaching URL: the
    # Side Panel button and the keyboard shortcut both call the SAME
    # qccTeachHumanOnlyCurrentTrustedAction, never a second endpoint.
    # (The route is also named once, in a documentation comment.)
    assert text.count('"/human-policy-teaching"') == 1
    assert text.count(
        "async function qccTeachHumanOnlyCurrentTrustedAction("
    ) == 1


def test_teaching_message_handler_and_shortcut_share_one_function():
    text = source()

    calls = [
        pos
        for pos in range(len(text))
        if text.startswith(
            "qccTeachHumanOnlyCurrentTrustedAction(",
            pos,
        )
    ]

    # Declaration + Side Panel message handler + keyboard shortcut.
    assert len(calls) == 3


def test_shortcut_command_never_mutates_storage_directly():
    text = source()

    shortcut = block(
        text,
        "const QCC_TEACH_HUMAN_ONLY_COMMAND =",
        "function captureDomFrame(",
    )

    assert "qccTeachHumanOnlyCurrentTrustedAction(" in shortcut
    assert "chrome.storage" not in shortcut
    assert ".click(" not in shortcut
    assert "executeScript(" not in shortcut

    # A missing trusted action must never crash/propagate: caught and
    # logged only, the command silently does nothing observable.
    assert "console.debug(" in shortcut
    assert "\"[QCC] Teach HUMAN_ONLY shortcut skipped:\"" in shortcut


def test_teaching_never_fabricates_pointerdown_authority():
    text = source()

    forward = block(
        text,
        "async function forwardQccHumanDomActionSignal(",
        "function captureDomFrame(",
    )

    assert 'armEventMode === "CONTEXTMENU"' in forward
    assert "qccHumanTrustedActionByTab.set(" in forward


def test_trusted_action_cleared_on_navigation_and_tab_close():
    text = source()

    updated = block(
        text,
        "chrome.tabs.onUpdated.addListener(",
        "chrome.tabs.onActivated.addListener(",
    )

    assert "qccHumanTrustedActionByTab.delete(" in updated
    assert "changeInfo?.url" in updated

    removed = block(
        text,
        "chrome.tabs.onRemoved.addListener(",
        "QCC_HUMAN_LISTENER_LIFECYCLE_ALARM_V1",
    )

    assert "clearQccHumanListenerArmsFor(" in removed
    assert "qccCancelHumanListenerRenewal(" in removed
    assert "qccHumanTrustedActionByTab.delete(" in removed


def test_sidepanel_does_not_control_the_page_for_teaching():
    script = (
        QCC
        / "sidepanel"
        / "sidepanel.js"
    ).read_text(
        encoding="utf-8"
    )

    assert "QCC_TEACH_HUMAN_ONLY" in script
    assert "QCC_GET_TEACHABLE_ACTION" in script
    assert "chrome.scripting" not in script
    assert "executeScript(" not in script


def test_sidepanel_teach_button_exists_and_is_governed_label():
    html = (
        QCC
        / "sidepanel"
        / "index.html"
    ).read_text(
        encoding="utf-8"
    )

    assert 'id="teach-human-only-button"' in html
    assert 'id="teach-human-only-card"' in html
    assert "HUMAN_ONLY" in html
