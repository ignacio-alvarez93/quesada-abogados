# QCC AUTO TWIN — Materialization Action Trace + Closure V1

## Execution constraint (read first)

This session's tool set did not include a shell/terminal execution
tool (only file read/write/edit/grep/glob). All findings below up to
and including "Root cause and fix" were established by direct,
exhaustive reading of the curated evidence in `.fabric_evidence/` and
of the actual repository source, including cross-checking every
existing test in `scripts/tests/` that touches the affected code path.

The following required steps could **not** be executed in this
session and are reported as such, not fabricated:

- running `pytest` (new test file, targeted suites, full regression);
- `python -m py_compile` on the changed files;
- running the normal automatic materializer to produce a NEW candidate
  revision from the real Mercurio evidence;
- the governed SeleniumBase Twin smoke (initial state -> EX19 via
  normal interaction, second-branch check);
- `git status`/commit.

Everything else in this report — evidence tracing, root cause, the
code fix, and the new regression test — is complete and ready to run.

## Initial state and causal pipeline

```
INITIAL_STATE = AUTO_88105E85ACF0C6413288A69F (/mercurio/inicioMercurio.html)
EX19_TARGET_STATE = AUTO_B60CDAC245925D6546CE8E3E (/mercurio/nuevaSolicitud-EX19.html)
OLD_CANDIDATE = matrev-c94d8c0ad27096203e29780d
ACTIVE = matrev-11ae7e269aefca0a8f0af7cd
```

```
REAL human observation (3x, CONFIRMED)
  -> HumanNavigationCandidateStore (candidate 1ef6661e...39, selector
     a[onclick="continuar();"])
  -> project_twin_eligible_navigation_candidates()
  -> normalize_twin_navigation_transitions()
  -> classify_twin_navigation_transition_outcomes()  (DETERMINISTIC)
  -> materialize_auto_twin_plan() / materialization_builder.py
       -> restore_navigation_action_identity()   <-- FIRST LOSS
       -> excluded from `outgoing`
       -> inject_navigation_runtime_adapter() never sees it
  -> recorded in runtime/deferred_navigation_transitions.json
     (deferral_reason =
      QCC_AUTO_TWIN_NAVIGATION_ACTION_EVIDENCE_AMBIGUOUS:
      a[onclick="continuar();"])
```

## The problematic action

- `before_state_id`: `AUTO_88105E85ACF0C6413288A69F`
- `after_state_id` (learned): `AUTO_8D1CFEC4C826E142EA81AEE9`
- `action.selector`: `a[onclick="continuar();"]`
- `candidate_id`: `1ef6661e769b4e8ee0e33854f0bdbadffa58e4acf68671836d2a0dd393df8b39`
- `candidate_status`: `CONFIRMED`, `real_observation_count`: `3`

Confirmed directly in
`.fabric_evidence/candidate_deferred_transitions.json` and
`.fabric_evidence/human_navigation_candidates.json`.

## Real evidence

`.fabric_evidence/initial_qcc_capture.json` contains **exactly one**
element on the initial state's main frame matching tag `a` with an
`onclick` attribute beginning with `continuar`:

```json
{
  "attributes": {
    "class": "mbbuttton simbutton buttonAction adelanta",
    "href": "#",
    "onclick": "continuar('INI');",
    "tooltip": "asasdñf"
  }
}
```

The physical attribute is `onclick="continuar('INI');"` — **with** the
literal argument `'INI'`. The persisted selector is
`a[onclick="continuar();"]` — **without** it.

## Resolving the Section 9 evidence discrepancy

1. **Source of the alleged duplicated evidence**: not a duplicate on
   the same page at all. `backend/automation/site_architecture/
   selectors.py` (`_onclick_structural_signature`,
   `QCC_ONCLICK_STRUCTURAL_SIGNATURE_V1`) deliberately strips onclick
   literal arguments before a selector is ever persisted, precisely
   because a literal argument can carry PII/dynamic values. This is
   correct, intentional, pre-existing design — not a bug and not a
   duplicate element.
2. Direct read of `initial_qcc_capture.json` confirms the selector
   attributes to **exactly one** physical element on
   `AUTO_88105E85ACF0C6413288A69F`, not zero and not several.
3. It belongs to that exact before-state (same capture, same frame).
4. `qcc_capture.json` **is** authoritative for reconstructing human
   action identity — the existing `restore_navigation_action_identity()`
   architecture (evidence-element correlation, then runtime-DOM
   correlation) is the right design.
5. No more precise causal action evidence object is needed.
6. Materialization was **not** looking at the wrong evidence surface.
   It was looking at the right surface (`qcc_capture.json`'s main-frame
   elements) but comparing the wrong **representation** of the
   `onclick` value: a raw literal captured value against an
   already-PII-stripped structural selector value, using plain string
   equality instead of the same structural transform on both sides.

The previously invalidated hypothesis (branch
`fix/qcc-action-evidence-identity-v2`, duplicate
`a[onclick="continuar();"]`) was correct that this selector is
involved, but wrong about *why* it fails: there is no duplicate
element on the page. `CONTINUAR_MATCHES=0 / ACTIONABLE_COUNT=0` for an
**exact-literal** search against `a[onclick="continuar();"]` is
expected and correct, because the real attribute is
`continuar('INI');`, not `continuar();`. The defect is a
representation mismatch, not a missing/ambiguous element.

## FIRST_LOSS_STAGE

Evaluating each stage (A–Q from the work order):

| Stage | Status |
|---|---|
| A–F (capture, persistence, projection, candidate generation, before/after fingerprint) | Intact — confirmed by evidence files |
| G (action identity/selector) | Intact — correctly generated by `selectors.py` as a structural signature |
| H/I (frame_path, context) | Intact |
| J/K (normalization, classification) | Intact — classified `DETERMINISTIC`, one target |
| L (deferred/exclusion filtering) | **LOSS HAPPENS HERE** — `restore_navigation_action_identity()` in `navigation_transition_runtime.py` |
| M–Q (materialization plan, physical state resolution, runtime payload, DOM binding, browser execution) | Never reached for this candidate — excluded upstream at L |

```
FIRST_LOSS_STAGE = L (deferred/exclusion filtering, inside
                       restore_navigation_action_identity())
LAST_GOOD_STAGE  = K (classify_twin_navigation_transition_outcomes ->
                       DETERMINISTIC)
```

## Root cause

`restore_navigation_action_identity()`
(`backend/qcc/auto_twin/navigation_transition_runtime.py`) compared
the selector's embedded `on*` attribute value against the raw QCC
evidence attribute value (and, further down, against the runtime
MHTML's already-present attribute value) using plain string equality.

For `onclick` specifically, the selector's embedded value is not the
literal handler call — it is the PII-stripped **structural signature**
produced by `selectors.py`. Any real element whose `onclick` carries an
argument (the overwhelmingly common case for parametrized navigation
handlers like `continuar('INI')`) can therefore never equal its own
selector's value under plain string equality, so
`evidence_matches` is always empty, and the transition is
unconditionally excluded as `ACTION_EVIDENCE_AMBIGUOUS` — regardless of
how unambiguous the real page actually is.

This exactly matches the browser-side runtime click adapter's own
prior design intent: `navigation_transition_runtime.py`'s injected
JavaScript already implements a structural-signature fallback
(`qccOnclickStructuralSignature` / `qccMatchesOnclickStructural`) for
matching a click event against a selector whose literal argument was
stripped (see the pre-existing test
`test_adapter_matches_sanitized_structural_onclick_against_physical_
literal`). That fallback, however, only ever runs once a transition
has already survived `restore_navigation_action_identity()` and been
wired into `outgoing`. The identity-restoration/evidence-matching step
that runs *before* it had no equivalent structural comparison, so the
transition was dropped before the already-correct runtime fallback
ever got a chance to execute.

## Fix

1. `backend/automation/site_architecture/selectors.py`: exposed the
   existing private `_onclick_structural_signature()` transform under
   a public name, `onclick_structural_signature`, so it can be reused
   verbatim (not duplicated) wherever onclick identity must be
   compared outside this module.
2. `backend/qcc/auto_twin/navigation_transition_runtime.py`: added
   `_event_value_matches(event_attribute, event_value, observed_value)`
   — exact literal equality for every `on*` attribute, plus a
   structural-signature fallback for `onclick` specifically (mirroring
   exactly what the injected browser-side adapter already does for
   click matching). Used it in both places that previously compared
   raw literals:
   - the QCC-evidence `evidence_matches` search (identity resolution);
   - the runtime-DOM `existing_value` conflict check (so an
     already-present, literal-argument `onclick` attribute in the
     materialized MHTML is recognized as the same handler instead of
     raising `RUNTIME_EVENT_CONFLICT`).

Properties:

- Localized to the exact comparison that was wrong; no other behavior
  changed.
- Deterministic — pure string transform, no ordering/heuristic
  dependence.
- Reusable/provider-neutral/site-neutral — no Mercurio- or
  EX19-specific logic; it only recognizes the same structural-identity
  rule already codified for `onclick` everywhere else in this
  codebase.
- Fail-closed preserved: two physically distinct elements whose
  `onclick` literals collapse to the same structural signature (e.g.
  `continuar('INI')` vs `continuar('OTRA')` on the same page) still
  produce `len(evidence_matches) != 1` and are still excluded/deferred
  — the fix never fabricates uniqueness the evidence does not support.
  A genuinely different handler (different structural signature) on a
  non-onclick attribute, or an onclick handler that fails the existing
  safe-handler allowlist, is unaffected and still fails closed exactly
  as before.

### Files changed

- `backend/automation/site_architecture/selectors.py`
- `backend/qcc/auto_twin/navigation_transition_runtime.py`

No other file required a change. The pipeline stages upstream of L
(A–K) and downstream (M–Q) were already correct; only the comparison
at L needed correcting.

## Regression test

`scripts/tests/test_qcc_auto_twin_materialization_action_trace_v1.py`
(new). Covers, against the exact real
`onclick="continuar('INI');"` / `a[onclick="continuar();"]` shape:

- T1/T3: the real literal-argument action is no longer excluded and
  is wired into the materialized runtime route
  (`test_literal_argument_onclick_is_no_longer_ambiguous`,
  `test_structural_onclick_action_materializes_as_executable_route`).
- Control: non-`onclick` event attributes keep exact literal
  comparison and still fail closed on mismatch
  (`test_non_onclick_event_attribute_keeps_exact_literal_comparison`).
- T5: two physically distinct elements sharing one structural
  signature (different literal arguments) still stay ambiguous/deferred
  (`test_two_distinct_literals_sharing_one_structural_signature_stay_
  ambiguous`).
- T2/T8: an independent before-state sharing only the structural
  signature resolves to its own, different after-state, with no
  cross-contamination.
- T6: a `HUMAN_ONLY`-policy candidate is still materialized/learnable
  in the Twin (no REAL authority implied).
- T9: re-materializing identical evidence into a fresh target produces
  an identical executable route set.
- T10/T11: deferred-sidecar emptiness and per-candidate provenance are
  asserted explicitly once the fix is applied.

T4 (zero AFTER -> deferred) and T12 (ACTIVE governance) are already
covered by the existing `navigation_transition_runtime` /
`active_revision` suites and intentionally not duplicated here.

**This test file has not been executed in this session** (no shell
tool available). It was written to exactly mirror the already-passing
`test_qcc_action_evidence_ambiguity_fix1.py` fixture conventions
(same `materialize_auto_twin_plan` golden-world pattern) to minimize
the risk of a harness mismatch, but it must be run before this fix is
considered closed.

## Existing regression suites reviewed (not executed)

Read in full and manually checked against the fix for compatibility:

- `scripts/tests/test_qcc_auto_twin_navigation_transition_runtime.py`
  — every `restore_navigation_action_identity` test uses either an
  exact-literal match (unaffected: the exact-match branch is
  unchanged) or the pre-existing browser-side structural fallback via
  `inject_navigation_runtime_adapter` directly (unaffected: that code
  path was not touched).
- `scripts/tests/test_qcc_action_evidence_ambiguity_fix1.py` — its
  ambiguous fixture uses **two elements with the identical literal**
  `onclick="continuar();"` (no argument on either). Both sides of the
  comparison remain exact-literal matches under the fix, so both still
  match, evidence_matches still has 2 entries, and the transition is
  still correctly excluded/deferred. This existing regression is not
  weakened.
- `scripts/tests/test_qcc_auto_twin_navigation_transition_materialization.py`,
  `test_qcc_auto_twin_navigation_transition_validation*.py`,
  `test_qcc_auto_twin_automatic_materialization.py`,
  `test_qcc_auto_twin_candidate_entry_routing.py`,
  `test_qcc_auto_twin_active_revision.py`,
  `test_qcc_auto_twin_post_human_learning_reconcile.py`,
  `test_qcc_auto_twin_crm_twins_management.py` — none of these call
  `restore_navigation_action_identity`'s literal-comparison branches
  with a mismatched onclick-with-argument fixture, so none are
  expected to change outcome. **Not executed; must be confirmed by
  running `pytest` before closure.**

## Rematerialization, governed smoke, ACTIVE governance

Not performed in this session (no shell/materializer/SeleniumBase
execution available). Required next steps for whoever continues this
work order:

1. `python -m py_compile backend/automation/site_architecture/selectors.py backend/qcc/auto_twin/navigation_transition_runtime.py`
2. `pytest scripts/tests/test_qcc_auto_twin_materialization_action_trace_v1.py scripts/tests/test_qcc_action_evidence_ambiguity_fix1.py scripts/tests/test_qcc_auto_twin_navigation_transition_runtime.py scripts/tests/test_qcc_auto_twin_navigation_transition_materialization.py scripts/tests/test_qcc_auto_twin_automatic_materialization.py scripts/tests/test_qcc_auto_twin_candidate_entry_routing.py scripts/tests/test_qcc_auto_twin_active_revision.py scripts/tests/test_qcc_auto_twin_post_human_learning_reconcile.py scripts/tests/test_qcc_auto_twin_crm_twins_management.py`
3. Run the normal automatic materializer against the real Mercurio
   evidence to produce a NEW candidate revision (never mutate
   `matrev-c94d8c0ad27096203e29780d`); compare state/transition/
   deferred counts against the old candidate.
4. Open the NEW candidate with the governed SeleniumBase Twin runtime,
   starting from `AUTO_88105E85ACF0C6413288A69F`, and confirm the
   `continuar('INI')` control now navigates to its real learned
   after-state (not `AUTO_B60CDAC245925D6546CE8E3E` directly — EX19 is
   several hops downstream per the materialized route table, so the
   full multi-hop path to EX19 must be walked and confirmed).
5. Confirm `matrev-11ae7e269aefca0a8f0af7cd` (ACTIVE) is byte-for-byte
   unchanged (`git status`/hash comparison) before and after.

## Remaining genuine risks

- The fix has not been exercised against the full real
  `human_navigation_candidates.json` set; other selectors/actions on
  the path to EX19 were not individually re-verified for a similar
  representation mismatch (only the initial-state `continuar()` hop
  was confirmed from evidence). A full rematerialization is required
  to confirm no further hop is deferred for an unrelated reason.
- Test execution, rematerialization, and the governed smoke are
  unexecuted; this report's conclusions about the fix's correctness
  rest on static code/evidence tracing plus manual compatibility
  review against every existing test that exercises the changed
  function, not on an actual test run.

---

## Closure evidence update · 2026-10-01

The earlier execution-status note is superseded by direct validation.

Validated:

- `git diff --check`: PASS.
- Python compile validation: PASS.
- targeted regression suite: `133 passed`.
- productive AUTO TWIN two-pass materialization: PASS.
- old candidate:
  - revision: `matrev-c94d8c0ad27096203e29780d`
  - states: 32
  - interactive transitions: 6
  - deferred navigation transitions: 2
- new candidate:
  - revision: `matrev-ad0fda58e05842a50b64fcc7`
  - states: 32
  - interactive transitions: 9
  - deferred navigation transitions: 0
- causal candidate
  `1ef6661e769b4e8ee0e33854f0bdbadffa58e4acf68671836d2a0dd393df8b39`
  is materialized and no longer deferred.
- learned transition:
  `AUTO_88105E85ACF0C6413288A69F`
  →
  `AUTO_8D1CFEC4C826E142EA81AEE9`
- physical Twin smoke with a live runtime owner:
  initial `Continuar` transition works.
- ACTIVE remained:
  `matrev-11ae7e269aefca0a8f0af7cd`
- ACTIVE materialized tree remained byte-for-byte unchanged.

The candidate revision is not treated as a complete Mercurio regression
environment. Other contextual transitions remain unresolved and are outside
the causal defect fixed by this Work Order.

Separate follow-up:
`scripts/maintenance/qcc_open_candidate_twin.py` returns immediately after
starting the governed candidate runtime, causing its process-owned local
runtime to terminate. This tooling lifecycle issue does not block integration
of the materialization/action-identity fix.
