"""FCP-11H-08: Fabric Control Plane operator view (Flet, section «Sistema») -
read-only, user-refreshed, fail-closed, OBSERVATION-ONLY.

Two layers in one module:

* A pure MODEL layer (`control_plane_sources`, `observe`, `build_model`,
  `error_model`) with no Flet import. It asks the FCP-11G-07 gateway
  (`scripts.ai.fabric_control_plane_gateway.query`) for `summary`,
  `pipelines` and `attention`, and copies an explicit field allowlist of
  those already-sanitized answers into a plain dict. It opens no file, runs
  no SQL, has no clock and never re-decides a status: values are the
  gateway's; anything absent or malformed becomes UNKNOWN, never SUCCESS.
* A Flet RENDERER (`fabric_control_plane_view`) that imports Flet lazily and
  reuses the existing frontend components (`app_alert`, `app_empty_state`,
  `app_button`). It reads ONLY when the user opens the view or presses
  «Actualizar»: no polling, timer, background task or watcher.

Model (`build_model` / `error_model` dict)
-----------------------------------------
`state` (READY / EMPTY / ERROR), `observed_at_utc`, `root` (`condition`,
`cause`, `actor`), `headline` (`attention_class`, `actor`, `origin`),
`counts` (pipelines / workers shown and omitted), `class_counts`,
`pipelines` (per pipeline: id, condition, lifecycle, outcome, agreement,
attention class, primary reason and `workers` with the same fields),
`pipelines_more` / `attention_more` (the gateway page has a next page),
`attention` (non-CLEAR items: subject, class, actor, origin, primary
reason), `consistent` (the three answers observed the same snapshot
revision), `actions` (governed actions, every one NOT AUTHORIZED here),
`authority` (fixed text) and `error` (`code`, `message`: the gateway's fixed
text, never a path, id or OS message).

Decisions
---------
* Director and Runner keep ALL execution, recovery, authorization, Git,
  process and resource authority. Pause / cancel / resume / retry are shown
  as «No autorizada» without any handler: no governed gateway for them has
  been approved by Dirección, so none is implemented by inference.
* Sources are explicit: `control_plane_sources(project_root)` only joins the
  Runner's own default layout (`runtime/claude_runner/pipelines` under the
  allowed root `runtime/claude_runner`); the gateway admits or refuses them.
  Paths are never shown in the UI.
* Fail closed: a gateway refusal, an unexpected exception, a foreign schema
  or any zero-authority flag set to True yields the ERROR state.
* The observation instant is taken once per user action by the injected
  `now_utc` callable and passed to the gateway (which has no clock).

Limitations
-----------
Each refresh costs three gateway reads of the state root (snapshot +
evidence + attention each), bounded by the gateway's own limits (32
pipelines, 32 workers per pipeline, MAX_RESPONSE_BYTES). Activity
(ledger) and resources stay available through the FCP-11 CLI only.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

VIEW_TITLE = "Control operativo Fabric"

QUERIES = ("summary", "pipelines", "attention")
PAGE_LIMIT = 50
MAX_TEXT = 80

STATE_READY = "READY"
STATE_EMPTY = "EMPTY"
STATE_ERROR = "ERROR"

UNKNOWN = "UNKNOWN"
CLEAR = "CLEAR"
PRESENT = "PRESENT"

ACTION_NOT_AUTHORIZED = "NO_AUTORIZADA"
GOVERNED_ACTIONS = (
    ("pause", "Pausar"),
    ("cancel", "Cancelar"),
    ("resume", "Reanudar"),
    ("retry", "Reintentar"),
)
AUTHORITY_TEXT = ("Solo observación: no certifica ni autoriza. Director y Runner son las únicas "
                  "autoridades de ejecución.")

VIEW_RESPONSE_INVALID = "VIEW_RESPONSE_INVALID"
VIEW_AUTHORITY_FLAG = "VIEW_AUTHORITY_FLAG"
VIEW_INTERNAL_ERROR = "GATEWAY_INTERNAL_ERROR"
_VIEW_MESSAGES = {
    VIEW_RESPONSE_INVALID: "the gateway answer does not match the expected schema",
    VIEW_AUTHORITY_FLAG: "the gateway answer claims an authority the view refuses",
    VIEW_INTERNAL_ERROR: "the response could not be produced",
}
_FRIENDLY = {
    "GATEWAY_ROOTS_INVALID": "Las fuentes del Runner no están disponibles en este equipo.",
    "GATEWAY_PATH_NOT_ADMISSIBLE": "La ruta configurada del Runner no es admisible.",
    "GATEWAY_PATH_OUTSIDE_ROOTS": "La ruta configurada del Runner está fuera de las raíces permitidas.",
    "GATEWAY_RESPONSE_TOO_LARGE": "La respuesta excede el límite de tamaño.",
}
_DEFAULT_FRIENDLY = "No se pudo observar el plano de control."


@dataclass(frozen=True)
class ControlPlaneSources:
    """Explicit gateway sources: allowed roots and the Runner state root."""
    allowed_roots: tuple
    state_root: str


def control_plane_sources(project_root) -> ControlPlaneSources:
    """The Runner's default layout under `project_root` (path joins only)."""
    runtime = project_root / "runtime" / "claude_runner"
    return ControlPlaneSources((str(runtime),), str(runtime / "pipelines"))


def utc_text(instant: datetime) -> str:
    return instant.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Model (no Flet)
# ---------------------------------------------------------------------------

def _text(value) -> str:
    if type(value) is str and value:
        return value[:MAX_TEXT]
    if type(value) is int:
        return str(value)
    return UNKNOWN


def _count(value) -> int:
    return value if type(value) is int and value >= 0 else 0


def _dict(value) -> dict:
    return value if type(value) is dict else {}


def _list(value) -> list:
    return value if type(value) is list else []


def _actions() -> list:
    return [{"action": a, "label": label, "availability": ACTION_NOT_AUTHORIZED} for a, label in GOVERNED_ACTIONS]


def error_model(code, message, observed_at_utc=None) -> dict:
    """ERROR state: only a fixed code and fixed text, never a value."""
    code = code if type(code) is str and code.isupper() and len(code) <= MAX_TEXT else VIEW_INTERNAL_ERROR
    return {
        "state": STATE_ERROR, "observed_at_utc": observed_at_utc, "root": None, "headline": None,
        "counts": None, "class_counts": {}, "pipelines": [], "pipelines_more": False, "attention": [],
        "attention_more": False, "consistent": False, "actions": _actions(), "authority": AUTHORITY_TEXT,
        "error": {"code": code, "message": _text(message) if type(message) is str else UNKNOWN,
                  "friendly": _FRIENDLY.get(code, _DEFAULT_FRIENDLY)},
    }


def _status(row: dict, key: str) -> dict:
    status = _dict(row.get(key))
    return {"condition": _text(status.get("condition")), "lifecycle": _text(status.get("lifecycle")),
            "outcome": _text(status.get("runner_outcome"))}


def _worker(row) -> dict:
    row = _dict(row)
    record = _status(row, "record_status")
    return {"worker_id": _text(row.get("worker_id")), **record,
            "result_outcome": _status(row, "result_status")["outcome"],
            "agreement": _text(row.get("agreement")), "attention_class": _text(row.get("attention_class")),
            "primary_reason": _text(row.get("primary_reason"))}


def _pipeline(row) -> dict:
    row = _dict(row)
    return {"pipeline_id": _text(row.get("pipeline_id")), **_status(row, "status"),
            "agreement": _text(row.get("agreement")), "attention_class": _text(row.get("attention_class")),
            "primary_reason": _text(row.get("primary_reason")),
            "workers": [_worker(w) for w in _list(row.get("workers"))]}


def _attention_item(item) -> dict:
    item = _dict(item)
    worker_id = item.get("worker_id")
    return {"pipeline_id": _text(item.get("pipeline_id")), "worker_id": None if worker_id is None else _text(worker_id),
            "attention_class": _text(item.get("attention_class")), "actor": _text(item.get("actor")),
            "origin": _text(item.get("origin")), "primary_reason": _text(item.get("primary_reason"))}


def _more(response: dict) -> bool:
    return _dict(response.get("page")).get("next_offset") is not None


def _check_response(response, name: str, schema) -> None:
    if type(response) is not dict or response.get("schema") != schema or response.get("query") != name:
        raise _ViewRefusal(VIEW_RESPONSE_INVALID)
    if any(value is True for value in response.values()):
        raise _ViewRefusal(VIEW_AUTHORITY_FLAG)


class _ViewRefusal(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def build_model(summary: dict, pipelines: dict, attention: dict, schema: str) -> dict:
    """READY / EMPTY model from three gateway answers (allowlist copy)."""
    try:
        for name, response in zip(QUERIES, (summary, pipelines, attention)):
            _check_response(response, name, schema)
    except _ViewRefusal as exc:
        return error_model(exc.code, _VIEW_MESSAGES[exc.code])
    head = _dict(summary.get("result"))
    rows = [_pipeline(p) for p in _list(_dict(pipelines.get("result")).get("pipelines"))]
    items = [_attention_item(i) for i in _list(_dict(attention.get("result")).get("items"))]
    revisions = {_dict(r.get("sources")).get("snapshot") for r in (summary, pipelines, attention)}
    root = {"condition": _text(head.get("root_condition")), "cause": _text(head.get("root_cause")),
            "actor": _text(head.get("root_actor"))}
    class_counts = {_text(k): _count(v) for k, v in sorted(_dict(head.get("class_counts")).items())}
    return {
        "state": STATE_READY if root["condition"] == PRESENT and rows else STATE_EMPTY,
        "observed_at_utc": _text(summary.get("observed_at_utc")), "root": root,
        "headline": {"attention_class": _text(head.get("attention_class")), "actor": _text(head.get("actor")),
                     "origin": _text(head.get("origin"))},
        "counts": {k: _count(head.get(k)) for k in ("pipelines_shown", "pipelines_omitted", "workers_shown",
                                                      "workers_omitted")},
        "class_counts": class_counts, "pipelines": rows, "pipelines_more": _more(pipelines),
        "attention": [i for i in items if i["attention_class"] != CLEAR], "attention_more": _more(attention),
        "consistent": len(revisions) == 1 and None not in revisions,
        "actions": _actions(), "authority": AUTHORITY_TEXT, "error": None,
    }


def _gateway():
    from scripts.ai import fabric_control_plane_gateway as gw
    return gw


def observe(sources: ControlPlaneSources, observed_at_utc: str, gateway=None) -> dict:
    """Ask the gateway once per query; any refusal becomes the ERROR state."""
    try:
        gw = gateway if gateway is not None else _gateway()
    except Exception:  # noqa: BLE001 - fail closed without a traceback
        return error_model(VIEW_INTERNAL_ERROR, _VIEW_MESSAGES[VIEW_INTERNAL_ERROR], observed_at_utc)
    if type(sources) is not ControlPlaneSources:
        return error_model("GATEWAY_USAGE_INVALID", "the request is invalid", observed_at_utc)
    responses = []
    for name in QUERIES:
        try:
            request = gw.GatewayRequest(name, tuple(sources.allowed_roots), sources.state_root, observed_at_utc,
                                        limit=PAGE_LIMIT)
            responses.append(gw.query(request))
        except gw.GatewayError as exc:
            return error_model(exc.code, exc.message, observed_at_utc)
        except Exception:  # noqa: BLE001 - fail closed without a traceback
            return error_model(VIEW_INTERNAL_ERROR, _VIEW_MESSAGES[VIEW_INTERNAL_ERROR], observed_at_utc)
    return build_model(*responses, schema=gw.SCHEMA)


# ---------------------------------------------------------------------------
# Flet renderer
# ---------------------------------------------------------------------------

Q_PRIMARY_DARK = "#003B7A"
Q_BORDER = "#E4E7EC"
Q_MUTED = "#64748B"
_CLASS_COLORS = {"SAFETY": "#B42318", "PROCESS": "#B42318", "EVIDENCE": "#B54708", "FAILURE": "#B42318",
                 "AUTH": "#B54708", "QUOTA": "#B54708", "WAITING": "#0057B8", CLEAR: "#027A48"}


def _subject(item: dict) -> str:
    return item["pipeline_id"] if item["worker_id"] is None else f"{item['pipeline_id']} / {item['worker_id']}"


def render_controls(ft, model: dict, components: dict) -> list:
    """Flet controls for a model; `components` are the reused frontend
    builders (`error_alert`, `warning_alert`, `empty_state`)."""
    def text(value, size=13, color=None, bold=False):
        return ft.Text(value, size=size, color=color, weight=ft.FontWeight.BOLD if bold else None)

    def card(title, controls):
        return ft.Container(
            content=ft.Column(controls=[text(title, 15, Q_PRIMARY_DARK, True), *controls], spacing=6),
            padding=14, border_radius=12, bgcolor="#FFFFFF", border=ft.border.all(1, Q_BORDER),
        )

    controls = [text(model["authority"], 12, Q_MUTED)]
    if model["state"] == STATE_ERROR:
        error = model["error"]
        controls.append(components["error_alert"](f"{error['friendly']} ({error['code']}: {error['message']})"))
    elif model["state"] == STATE_EMPTY:
        root = model["root"]
        controls.append(components["empty_state"](
            f"Sin pipelines observados (estado del Runner: {root['condition']} {root['cause']})"))
    if model["state"] != STATE_ERROR:
        if not model["consistent"]:
            controls.append(components["warning_alert"](
                "Las fuentes cambiaron entre lecturas: vuelve a pulsar Actualizar."))
        head, counts = model["headline"], model["counts"]
        controls.append(card("Resumen", [
            text(f"Observado (UTC): {model['observed_at_utc']}"),
            text(f"Atención: {head['attention_class']} · actor {head['actor']} · origen {head['origin']}",
                 color=_CLASS_COLORS.get(head["attention_class"], Q_MUTED), bold=True),
            text(f"Pipelines: {counts['pipelines_shown']} (omitidos {counts['pipelines_omitted']}) · "
                 f"Workers: {counts['workers_shown']} (omitidos {counts['workers_omitted']})"),
            text(" · ".join(f"{k}: {v}" for k, v in model["class_counts"].items()) or "Sin clases", 12, Q_MUTED),
        ]))
        rows = []
        for p in model["pipelines"]:
            rows.append(text(f"{p['pipeline_id']} · {p['lifecycle']} · {p['outcome']} · {p['agreement']} · "
                             f"atención {p['attention_class']}", bold=True))
            rows.extend(text(f"   {w['worker_id']} · {w['lifecycle']} · {w['outcome']} / resultado "
                             f"{w['result_outcome']} · {w['agreement']} · atención {w['attention_class']} "
                             f"({w['primary_reason']})", 12) for w in p["workers"])
        if model["pipelines_more"]:
            rows.append(text("Hay más pipelines no mostrados.", 12, Q_MUTED))
        controls.append(card("Pipelines y workers", rows or [text("Sin pipelines.", color=Q_MUTED)]))
        items = [text(f"{i['attention_class']} · {_subject(i)} · {i['primary_reason']} · actor {i['actor']} · "
                      f"origen {i['origin']}", color=_CLASS_COLORS.get(i["attention_class"], Q_MUTED))
                 for i in model["attention"]]
        if model["attention_more"]:
            items.append(text("Hay más elementos de atención no mostrados.", 12, Q_MUTED))
        controls.append(card("HUMAN ATTENTION", items or [text("Sin elementos que requieran atención.",
                                                                color=Q_MUTED)]))
    controls.append(card("Actuaciones gobernadas", [
        text(f"{a['label']}: No autorizada (requiere gateway gobernado y decisión de Dirección)", 12, Q_MUTED)
        for a in model["actions"]
    ]))
    return controls


def fabric_control_plane_view(page, sources=None, gateway=None, now_utc=None):
    """Flet view. Reads only on open and on «Actualizar»; never on a timer."""
    import flet as ft
    from frontend.components.app_alert import error_alert, warning_alert
    from frontend.components.app_button import primary_button
    from frontend.components.app_empty_state import empty_state

    components = {"error_alert": error_alert, "warning_alert": warning_alert, "empty_state": empty_state}
    clock = now_utc if now_utc is not None else _now_utc
    body = ft.Column(controls=[], spacing=12)

    def refresh(e=None):
        if sources is None:
            model = error_model("GATEWAY_SOURCE_REQUIRED", "the query needs a source that was not given")
        else:
            model = observe(sources, utc_text(clock()), gateway=gateway)
        body.controls = render_controls(ft, model, components)
        if e is not None:
            try:
                page.update()
            except Exception:  # noqa: BLE001 - the view stays as rendered
                pass
        return model

    refresh()
    header = ft.Row(
        controls=[ft.Text(VIEW_TITLE, size=24, weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK, expand=True),
                  primary_button("Actualizar", refresh)],
        vertical_alignment=ft.CrossAxisAlignment.CENTER,
    )
    return ft.Container(
        expand=True, padding=20,
        content=ft.Column(controls=[header, body], spacing=14, scroll=ft.ScrollMode.AUTO, expand=True),
    )
