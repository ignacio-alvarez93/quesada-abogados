# Quesada Abogados — Current Development State

**Date:** 2026-09-12
**Purpose:** Operational handoff state for AI-assisted development
**Normative authority:** Project resolutions
**This document:** Operational only; update as the project advances

---

# 1. Current branch

Current development branch:

```text
feature/qcc-live-navigation-intelligence
```

At the start of the Claude Code transition, the branch is substantially ahead of its remote counterpart and contains significant uncommitted work.

Reference observed immediately before creating the AI governance layer:

```text
local branch ahead of origin by 37 commits
working tree contains many modified and untracked files
```

This existing work MUST be preserved.

Do not assume untracked files are disposable.

Do not run destructive cleanup commands.

---

# 2. Current development domain

The active development area is:

```text
QCC
+
AUTO TWIN
+
Mercurio
+
Live Navigation Intelligence
```

The project is not currently in a general ERP refactor phase.

The immediate technical work belongs to the AUTO TWIN / navigation materialization line.

---

# 3. AUTO TWIN architectural status

AUTO TWIN is already a substantial implemented subsystem.

Relevant implementation currently exists under areas including:

```text
backend/qcc/auto_twin/
backend/qcc/context/
backend/qcc/navigation_learning/
backend/qcc/site_architecture/
backend/automation/site_architecture/
backend/automation/site_policies/
backend/services/
chrome_extension/qcc/
scripts/tests/
```

Do not treat AUTO TWIN as a greenfield module.

Inspect existing implementation before changing it.

---

# 4. Core AUTO TWIN doctrine

AUTO TWIN belongs to QCC.

Its objective is to maintain governed local replicas of observed websites with high fidelity across applicable dimensions:

```text
FUNCTIONAL
DOM
CSS
GEOMETRY
VISUAL
CATALOG
INTERACTION
NAVIGATION
```

The Twin is intended as the preproduction environment in which automation behavior can be validated before REAL execution.

---

# 5. Twin browser rule

The local Twin must run inside a governed SeleniumBase runtime.

Do NOT use the user's ordinary Chrome as the operational Twin environment.

The repository already contains Twin runtime services.

Known relevant services include:

```text
backend/services/twin_browser_runtime_service.py
backend/services/twin_discovery_runtime_service.py
backend/services/twin_local_runtime_service.py
```

Prefer existing runtime infrastructure over creating manual browser launch instructions.

---

# 6. Discovery model

The architecture distinguishes between:

```text
REAL assisted browser profiles
→ observation

TWIN DISCOVERY profile
→ observation + governed discovery
```

REAL profiles observe site behavior during ordinary work.

They must not perform uncontrolled active exploration capable of interfering with real administrative activity.

TWIN DISCOVERY may safely explore when policy allows.

---

# 7. Mercurio scope doctrine

Mercurio Discovery is site-level.

It is not an EX01-specific crawler.

EX01 is currently the seed/evidence area under active development, but Mercurio Twin must remain capable of learning the wider site.

Procedure-specific branches are learned incrementally.

---

# 8. Current EX01 navigation findings

REAL evidence has established:

```text
datosForAut=130
= EX01_RENOVACION_TITULAR
= Renovación · Titular

datosForAut=131
= Renovación · Familiar
```

Both originate from:

```text
EX01_AUTHORIZATION
```

and both lead immediately to:

```text
EX01_PERSONAL
```

The context differs.

The physical target state does not.

Therefore there must NOT be separate physical Twin destination states for 130 and 131.

The correct navigation model is conceptually:

```text
130 ─┐
     ├── EX01_AUTHORIZATION + CONTINUAR → EX01_PERSONAL
131 ─┘
```

with a single deterministic physical transition and preservation of both REAL observations as evidence.

---

# 9. Functional State V3 evidence

Known functional fingerprints:

## EX01_AUTHORIZATION

```text
0f048a41feded5af2ceae831e57bf6c1d79d3d86ccfe991c698a5b21e3e7aca2
```

## EX01_PERSONAL

```text
d0af84caa02f93f585f9df7f3e2ef82b487348a64550e07c54f481e58e84e2f4
```

Important invariant:

```text
PERSONAL 130 == PERSONAL 131
```

The selected 130/131 branch must not contaminate the physical functional fingerprint of `EX01_PERSONAL`.

Navigation context and physical state identity are separate concepts.

---

# 10. Known REAL navigation candidates

Candidate for branch 130:

```text
0b9da55ea870596b1bbc8f6c00b09f727b75ee38baccad089e9f7239586771cd
```

Candidate for branch 131:

```text
b759bd36b0225092d880cc1385e525b2b3bbcfb71054eecbe371f7b9689a51b5
```

Both have:

```text
before_fingerprint:
0f048a41feded5af2ceae831e57bf6c1d79d3d86ccfe991c698a5b21e3e7aca2

after_fingerprint:
d0af84caa02f93f585f9df7f3e2ef82b487348a64550e07c54f481e58e84e2f4
```

Expected interpretation:

```text
two REAL observations
+
same physical edge
=
one DETERMINISTIC navigation transition
```

---

# 11. Last known materialized Twin reference

Last reported materialized revision before the Claude transition:

```text
matrev-0bc55431f3d6040bcd93e5f7
```

Reported state:

```text
STATUS=MATERIALIZED
STATE_COUNT=9
navigation adapter=5
Twin browser=STOPPED
```

The revision already contains:

```text
EX01_AUTHORIZATION
EX01_PERSONAL
EX01_PRESENTER
```

This state must be revalidated against the repository/runtime before relying on it as current truth.

---

# 12. Current reconciliation problem

The key unresolved problem is not state discovery.

It is reconciliation of a newer physical representation of an already-existing state.

Existing logical/physical state:

```text
state_id:
AUTO_46D7EFFD1132808AA1B6B5AF

functional_state:
EX01_AUTHORIZATION
```

Old materialized fingerprint:

```text
db7cc71a0d256742fa08f68cad4232067bb017a6aea28b20ce4d2e7373819719
```

Reported source capture for the old materialization:

```text
20260909_202853_729169_7a92a017
```

Observation Store has newer evidence for the same logical state.

Fresh capture:

```text
20260912_065115_013424_32595c3f
```

Fresh functional fingerprint:

```text
0f048a41feded5af2ceae831e57bf6c1d79d3d86ccfe991c698a5b21e3e7aca2
```

Classification:

```text
CHANGED
```

The correct behavior is to refresh the physical evidence of the existing state while preserving its identity.

---

# 13. Existing-state causal refresh invariant

The desired transformation is:

```text
AUTO_46D7EFFD1132808AA1B6B5AF

old physical evidence:
db7cc...

        ↓

same logical state_id

        ↓

fresh causal evidence:
0f048...
```

without creating a new tenth state.

Must preserve:

```text
state_id
functional_state
historical revision immutability
causal authority rules
TWIN_ELIGIBLE requirements
```

A generic adoption rule for arbitrary `CHANGED` captures is not acceptable.

---

# 14. Existing implementation reference

A mechanism identified during the previous development phase is:

```text
QCC_AUTO_TWIN_EXISTING_STATE_CAUSAL_REFRES
```

---

# 15. 2D-20 CLOSURE (final, validated)

**Status: TWO_PASS_VALIDATED.** The reconciliation problem described in
§12/§13 above is resolved. This section is the authoritative final
record; §8-§14 remain as historical narrative and are not rewritten.

## 15.1 Validated physical identity

```text
EX01_AUTHORIZATION
state_id:    AUTO_46D7EFFD1132808AA1B6B5AF
fingerprint: 0f048a41feded5af2ceae831e57bf6c1d79d3d86ccfe991c698a5b21e3e7aca2

EX01_PERSONAL[TITULAR]   (state_variant_key = NO_FAMILIAR_TAB)
fingerprint: 52efb715d5688ad10cb2945d862847868ce25b4208f6ca84dcf57aa8a4032311

EX01_PERSONAL[FAMILIAR]  (state_variant_key = FAMILIAR_TAB_AVAILABLE)
fingerprint: 88c730539a17c84d7c3ac6fb753c7ba40a7489289f7d0c950d815f3aa568ae38

legacy collided EX01_PERSONAL (pre-2D-20H, pre-split)
fingerprint: d0af84caa02f93f585f9df7f3e2ef82b487348a64550e07c54f481e58e84e2f4
```

`state_variant_key` identifies a stable functional variant *within* the
`EX01_PERSONAL` screen family, derived only from the observable
capability signal (`pestFamiliar` tab visibility) -- never from raw
branch codes/context values such as `datosForAut`, `130`/`131`,
`supuestoSeleccionadoSup` or `codOpcionAutorizacion`, which remain
provenance/context only.

## 15.2 Governed mechanisms that made closure possible

```text
2D-20H/J  functional-state fingerprint & state_variant_key capability
          augmentation (backend/automation/site_recognizers/mercurio.py)
2D-20K    governed 1->N observation supersession
          (AutoTwinObservationStore.supersede(), append-safe)
2D-20O    carry-forward dedupe honors governed 1->N replacement sets
2D-20R    contextual 1->N navigation-target rebind
          (resolve_contextual_supersession_navigation_target /
          rebind_contextual_supersession_navigation_targets)
2D-20S    replacement_navigation_context_signatures corroboration
          derived from independently correlated evidence (never from
          raw branch/context literals) -- AutoTwinObservationStore.
          enrich_supersession_provenance()
2D-20U    CAUSAL_BASELINE_FALLBACK: when a state's recorded
          last_capture is evidence-incomplete and no capability-aware
          CAUSAL_EQUIVALENT exists, its own baseline_capture_id may be
          used ONLY after independent re-validation to the exact
          CURRENT fingerprint/identity (automatic_materialization.py::
          _new_state_navigation_source / _causal_baseline_fallback_
          capture / _recompute_capture_identity)
2D-20V    canonical capability-aware MATERIALIZATION fingerprint:
          persisted_capture_bundle.py delegates to the same
          apply_mercurio_functional_fingerprint_capability() used by
          observation ingestion, instead of the raw pre-2D-20H generic
          value cached on state_observation.json. The historical raw
          value remains readable at bundle["raw_fingerprint"];
          bundle["fingerprint"] is the CURRENT projected identity.
2D-20W    variant-aware catalog refresh: catalog_refresh.py::
          _current_state_metadata() resolves a (pathname,
          functional_state) family with >1 legitimate CURRENT variant
          via an exact caller-supplied state_id/fingerprint/
          state_variant_key discriminator -- never a first-match, never
          a branch/context code. A single-variant family is completely
          unaffected (byte-compatible legacy path).
```

## 15.3 CURRENT vs historical semantics

`supersede()` is append-safe: the superseded `old_state_key` remains
fully readable via the default (historical) `snapshot()`, and is
excluded only from `snapshot(current_only=True)`. Materialization only
ever consumes the CURRENT view. The legacy collided EX01_PERSONAL
fingerprint (`d0af84c...`) is permanently historically readable and is
never CURRENT again once its capability-aware replacements exist.

## 15.4 Previous-revision pinning and two-call fixed-point reconciliation

A reconciliation call may PIN an explicit `previous_revision_id`
(`AUTO_TWIN_PREVIOUS_REVISION_SELECTION_PINNED`); this fails closed
(never silently falls back to "latest") if the pin does not resolve.
`reconcile_auto_twin_discovery_materialization()` requires both
transition endpoints to already physically exist in the pinned base
revision (`QCC_AUTO_TWIN_FIXED_POINT_CLOSURE_V1`): a brand-new state
and the transition that targets it cannot both materialize in the same
call. Closing a governed 1->N split from a base that has neither
replacement yet therefore requires exactly two calls:

```text
CALL 1: previous_revision_id = <original pinned base>, PINNED
        -> materializes the new CURRENT state(s) only
CALL 2: previous_revision_id = <CALL 1's own new revision>, PINNED
        -> materializes the newly eligible transition(s)
```

## 15.5 Final validated revision chain (Mercurio)

```text
matrev-1586425db7664a40678bfa82   original authorized pinned base
        |  CALL 1 (PINNED)
        v
matrev-d1205abd0e4e762b2c3a297e   CALL 1: TITULAR + FAMILIAR CURRENT
        |                          (independently audited REUSABLE_CALL1_BASE)
        |  CALL 2 (PINNED to CALL 1's own revision)
        v
matrev-66fb6689e07f91f77093f8cf   CALL 2: AUTHORIZATION+130/131 closed,
                                   outcome_mode=CONTEXTUAL_RESOLVED,
                                   both outcomes represented -- FINAL
```

Non-conforming historical revisions -- append-only evidence, remain
on disk, are NEVER deleted/relabeled/rewritten, and must NEVER be used
as a materialization base again unless independently re-validated
against the same invariants documented here:

```text
matrev-0737ace5e5dc6fef1dbd982d
matrev-e913839c49ad1ebf87f8b505
matrev-ceafd8162d0e4eeb5f08cb62
matrev-684fc2abc9bbea4402bd0261   (superseded by matrev-d1205...
                                    once 2D-20V fixed its fingerprint-
                                    collapse defect)
```

## 15.6 Final verdict

```text
TWO_PASS_VALIDATED
```

AUTHORIZATION+130 resolves through governed contextual 1->N
supersession evidence to `EX01_PERSONAL[TITULAR]`
(`52efb715...4032311`); AUTHORIZATION+131 resolves to
`EX01_PERSONAL[FAMILIAR]` (`88c730539a...568ae38`); both as one
`CONTEXTUAL_RESOLVED` action group with both outcomes represented;
`EX01_AUTHORIZATION` identity preserved throughout; the legacy
collided fingerprint remains historical-only.
