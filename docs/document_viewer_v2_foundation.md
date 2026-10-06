# Document Viewer V2: consolidation foundation

## Inventory and evidence

Before this slice there were **two embedded document/PDF viewer implementations**, eight external caller sites, and **three backend PDF rasterization implementations**. Both viewers used the same `document_viewer_service.create_document_preview` engine; there were not two independent interactive PDF engines.

| Implementation before migration | Actual callers | Disposition |
| --- | --- | --- |
| `frontend/components/document_viewer_modal.py:open_document_viewer_modal` | Documental: `show_preview`, `open_document_detail_dialog/detail_show_preview`, `show_batch_item_preview` (3 sites) | Canonical component |
| `frontend/views/expedients_view.py:show_document_preview` | `build_diagnostic_content/open_selected_diagnostic_documents`, `build_documentacion_content/open_selected_documents`, its individual document action, `show_expediente_documents_dialog`, `build_expediente_documents_inline` (5 sites) | All five now delegate through the existing adapter to the canonical component |
| `backend/services/document_viewer_service.py:create_document_preview` | Previously both viewer bodies; now the canonical session | Existing interactive PDF renderer; image previews return the image path |
| `backend/services/document_intelligence/document_image_renderer.py:PdfPageRenderer` | `document_ocr_service` calls `render_pages`; `document_intelligence_service` constructs/injects it; package re-exports it | OCR page images, not an interactive viewer; retained |
| `backend/services/document_tools/pdf_tools_service.py:compress_pdf_rasterized` | `document_inbox_tools_service.compress_inbox_pdf_strong`, `compress_pdf_smart` | PDF transformation renderer, not an interactive viewer; retained |

The existing system-viewer launcher is `document_viewer_service.open_document`. Its direct frontend callers are the canonical modal, Expedientes' `open_document_with_system`, Client Detail, and Documental's detail and batch handlers (the batch handler has a fallback invocation). This launches an external application; it is not another embedded viewer.

`document_file_card` is a command/display card, not a page renderer. Documental's `preview_dialog` and `viewer_overlay` variables have no rendering implementation: previews already call the reusable component. Login images are branding. Mapper/payload/extraction previews are data/form displays, not document page viewers. PDF template/fill services generate documents rather than display pages.

Evidence was collected using `rg --no-ignore` across frontend/backend/app, searches for `create_document_preview`, `open_document_viewer_modal`, `show_document_preview`, `ft.Image`, `get_pixmap`, `convert_from_path`, `PdfPageRenderer`, `pdfium`, `pdfjs`, and AST call-site enumeration. `--no-ignore` matters because normal repository ignore rules hide relevant files. The regression suite asserts all five Expedientes sites and all three Documental sites. There were no dedicated viewer or PDF Tools tests before this slice; related OCR/extraction tests existed.

## Canonical choice and migration

Expedientes had more external sites (5 versus 3), but its engine duplicated the existing reusable component inside a large view closure. Both used the same backend and rendering strategy, with no dedicated test advantage. The reusable component wins on layering, migration cost and future lifecycle ownership. It now serves all eight caller paths.

The `show_document_preview` adapter preserves expediente resolution, missing-expediente errors, initial page/zoom, queue and index, the existing overlay and caller error reporting. Its duplicated rendering body was removed only after every caller was accounted for and redirected. The document-list dialog remains. No live viewer was abandoned. No Box, Knowledge, QCC, database or broad Documental changes were made.

The public `open_document_viewer_modal` positional contract remains compatible. Optional keyword-only arguments permit a caller-owned `dialog`, `on_error`, and `toolbar_actions`. It returns the dialog for lifecycle management and testing.

## Current performance and next architecture

Rendering is still synchronous PyMuPDF rasterization to PNG, displayed with Flet Image inside horizontal Rows in a vertical ListView. Opening page 1 renders pages 1–4; scrolling within 250 pixels of the end requests three more. Opening page N renders the prefix through N+3, capped at the document length. Navigation/zoom rebuild that prefix. Each page request reopens the PDF, rasterizes it and writes a PNG, even when that path already exists. This is **not a cache hit**.

The concrete bottleneck is synchronous rasterization/PNG I/O in interaction handlers, combined with an ever-growing image/control list. Zoom magnifies raster cost. There is no window eviction, background prefetch, persistent cache validation or interruption of an executing native render. No interactive frame-time benchmark was taken.

This slice introduces backend `DocumentPreviewSession` and immutable `PreviewRequest` as the single page-request seam. Generation invalidation prevents obsolete requests starting and discards obsolete results after rendering. Close, queue/page/zoom changes and reuse invalidate earlier requests. Old scroll callbacks cannot append pages; earlier list references are cleared rather than retained for every document/zoom. The service closes PDF handles on failure as well as success. System opening now delegates to backend validation instead of calling `os.startfile` in Flet.

This is a synchronous lifecycle foundation, not a thread-safe asynchronous scheduler. The next slice should put a bounded scheduler/cache behind this seam, key entries by source identity/version + page + scale, add atomic cache publication and eviction, maintain a viewport window with placeholders, and prefetch neighboring pages. Coordinate generation checks and UI publication when introducing worker threads. Native-render interruption needs explicit engine support; current cancellation only suppresses obsolete work/results at request boundaries. Existing controls and caller APIs can be retained.

Flet 0.84.0 was installed; requirements currently leave Flet unpinned. The existing ListView/on_scroll/overlay APIs were exercised by construction and event tests. Existing deprecated padding/border/button helpers still execute and emit warnings. No speculative Flet APIs were introduced. Desktop visual/scroll validation remains for the next interactive acceptance run.

## PDF Tools and mutation safety

`toolbar_actions(PreviewRequest)` is the canonical command integration point and receives the currently displayed document/page/zoom, including after queue navigation. No PDF operations were moved into Flet and no new transformation engine was added. Full toolbar wiring is deferred.

Reuse `backend/services/document_tools/pdf_tools_service.py` for merge, extract, remove, reorder, split, rotate, move and compression. Documental's existing `document_inbox_tools_service` wrappers retain inbox registration and application behavior. `safe_file_service.build_output_path` provides sanitized, timestamp/UUID-suffixed output paths under `storage/document_tools`; callers should continue using these services instead of writing original documents.

Viewing only writes derived PNG previews. Tests compare source bytes before/after viewing and invoke the actual existing rotation service: its separate eight-page output has the requested rotations and the source remains byte-identical. This verifies the exercised operations, not a new exhaustive audit of every historical PDF Tools operation.

## Previous candidate validation (historical, not recovery evidence)

- `python -m unittest discover -s scripts/tests -p 'test_document*.py'`: 200 passed at that run, including the initial 11 foundation tests.
- `python -m unittest scripts.tests.test_payroll_file_extraction scripts.tests.test_payroll_document_extraction scripts.tests.test_payroll_document_intelligence_integration scripts.tests.test_client_authorization_origin_actions scripts.tests.test_dehu_receipt_extraction scripts.tests.test_justificante_presentacion_extraction scripts.tests.test_justificante_aportacion_tasa_extraction scripts.tests.test_justificante_aportacion_documentacion_extraction scripts.tests.test_justificante_ampliacion_plazo_extraction`: 54 passed.
- After final lifecycle guards and four additional foundation cases: `python -m unittest scripts.tests.test_document_viewer_foundation scripts.tests.test_admision_tramite_extraction scripts.tests.test_requerimiento_extraction scripts.tests.test_resolucion_favorable_extraction scripts.tests.test_resolucion_denegacion_extraction -q`: 28 passed.

Total: **271 distinct tests passed**, including all 15 final foundation tests. The latter cover real PDF rendering, construction/open, multipage scroll, single-page display, page clamping/navigation, zoom, queues, toolbar context, stale callbacks/results, overlay reuse/close, images/unsupported documents, missing/corrupt files, scope validation, system opening, handle cleanup, actual adapter invocation, caller counts and non-destructive PDF output. UI tests use real Flet controls with a fake Page; they do not simulate a desktop Flutter client. `git diff --check` also passed.

## Governed recovery audit (2026-10-06)

Restored stash `775eae9650faa0cd5468c14332c596b4b0a10a4a` using the binary patch after `git apply --check`; the stash was not popped or dropped. Only the six authorized paths are changed. Inventory was independently repeated across ignored and tracked Python sources: two embedded viewers before consolidation, one afterward, five Expedientes caller sites migrated, three existing Documental sites retained. OCR rasterization and PDF compression are not interactive viewers.

The session is retained as a small reusable application abstraction: it owns generation validity and loaded-page extent, delegates all rendering and scope validation to the existing viewer service, and has no Flet dependency or duplicate PDF engine. The viewer service remains the document listing, validated system-open and preview-rendering service. The modal remains the canonical presentation and navigation component. No SQL or PDF mutation logic was added to Flet.

Recovery corrected two candidate defects: clearing loaded-page extent on every navigation truncated the previously loaded prefix; extent now lives in the backend session and is preserved across navigation in that session. Old navigation/close buttons could affect a reused dialog or reopen a closed viewer; callbacks now reject closed or replaced sessions. Explicitly starting a new viewer session resets its progressive extent; this is session-local state, not a persistent cache. No caller API regression was found in the tested open, queue, navigation, error and system-open contracts.

Current recovery command:

`python -B -m unittest scripts.tests.test_document_viewer_foundation scripts.tests.test_document_ocr_service scripts.tests.test_document_ocr_persistence scripts.tests.test_document_text_contract -q`

**39 tests passed**, including **17 foundation tests**. The original restored 15 foundation tests also passed before recovery edits. Tests exercise actual PyMuPDF rendering and PDF Tools rotation, source-byte preservation, real Flet controls and callbacks, and execution of the extracted Expedientes adapter. They do not run the full Expedientes screen or a desktop Flutter client. Existing Flet deprecation warnings remain. `git diff --check` passed.

The PDF Tools registration wrapper was also inspected: generated-result metadata retains operation, source item IDs, source paths and tool result before inbox import. This foundation does not bypass or replace that lineage path. No full PDF Tools toolbar integration is claimed.

Performance is unchanged in kind: synchronous PNG rasterization, prefix rendering through the requested page plus three, then batches of three appended near the scroll end. Each request reopens and renders the PDF; generated PNG paths are not a validated cache. Synchronous rendering/I/O plus growing image controls remain the primary bottleneck. The next slice should implement bounded page scheduling/windowing, versioned cache, neighboring-page prefetch, eviction and coordinated obsolete-result cancellation behind the same service seam. Native in-flight rendering is not interrupted today.


## Windowed lazy rendering (2026-10-06)

This slice supersedes the historical prefix-rendering behavior above. The canonical
modal accepts an optional keyword-only `near_window` (default 3). The session owns
`current_request`, `requested_window` and `loaded_window`. A request for page N
renders only N and its clamped neighborhood, at most `2 * near_window + 1` pages;
it never renders the preceding prefix. Overlapping successful neighbor previews
are reused within the same source version, scope and zoom. Moving outside the
window evicts those entries. Failed neighbors remain requested but are not marked
loaded and are retried on the next request. The current page still goes through
the existing validated rendering service on each transition.

Presentation uses fixed-height page slots and two aggregate blank spacers, so
control count is bounded and scroll offsets remain independent of the loaded
window. Forward/back scrolling, page buttons, zoom and queue changes all use the
same session seam. Initial navigation restores the requested page's scroll offset;
obsolete scroll callbacks and scheduled restoration tasks are generation guarded.
No second viewer or PDF engine was introduced. Existing positional callers and
single-page service/error contracts remain intact; original files are not changed.
The older extent methods remain available for compatibility but the canonical
viewer no longer uses prefix extents.

Rendering remains synchronous. Active preview references and page controls are
bounded; derived PNG files in the existing preview directory are not a disk cache
with eviction. Fixed slots may leave whitespace around nonstandard page sizes.
Desktop Flutter scroll/layout validation remains outstanding; automated tests use
real Flet controls, simulated scroll events and the real PyMuPDF service.

Validation: `python -B -m unittest scripts.tests.test_document_viewer_foundation scripts.tests.test_document_ocr_service scripts.tests.test_document_ocr_persistence scripts.tests.test_document_text_contract -q` passed **46 tests**, including 24 viewer tests. Coverage includes deep-page opening, a simulated 1,000-page window progression, forward/back scrolling, bounded page/control counts, source-version invalidation, scroll restoration, missing/corrupt documents, failed-neighbor retry, caller compatibility and unchanged original bytes. `git diff --check` passed. Existing Flet deprecation warnings remain.

## Bounded rendered-page cache (2026-10-06)

The existing viewer service now owns a dedicated `data/document_previews/v2`
cache, limited to 64 PNG pages and 128 MiB. Both limits apply across documents,
zooms and sessions. On each PDF request, deterministic LRU eviction uses last
access timestamps with filename tie-breaking; hits refresh recency. Entries
survive process restarts without an unbounded in-memory index. Legacy preview
files outside this namespace are untouched and no longer generated.

SHA-256 keys include resolved source path, source content digest, expediente
scope, clamped page, exact normalized zoom, renderer version and RGB/alpha/output
parameters. The renderer reads an immutable source snapshot and renders those
same bytes. Access validation runs before cache lookup. Cache hits avoid
rasterization and PNG writes, though source reading/hashing and PDF opening still
occur. Publication uses a temporary file and atomic replacement; failures clean
up the temporary file. A process-local lock serializes cache operations. This
remains the existing synchronous, single-process viewer; multi-process cache
coordination is not provided.

The canonical session's existing bounded neighborhood supplies adjacent-page
prefetch (default three on either side). No worker or second rendering engine
is introduced. Session overlap checks content identity, including changes with
unchanged size/timestamp, and regenerates evicted files. Existing generation
checks reject obsolete requests/results. An individual PNG larger than the byte
budget produces the normal preview failure rather than violating the bound.
Source PDFs are never written by the preview path.

Validation: 53 tests passed using `python -B -m unittest
scripts.tests.test_document_viewer_cache scripts.tests.test_document_viewer_foundation
scripts.tests.test_document_ocr_service scripts.tests.test_document_ocr_persistence
scripts.tests.test_document_text_contract -q`. New tests exercise cache hits,
exact zoom keys, clamped-page reuse, deterministic LRU, page/byte budgets,
oversized entries, adjacent prefetch, document/session isolation, source-content
invalidation, evicted overlap recovery, atomic-publication failure cleanup and
unchanged source bytes. Desktop Flutter validation was not run; existing Flet
deprecation warnings remain.
