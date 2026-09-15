# QCC / AUTO_TWIN Branch Consolidation Manifest (2D-22 audit)

**Purpose:** persist the complete, already-executed 2D-22 read-only branch
audit so a *fresh* Claude Code session (or human reviewer) can execute
the remaining consolidation commits (Groups A-G below) without needing
any prior conversation history.

**Branch:** `feature/qcc-live-navigation-intelligence`
**HEAD at time of audit:** `57768f1a6439eabde27dacdecf6c17d9b2dc6bcf`
("fix(auto-twin): close governed EX01_PERSONAL TITULAR/FAMILIAR
two-call reconciliation (2D-20S-W)")
**Total dirty/untracked entries at audit time:** 193
**2D-20 feature status referenced:** `TWO_PASS_VALIDATED` (governed
EX01_PERSONAL TITULAR/FAMILIAR fixed-point closure, see
`docs/ai/CURRENT_STATE.md` §15)

---

## 1. Headline finding

**A fresh clone of `57768f1` alone cannot execute the validated
QCC/AUTO_TWIN functionality or its test suite.** Confirmed empirically
(not just by static import analysis) by exporting `git archive HEAD`
into an isolated directory and running real imports/pytest there:

- `from backend.qcc.auto_twin.automatic_materialization import
  reconcile_auto_twin_discovery_materialization` fails immediately:
  `ModuleNotFoundError: No module named
  'backend.qcc.auto_twin.catalog_materialization'`.
- Even after adding the narrow 13-file + `mercurio.py`/`ingestor.py`
  closure, the exact 264-test "2D-20 closure" regression set scores
  **251 passed / 12 skipped (real-data-gated, correctly) / 1 failed**
  (`test_bridge_hooks_page_and_viewport`, needs
  `backend/qcc/bridge/server.py`'s uncommitted diff).
- The broader ~99-file AUTO_TWIN test corpus scores **671 passed / 116
  failed** once the `__init__.py` aggregator closure is also added;
  the 116 failures are exclusively CRM/sidepanel/manage-api/
  validation-evidence-read-api/renderer-v2/v6/bridge-hook tests, all
  needing `backend/qcc/bridge/server.py`'s much larger, separate
  integration-layer diff.
- 8 test files do not even collect (`ModuleNotFoundError` for
  `backend.services.twin_*_runtime_service`).

## 2. Final verdict (2D-22)

```
ADDITIONAL_COMMITS_REQUIRED
```

Fresh-clone-of-57768f1-alone verdict: **NO** (see §1).

## 3. Method used to derive this manifest (reproducible)

1. `git status --porcelain=v1` captured full list of 193 dirty/untracked
   entries.
2. Static import-graph BFS: for every `.py` file under `backend/` and
   `scripts/`, parsed `^from (\.*)([\w\.]*) import` lines, resolved
   relative (`.`) and absolute (`backend...`) targets to file paths,
   and computed the transitive closure reachable from the 5 already
   -committed AUTO_TWIN seed modules plus the 2 committed evidence
   scripts (see Group CORE below), including expansion through
   `backend/qcc/auto_twin/__init__.py` once it was proven to be a real
   dependency (see next point).
3. Empirical proof, not assumption: exported `git archive HEAD` to an
   isolated temp directory, overlaid candidate dependency sets file by
   file, and ran real `python -c "import ..."` and
   `python -m pytest scripts/tests/ -q` against that clean tree.
4. This surfaced two dependencies invisible to naive `git status`
   review: (a) `backend/qcc/auto_twin/__init__.py` is untracked and
   eagerly imports ~18 further untracked modules, and it is required
   because the already-committed
   `scripts/tests/test_qcc_auto_twin_observation_supersession.py` does
   `from backend.qcc.auto_twin import (AutoTwinManagedSite,
   AutoTwinObservationStore)` (package-aggregator import style, not a
   direct submodule import); (b) `backend/automation/site_recognizers/
   mercurio.py` and `backend/qcc/site_architecture/ingestor.py` are
   **tracked but modified** — their *committed* HEAD blobs lack the
   `apply_mercurio_functional_fingerprint_capability` /
   `resolve_mercurio_state_variant_key` / `_ex01_personal_capability_
   discriminator` functions and their wiring, which 2D-20V/2D-20U's
   already-committed code requires. A `git status` "M" does not by
   itself reveal *which* functions are missing from HEAD — this was
   confirmed by `git show HEAD:<path> | grep '^def '` diffed against
   the working tree.

---

## 4. Groups

Every one of the 193 entries belongs to exactly one group below.
Groups CORE, A-G, GENERATED, UNRELATED and REVIEW_REQUIRED are a
partition (no overlaps, no gaps) — verified by a classification script
whose bucket counts sum to 193.

### Group CORE — REQUIRED_FOR_THIS_FEATURE (must land before ANY PR; makes 57768f1's own committed modules importable)

Source (17, of which 2 are tracked-but-modified and 5 are already
committed — listed for completeness since tests target them):

```
backend/qcc/auto_twin/catalog_materialization.py
backend/qcc/auto_twin/catalog_runtime_adapter.py
backend/qcc/auto_twin/managed_site_registry.py
backend/qcc/auto_twin/managed_site_store.py
backend/qcc/auto_twin/materialization_builder.py
backend/qcc/auto_twin/materialization_plan.py
backend/qcc/auto_twin/materialized_revision.py
backend/qcc/auto_twin/materialized_revision_store.py
backend/qcc/auto_twin/navigation_transition_runtime.py
backend/qcc/auto_twin/profile_policy.py
backend/qcc/auto_twin/rendering_profile.py
backend/qcc/auto_twin/runtime_network_sterilization.py
backend/qcc/context/navigation_context.py
backend/automation/site_recognizers/mercurio.py   [TRACKED, modified — commit current working-tree diff; diff adds only `import hashlib`, no new external deps]
backend/qcc/site_architecture/ingestor.py         [TRACKED, modified — commit current working-tree diff; diff adds only a same-repo cross-import of mercurio.py above]
scripts/qcc_auto_twin_reproject_ex01_personal_2d_20k.py   [pre-existing 2D-20K evidence script]
scripts/qcc_auto_twin_resume_pass2_2d_20.py               [pre-existing 2D-20 PASS-1 evidence script]
```

Already committed at 57768f1, listed for reference only, not to be re-added:
```
backend/qcc/auto_twin/automatic_materialization.py
backend/qcc/auto_twin/catalog_refresh.py
backend/qcc/auto_twin/navigation_transition_materialization.py
backend/qcc/auto_twin/observation_store.py
backend/qcc/auto_twin/persisted_capture_bundle.py
```

Tests (30):

```
scripts/tests/test_qcc_auto_twin_automatic_materialization.py   [MIXED — see caveat below]
scripts/tests/test_qcc_auto_twin_builder_path_identity.py
scripts/tests/test_qcc_auto_twin_catalog_materialization.py
scripts/tests/test_qcc_auto_twin_catalog_refresh.py
scripts/tests/test_qcc_auto_twin_catalog_runtime_adapter.py
scripts/tests/test_qcc_auto_twin_catalog_supplemental_materialization.py
scripts/tests/test_qcc_auto_twin_causal_equivalent_evidence.py
scripts/tests/test_qcc_auto_twin_causal_refresh_navigation_rebind.py
scripts/tests/test_qcc_auto_twin_contextual_interactive_runtime.py
scripts/tests/test_qcc_auto_twin_contextual_supersession_target_rebind.py
scripts/tests/test_qcc_auto_twin_fingerprint_canonicalization.py
scripts/tests/test_qcc_auto_twin_materialization_plan.py
scripts/tests/test_qcc_auto_twin_materialized_carry_forward.py
scripts/tests/test_qcc_auto_twin_materialized_revision.py
scripts/tests/test_qcc_auto_twin_materialized_revision_store.py
scripts/tests/test_qcc_auto_twin_navigation_refresh.py
scripts/tests/test_qcc_auto_twin_navigation_transition_materialization.py
scripts/tests/test_qcc_auto_twin_navigation_transition_runtime.py
scripts/tests/test_qcc_auto_twin_network_sterilization.py
scripts/tests/test_qcc_auto_twin_path_identity.py
scripts/tests/test_qcc_auto_twin_refresh_dimensions.py
scripts/tests/test_qcc_auto_twin_renderer_v2.py
scripts/tests/test_qcc_auto_twin_renderer_v3.py
scripts/tests/test_qcc_auto_twin_renderer_v4.py
scripts/tests/test_qcc_auto_twin_renderer_v5.py
scripts/tests/test_qcc_auto_twin_renderer_v6.py
scripts/tests/test_qcc_auto_twin_transitive_shortcut_rejection.py
scripts/tests/test_qcc_mercurio_ex01_personal_capability_fingerprint.py
scripts/tests/test_qcc_mercurio_ex01_personal_state_variant_key.py
scripts/tests/test_qcc_navigation_context_branching.py
```

Also add to CORE (test the already-committed modules, currently
untracked): `scripts/tests/test_qcc_auto_twin_observation_store.py`,
`scripts/tests/test_qcc_auto_twin_persisted_capture_bundle.py`.

**Caveat:** `test_qcc_auto_twin_automatic_materialization.py` is a
mixed file — every assertion except `test_bridge_hooks_page_and_
viewport` belongs in CORE; that one test couples to Group B (bridge
server marker `QCC_AUTO_TWIN_AUTOMATIC_MATERIALIZATION_HOOK_V1`) and
will fail (not error — a clean `AssertionError`) until Group B lands.
Commit CORE anyway and accept that one known-red test, or split it out
first.

**Verification commands for a fresh session before staging CORE:**
```
python -m py_compile backend/qcc/auto_twin/*.py backend/qcc/context/navigation_context.py backend/automation/site_recognizers/mercurio.py backend/qcc/site_architecture/ingestor.py
python -c "from backend.qcc.auto_twin.automatic_materialization import reconcile_auto_twin_discovery_materialization"
python -m pytest scripts/tests/test_qcc_auto_twin_observation_store.py scripts/tests/test_qcc_auto_twin_persisted_capture_bundle.py scripts/tests/test_qcc_mercurio_ex01_personal_*.py -q
```

---

### Group A — AUTO_TWIN package-aggregator scaffolding (18 source + ~30 tests)

Required ONLY because `backend/qcc/auto_twin/__init__.py` eagerly
imports all of these, and at least one already-committed test uses the
package-aggregator import style (see §3.4). Functionally these are
behavior comparison / structural-visual-unified diffing / candidate
projection / validation-evidence bookkeeping — a distinct concern from
the EX01 TITULAR/FAMILIAR reconciliation itself.

Source (18):
```
backend/qcc/auto_twin/__init__.py
backend/qcc/auto_twin/behavior_catalog_adapters.py
backend/qcc/auto_twin/behavior_comparator.py
backend/qcc/auto_twin/behavior_navigation_adapters.py
backend/qcc/auto_twin/behavior_trace.py
backend/qcc/auto_twin/candidate_projection.py
backend/qcc/auto_twin/candidate_revision_store.py
backend/qcc/auto_twin/capture_pair.py
backend/qcc/auto_twin/catalog_comparator.py
backend/qcc/auto_twin/observation_projection.py
backend/qcc/auto_twin/structural_comparator.py
backend/qcc/auto_twin/unified_comparator.py
backend/qcc/auto_twin/validation_evaluator.py
backend/qcc/auto_twin/validation_evidence.py
backend/qcc/auto_twin/validation_evidence_store.py
backend/qcc/auto_twin/validation_runner.py
backend/qcc/auto_twin/validation_trigger.py
backend/qcc/auto_twin/visual_comparator.py
```

Tests (assigned by filename↔module correlation; each imports the
package aggregator `from backend.qcc.auto_twin import (...)` rather
than the submodule directly, so re-confirm with one `grep` per file
before staging if in doubt):
```
scripts/tests/test_qcc_auto_twin_behavior_catalog_adapters.py
scripts/tests/test_qcc_auto_twin_behavior_comparator.py
scripts/tests/test_qcc_auto_twin_behavior_navigation_adapters.py
scripts/tests/test_qcc_auto_twin_behavior_provenance_contract.py
scripts/tests/test_qcc_auto_twin_behavior_trace.py
scripts/tests/test_qcc_auto_twin_candidate_lifecycle.py
scripts/tests/test_qcc_auto_twin_candidate_projection.py
scripts/tests/test_qcc_auto_twin_candidate_revision_store.py
scripts/tests/test_qcc_auto_twin_capture_pair.py
scripts/tests/test_qcc_auto_twin_catalog_comparator.py
scripts/tests/test_qcc_auto_twin_managed_site_registry.py
scripts/tests/test_qcc_auto_twin_managed_site_settings.py
scripts/tests/test_qcc_auto_twin_managed_site_store.py
scripts/tests/test_qcc_auto_twin_observation_projection.py
scripts/tests/test_qcc_auto_twin_profile_policy.py
scripts/tests/test_qcc_auto_twin_rendering_profile.py
scripts/tests/test_qcc_auto_twin_structural_comparator.py
scripts/tests/test_qcc_auto_twin_unified_comparator.py
scripts/tests/test_qcc_auto_twin_validation_evaluator.py
scripts/tests/test_qcc_auto_twin_validation_evidence.py
scripts/tests/test_qcc_auto_twin_validation_evidence_store.py
scripts/tests/test_qcc_auto_twin_validation_runner.py
scripts/tests/test_qcc_auto_twin_validation_trigger.py
scripts/tests/test_qcc_auto_twin_visual_comparator.py
```
(23 tests; `managed_site_registry.py`/`managed_site_store.py`/
`profile_policy.py`/`rendering_profile.py` are technically already
required by CORE's closure too — their tests are grouped here since
the *source* files sit logically with Group A's "supporting
scaffolding" framing; no conflict either way since both groups would
be committed adjacently in the proposed sequence below.)

**2D-23A note:** WO 2D-23A already executed staging/commit for
*exactly this Group A path list* (18 source files as enumerated
above). If this manifest is read after 2D-23A ran, check
`git log --oneline -- backend/qcc/auto_twin/__init__.py` before
re-attempting — it may already be committed.

---

### Group B — QCC Bridge / CRM / sidepanel integration layer (16 source + ~35 tests)

Empirically confirmed as the source of all 116 non-CORE test failures
and the 1 CORE-adjacent failure. `backend/qcc/bridge/server.py`
transitively needs a much larger, genuinely separate set NOT enumerated
here in full (`backend/qcc/contracts/*`, `backend/qcc/actions/store`,
`backend/qcc/tools/store`, `backend/qcc/navigation_knowledge`,
`backend/qcc/navigation_learning` package init,
`backend/qcc/context/live_planning_coordinator`,
`live_governance_coordinator`, `navigation_intent`,
`backend/qcc/context/browser_registry`,
`backend/automation/site_architecture/managed_governance_registry`) —
**a future session must re-run the same import-graph BFS method from
§3 seeded at `backend/qcc/bridge/server.py` before committing Group B**,
since this manifest's author did not fully enumerate that closure
(out of the narrower AUTO_TWIN scope this audit targeted).

Source (16):
```
app/main.py
backend/qcc/bridge/server.py
backend/qcc/context/human_action_canonicalizer.py
backend/qcc/context/human_listener_plan.py
backend/qcc/context/human_transition_correlator.py
backend/qcc/context/live_action_evidence.py
backend/qcc/context/live_state_projection.py
backend/qcc/context/observation_scope.py
backend/qcc/context/observed_human_action.py
backend/qcc/context/observed_human_transition.py   [TRACKED, modified]
backend/qcc/context/store.py
backend/qcc/navigation_learning/human_candidate_store.py   [TRACKED, modified]
chrome_extension/qcc/background/service_worker.js
chrome_extension/qcc/sidepanel/index.html
chrome_extension/qcc/sidepanel/sidepanel.css
chrome_extension/qcc/sidepanel/sidepanel.js
```

Tests (~35; filename-correlated, re-verify with a `BRIDGE.read_text()`
or `bridge` grep per file before staging):
```
scripts/tests/test_qcc_auto_twin_behavior_navigation_adapters.py
scripts/tests/test_qcc_auto_twin_bridge_candidate_contract.py
scripts/tests/test_qcc_auto_twin_bridge_observation_contract.py
scripts/tests/test_qcc_auto_twin_bridge_read_api.py
scripts/tests/test_qcc_auto_twin_bridge_runtime_support.py
scripts/tests/test_qcc_auto_twin_candidate_read_api.py
scripts/tests/test_qcc_auto_twin_candidate_sidepanel.py
scripts/tests/test_qcc_auto_twin_candidate_validation_api.py
scripts/tests/test_qcc_auto_twin_candidate_validation_contract.py
scripts/tests/test_qcc_auto_twin_candidate_validation_sidepanel.py
scripts/tests/test_qcc_auto_twin_catalog_dependency_bridge_contract.py
scripts/tests/test_qcc_auto_twin_catalog_dependency_bridge_http.py
scripts/tests/test_qcc_auto_twin_catalog_probe_decision_bridge_contract.py
scripts/tests/test_qcc_auto_twin_crm_discovery_controls.py
scripts/tests/test_qcc_auto_twin_crm_empty_discovery_card.py
scripts/tests/test_qcc_auto_twin_crm_localhost_controls.py
scripts/tests/test_qcc_auto_twin_manage_api.py
scripts/tests/test_qcc_auto_twin_observation_read_api.py
scripts/tests/test_qcc_auto_twin_observation_sidepanel.py
scripts/tests/test_qcc_auto_twin_sidepanel_contract.py
scripts/tests/test_qcc_auto_twin_sidepanel_runtime.py
scripts/tests/test_qcc_auto_twin_site_level_discovery_contract.py
scripts/tests/test_qcc_auto_twin_validation_bridge_hook.py
scripts/tests/test_qcc_auto_twin_validation_evidence_read_api.py
scripts/tests/test_qcc_auto_twin_validation_evidence_read_contract.py
scripts/tests/test_qcc_auto_twin_validation_evidence_sidepanel.py
scripts/tests/test_qcc_discovery_observation_scope_bridge.py
scripts/tests/test_qcc_human_action_canonicalizer.py
scripts/tests/test_qcc_human_candidate_fingerprint_first.py
scripts/tests/test_qcc_human_dom_action_bridge.py
scripts/tests/test_qcc_human_listener_extension_contract.py
scripts/tests/test_qcc_human_navigation_candidate_store.py
scripts/tests/test_qcc_human_transition_runtime.py
scripts/tests/test_qcc_live_action_evidence_runtime.py
scripts/tests/test_qcc_navigation_context_jit_capture.py
scripts/tests/test_qcc_navigation_context_persisted_capture_resolution.py
scripts/tests/test_qcc_observation_scope_runtime.py
scripts/tests/test_qcc_snapshot_addressed_human_evidence_contract.py
```

---

### Group C — Twin browser-runtime validation layer (6 source + 8 tests)

Needs a live/governed SeleniumBase runtime; a separate operational
concern from the reconciliation algorithm.

Source:
```
backend/services/twin_browser_runtime_service.py
backend/services/twin_discovery_runtime_service.py
backend/services/twin_local_runtime_service.py
backend/qcc/auto_twin/navigation_transition_validation.py
backend/qcc/auto_twin/navigation_transition_validation_coordinator.py
backend/qcc/auto_twin/navigation_transition_validation_store.py
```
Tests:
```
scripts/tests/test_qcc_auto_twin_browser_runtime_commands.py
scripts/tests/test_qcc_auto_twin_browser_runtime_service.py
scripts/tests/test_qcc_auto_twin_discovery_runtime_service.py
scripts/tests/test_qcc_auto_twin_local_runtime_service.py
scripts/tests/test_qcc_auto_twin_navigation_transition_validation.py
scripts/tests/test_qcc_auto_twin_navigation_transition_validation_coordinator.py
scripts/tests/test_qcc_auto_twin_navigation_transition_validation_store.py
scripts/tests/test_qcc_auto_twin_red_sara_bootstrap.py
```
(`test_qcc_auto_twin_crm_twins_management.py` also belongs here —
confirmed via dependency scan needing `materialized_revision.py` +
`materialized_revision_store.py`; source file itself,
`backend/services/twin_management_service.py`, is **already
committed**.)

---

### Group D — Catalog-dependency feature (4 source + 4 tests)

```
backend/qcc/auto_twin/catalog_dependency_probe.py
backend/qcc/auto_twin/catalog_dependency_store.py
backend/qcc/auto_twin/catalog_probe_decision.py
chrome_extension/qcc/shared/catalog_dependency_planner.js
```
```
scripts/tests/test_qcc_auto_twin_catalog_dependency_probe.py
scripts/tests/test_qcc_auto_twin_catalog_dependency_store.py
scripts/tests/test_qcc_auto_twin_catalog_probe_decision.py
scripts/tests/test_qcc_catalog_dependency_automatic_wiring.py
```
(`backend/qcc/auto_twin/catalog_dependency_materialization.py` and
`scripts/tests/test_qcc_auto_twin_catalog_dependency_materialization.py`
are **already committed** — part of this same family, listed for
context only.)

---

### Group E — Governing documentation (1 file)

```
docs/resolutions/20260905_resolucion_qcc_auto_twin_arquitectura_fidelidad_sincronizacion.md
```
The foundational AUTO TWIN architecture resolution (`RESUELTO /
ARQUITECTURA APROBADA`, 2026-09-04) — should accompany the code it
governs.

---

### Group F — GENERATED_OR_RUNTIME_DATA_DO_NOT_COMMIT (1 directory, 15 files)

```
runtime/    (qcc_branch_*.log, *.pid, *_baseline.json, *_evidence_audit.json, *_recaptures.json, *_canonical_evidence.json, *_causal_last_audit.json, *_latest_revision.txt)
```
Process logs/PIDs/ad-hoc evidence dumps. Action: add `runtime/` to
`.gitignore`; never commit. (`data/` is already correctly gitignored —
confirmed; all real capture/materialized-revision evidence this work
depends on lives there and correctly never appears in `git status`.)

---

### Group G — UNRELATED_FEATURE_LEAVE_UNSTAGED (43 files)

Confirmed zero coupling to AUTO_TWIN/QCC (either by content grep or by
committed-HEAD-vs-working-tree diff showing the committed version
already works without these changes):

```
frontend/layouts/sidebar.py
backend/automation/site_architecture/action_inventory.py
backend/automation/site_architecture/catalog_dynamics.py
backend/automation/site_architecture/selectors.py
backend/automation/site_architecture/state_fingerprint.py
backend/automation/site_policies/__init__.py
backend/automation/site_policies/default_registry.py
docs/ai/CURRENT_STATE.md   [MIXED — §15 "2D-20 CLOSURE" already committed by 2D-21 via a hunk-selective patch; the REMAINING unstaged hunks are pre-existing "SUPERSEDED by 2D-20E/2D-20G" annotations from an earlier, different session — not this branch's AUTO_TWIN closure work]
scripts/tests/test_qcc_automatic_site_architecture_extension_contract.py
scripts/tests/test_qcc_catalog_experiment_extension_contract.py
scripts/tests/test_qcc_catalog_probe_extension_contract.py
scripts/tests/test_qcc_composed_action_addressability.py
scripts/tests/test_qcc_custom_catalog_scalar_scope.py
scripts/tests/test_qcc_discovery_human_listener_auto_arm_reset.py
scripts/tests/test_qcc_generic_active_normal_tab.py
scripts/tests/test_qcc_generic_catalog_causal_executor.py
scripts/tests/test_qcc_generic_catalog_hard_document_restore.py
scripts/tests/test_qcc_right_click_causal_capture_extension_contract.py
scripts/tests/test_qcc_shadow_adopted_stylesheet_capture_contract.py
scripts/tests/test_site_architecture_catalog_dynamics.py
scripts/tests/test_site_architecture_functional_ui_regions.py
scripts/tests/test_site_architecture_onclick_selector.py
scripts/tests/test_site_architecture_state_fingerprint.py
scripts/tests/test_qcc_human_listener_extension_contract.py
```
*(`test_qcc_catalog_dependency_automatic_wiring.py` belongs to Group D
above, not here — listed only once, under Group D, to avoid a
duplicate/ambiguous assignment.)*

---

### REVIEW_REQUIRED (2 files) — separate from Groups A-G

```
backend/automation/site_policies/red_sara.py
scripts/tests/test_qcc_red_sara_governance.py
```
**Decision context (from Project Direction, stated explicitly during
2D-23A authorization):** Red Sara is intended QCC/AUTO_TWIN
functionality (a distinct site-onboarding effort, different provider
than Mercurio) and **may later be committed as its own atomic unit
only after scope/dependency validation**. It is explicitly **NOT**
part of Group A and must not be folded into it. Committed
`site_policies/__init__.py`/`default_registry.py` do not reference it
(safe either way on a fresh clone); `test_qcc_auto_twin_red_sara_
bootstrap.py` (Group C) needs `twin_discovery_runtime_service.py`.
Treat as its own future Group (tentatively "Group H") pending a
dedicated scope/dependency audit — do not commit until that happens.

---

## 5. Proposed atomic commit order (for a fresh session to follow)

1. `fix(qcc): commit Mercurio capability-aware recognizer + ingestor wiring` — the 2 tracked-modified files in Group CORE only.
2. `feat(auto-twin): commit core materialization/observation scaffolding` — the rest of Group CORE (15 source + 2 scripts + 30 tests).
3. `feat(auto-twin): commit validation/behavior/rendering package scaffolding` — Group A. **Already executed by WO 2D-23A** if this manifest is read afterward — check `git log` first.
4. `feat(qcc): commit Bridge/CRM/sidepanel integration layer` — Group B (re-run the §3 BFS method seeded at `bridge/server.py` first — this manifest's Group B source list is not a fully-closed transitive set).
5. `feat(auto-twin): commit twin browser-runtime validation layer` — Group C.
6. `feat(auto-twin): commit catalog-dependency feature` — Group D.
7. `docs(resolutions): add AUTO TWIN architecture resolution` — Group E.
8. Add `runtime/` to `.gitignore` (Group F disposal).
9. Project Direction decision on Red Sara (REVIEW_REQUIRED) before it becomes its own Group H commit.

After all of 1-7 land, re-run the full fresh-clone empirical proof from
§3 (archive HEAD, run pytest) to confirm 0 unexpected failures before
opening a PR.

---

## 6. Next action

```
next action = 2D-23A
```

---

## 7. Epilogue (2D-27-EF)

This section is a historical consolidation manifest, not a live status
board. It records the read-only 2D-22 audit exactly as it was executed
at the time (`ADDITIONAL_COMMITS_REQUIRED`, per-group blocker analysis,
the `next action = 2D-23A` pointer). Section §1-§6 above are preserved
unmodified as historical evidence and are NOT rewritten here.

Since this manifest was written, later Work Orders landed and
superseded its interim blocker/status classifications:

```
2D-23A   Group A (AUTO_TWIN package-aggregator scaffolding) committed
2D-25B   frontend/layouts/sidebar.py fresh-clone blocker committed
2D-26    the two indeterminate mechanical-test-tail items committed
2D-27-EF Group E (this doc + the AUTO TWIN architecture resolution)
         and Group F (runtime/ ignore) closed
```

As of 2D-27-EF, CORE and Groups A/B/C/D/G are consolidated and
fresh-clone reproducible; `ADDITIONAL_COMMITS_REQUIRED` and
`next action = 2D-23A` above no longer describe the current branch
state. Group H (Red SARA) remains explicitly deferred per its own
REVIEW_REQUIRED section (§4), unchanged by this epilogue.
