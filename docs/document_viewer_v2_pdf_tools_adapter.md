# Viewer V2 PDF Tools toolbar adapter

`PdfToolsToolbarAdapter` implements the existing `toolbar_actions(PreviewRequest)`
extension point. It accepts a registered-item resolver, existing workflow handlers
and an error callback. It contains no PDF transformations or persistence logic.

The inbox list, detail and batch viewers expose the existing rotate, move-page,
split and compress workflows. Their existing dialogs own parameters, validation,
result registration and feedback. Missing handlers (including extract/merge in
this UI and unsupported annotation) remain disabled. Other callers can provide
supported workflows using the same adapter contract.

Paths must match the registered item; identity is checked again on click. Viewer
generation guards prevent callbacks from acting after navigation, closure or
dialog replacement. Queue callers can resolve each current request independently.

Existing PDF services generate separate files using exclusive creation. Smart
compression also copies and verifies its chosen candidate before releasing that
temporary candidate. Source files are preserved. Inbox persistence uses
COPY → VERIFY (size and SHA-256) → REGISTER, refusing collisions or mismatched
copies before insertion. Existing document-tools source IDs, paths and operation
metadata remain attached to generated items. Failed copies may remain unregistered
on disk for inspection; the source is never removed.

Validation: `python -m unittest discover -s scripts/tests -p 'test_document_viewer*.py'`.

Recovery audit:
- Base: `5cfcd19e031177d4b390981e487beb263a169c60`.
- Candidate: `77be159aea1023e64b3a8158709013946c2a3b7e`, inspected read-only
  and recovered by reading individual blobs; no stash apply/pop or commit.
- Scope: exactly the seven authorized paths. No viewer, cache, cancellation
  or PDF transformation reimplementation. Each production change supports
  workflow delegation, stale-command rejection or safe derived-file persistence.
- Validation: 47 tests pass (foundation 24, cache 7, cancellation 4, toolbar 12).
  Includes queue/dialog replacement, original-file collisions, traceability,
  corrupt-copy rejection and registration ordering. Existing Flet deprecation
  warnings remain. Native GUI interaction was not manually exercised.
- VERDICT=PASS
