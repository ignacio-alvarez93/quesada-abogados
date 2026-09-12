# Quesada Abogados — Project Constitution

## Purpose

This document is the compact constitutional layer for AI-assisted development of Quesada Abogados.

It does not replace the approved resolutions.

The resolutions remain the normative authority.

This document exists so an execution agent can understand the permanent rules of the project before modifying code.

---

## 1. Authority

Decision hierarchy:

```text
Quesada Abogados Project Direction
        ↓
Approved resolutions
        ↓
Explicit Work Order
        ↓
Existing architectural contracts
        ↓
Existing tested implementation
        ↓
Implementation discretion
```

Claude Code executes.

It does not independently redefine project architecture.

---

## 2. Permanent development doctrine

The project follows:

```text
THINK
→ DESIGN
→ SPECIFY
→ EXECUTE
→ PROVE
→ REVIEW
→ CONSOLIDATE
```

Roles:

```text
Quesada Abogados
= project authority and objectives

ChatGPT
= technical and architectural direction

Claude Code
= repository execution and evidence

Git
= code history and technical source of truth

Tests
= executable contracts

Resolutions
= normative authority
```

---

## 3. Preserve previous decisions

The transition to Claude Code changes the execution layer only.

It does not reset:

* architecture;
* methodology;
* contracts;
* domain authority;
* branch governance;
* automation policies;
* QCC architecture;
* AUTO TWIN architecture;
* SeleniumBase governance;
* testing requirements.

All previous approved resolutions remain valid unless explicitly superseded.

---

## 4. Repository-first rule

Always inspect the real repository before changing significant code.

Do not work from reconstructed assumptions when the implementation can be read directly.

Preferred sequence:

```text
Inspect
→ Understand
→ Modify narrowly
→ Validate
→ Test
→ Review
```

---

## 5. Protect existing work

Uncommitted work is valuable project state.

Never discard or overwrite it casually.

Do not use destructive Git operations without explicit authorization.

Particularly prohibited by default:

```text
git reset --hard
git clean
bulk git restore
mass deletion
mass formatting
```

Never use `git add .` unless specifically authorized.

---

## 6. Git model

Official branches:

```text
main
develop
feature/*
hotfix/*
```

Rules:

* `main` is stable;
* `develop` is integration;
* normal work occurs in `feature/*`;
* no autonomous merge to `develop`;
* no autonomous merge to `main`;
* commits should be atomic and reversible.

---

## 7. Incremental development

Prefer small, diagnosable changes.

Do not rewrite mature modules merely because a cleaner design is possible.

A refactor requires a concrete reason and preserved behavior.

Existing working code has value.

---

## 8. Tests and evidence

No important change is considered finished without evidence.

Depending on scope, evidence may include:

* pytest;
* contract tests;
* regression tests;
* integration tests;
* E2E tests;
* `py_compile`;
* `git diff --check`;
* controlled smoke validation;
* runtime evidence;
* revision IDs;
* fingerprints.

A green description is not equivalent to a green test suite.

---

## 9. Frontend / backend boundary

The required direction is:

```text
Frontend
→ Application / Services
→ Domain
→ Persistence
```

Do not introduce new SQL into Flet.

Do not evolve database schema from frontend.

Do not duplicate backend business logic in UI.

---

## 10. Persistence principles

Avoid new direct coupling to SQLite.

Schema evolution must move toward governed migrations.

Business services must not become responsible for uncontrolled runtime schema mutation.

PostgreSQL migration must preserve domain behavior rather than reproduce SQLite implementation details.

---

## 11. Single source of truth

Do not create parallel authorities.

Core examples:

```text
Expedient / Traceability
= legal-administrative authority

TASK
= canonical work unit

Calendar
= temporal projection

CAA
= administrative operations center

notification_tracking
= administrative waiting projection

scheduled_notifications
= notification delivery outbox

Reporting
= analytical projection

Knowledge
= information consumer

QCC
= contextual runtime/browser projection

AUTO TWIN
= governed representation of observed websites
```

---

## 12. Browser automation

Browser automation is shared infrastructure.

Preferred architecture:

```text
Use Case
→ Runtime
→ Connector
→ Browser Infrastructure
→ SeleniumBase / CDP
→ Chrome
```

Do not spread SeleniumBase implementation details across unrelated domains.

Do not put SeleniumBase inside Flet views.

---

## 13. Browser ownership

Every browser session requires explicit ownership.

The system must know:

* who creates it;
* which runtime owns it;
* which profile it uses;
* who may execute actions;
* who may close it;
* how its lifecycle ends.

Persistent browser operations should be serialized where required.

---

## 14. QCC doctrine

Quesada Chrome Companion is the contextual interface of the ERP inside Chrome.

QCC:

* observes;
* projects runtime state;
* supports governed interaction;
* communicates through backend contracts.

QCC is not:

* a second CRM;
* a database;
* the legal authority;
* an independent automation engine.

---

## 15. QCC Bridge

QCC Bridge is infrastructure.

It must remain primarily:

```text
transport
+
state exposure
+
runtime communication
```

It must not silently become business or legal authority.

---

## 16. LABS doctrine

For governed sites:

```text
REAL
→ observation
→ site contract
→ LAB / TWIN
→ automation
→ tests
→ REAL
```

LABS exist to reproduce observable behavior required by the ERP.

They must not be replaced by trivial mocks when real navigable behavior is part of the contract.

---

## 17. AUTO TWIN doctrine

AUTO TWIN is a QCC capability for building, maintaining and validating governed local replicas of websites.

Its contract may include:

* functional identity;
* DOM structure;
* CSS;
* assets;
* geometry;
* visual fidelity;
* states;
* navigation;
* catalogs;
* catalog dependencies;
* interaction;
* revisions;
* fingerprints;
* evidence;
* REAL ↔ TWIN comparison;
* continuous discovery.

AUTO TWIN is not merely HTML generation.

---

## 18. Twin runtime

The operational Twin runs in a governed SeleniumBase browser.

Do not use the user's ordinary Chrome as the Twin preproduction runtime.

Where the repository already has runtime services or launch scripts, use them instead of asking the user to manually start infrastructure.

---

## 19. Discovery

REAL assisted browsers observe.

TWIN DISCOVERY may observe and, when policy allows, safely explore.

Do not convert production/REAL browsing into uncontrolled active exploration.

---

## 20. Interaction governance

Interaction policies remain authoritative:

```text
AUTOMATION_ALLOWED
OBSERVATION_ONLY
HUMAN_ONLY
```

A technically possible action is not automatically authorized.

Actions classified HUMAN_ONLY remain human.

---

## 21. Manual actions

If manual validation is necessary, provide exact steps before asking the user to act.

Specify:

* runtime/browser;
* state;
* action;
* expected result;
* evidence to capture.

Technical startup should be automated by repository tooling whenever reasonably possible.

---

## 22. Security

Never commit or expose:

* passwords;
* API keys;
* OAuth secrets;
* private certificates;
* tokens;
* authentication cookies;
* production secrets.

Prefer synthetic and sanitized test data.

---

## 23. Real client data

Tests should use:

* fictitious clients;
* fixtures;
* temporary databases;
* temporary directories;
* sanitized evidence.

Real client information must not become routine test material.

---

## 24. Existing capability first

Before creating a new abstraction, search for an existing one.

This applies to:

* services;
* components;
* helpers;
* mappers;
* runtimes;
* tables;
* stores;
* contracts;
* test utilities.

Do not duplicate functionality unnecessarily.

---

## 25. Out-of-scope findings

When discovering technical debt outside the assigned task:

```text
identify
→ document
→ assess risk
→ leave unchanged
```

unless it blocks the authorized objective.

Do not enlarge Work Orders silently.

---

## 26. Contradictions

If the requested change contradicts:

* an approved resolution;
* an established contract;
* repository reality;
* test evidence;

do not silently choose a new architecture.

Return the contradiction and evidence for review.

---

## 27. Definition of completion

A Work Order is complete only when its principal acceptance criteria have been demonstrated.

Allowed final states:

```text
COMPLETED
PARTIALLY COMPLETED
BLOCKED BY FINDING
REQUIRES HUMAN VALIDATION
```

---

## 28. Default integration policy

Default:

```text
NO MERGE
```

Execution and integration are separate decisions.

The normal path is:

```text
Work Order
→ Execution
→ Evidence
→ Architectural Review
→ Approval
→ Integration
```

---

## 29. Governing references

The primary resolution for the Claude execution model is:

`docs/resolutions/20260912_resolucion_modelo_direccion_tecnica_y_ejecucion_claude.md`

Other project resolutions remain authoritative for their respective domains.

---

## 30. Final principle

The purpose of AI-assisted development in Quesada Abogados is:

```text
more execution capacity
without losing control,

more speed
without losing architecture,

more automation
without losing human governance,

more complexity
without losing traceability.
```
