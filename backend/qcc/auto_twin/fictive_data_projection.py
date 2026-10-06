"""Safe fictive-data projection for Twin runtime replay — AUTO TWIN (UWT-8).

``build_form_runtime_hydration_plan`` (UWT-6A2) already flags every
TEXT/TEXTAREA control that was observed REAL-populated
(``RUNTIME_POLICY_SUPPLY_SYNTHETIC_VALUE``) without ever exposing the
REAL literal: ``form_state.py`` only ever records ``has_value`` as a
boolean. Something must still supply a *value* at Twin-replay time —
otherwise required fields block the very state transitions the Twin
exists to validate — but nothing in AUTO TWIN may originate that value
from REAL captured data, because none is available, and none must ever
be synthesized to *look* real.

This module closes that gap: it projects a deterministic, unmistakably
fictive placeholder from the control's own opaque ``control_key`` and
its already-captured generic ``form_constraints`` (autocomplete/
minlength/maxlength) — never from any literal the REAL user typed.

Determinism is intentional: the same control, on the same materialized
revision, always projects the same fictive value, so Twin replay/tests
stay reproducible across runs and across providers.

No network. No browser. No REAL evidence read.
"""

from __future__ import annotations

import hashlib


FICTIVE_DATA_PROJECTION_SCHEMA_VERSION = 1

# RFC 2606 reserved TLD: guaranteed to never resolve on the public
# internet, so a fictive email can never become a REAL network target
# even by accident.
FICTIVE_EMAIL_DOMAIN = "twin.invalid"

_FICTIVE_MARKER = "qcc-twin-fictive"

_CATEGORY_EMAIL = "EMAIL"
_CATEGORY_TEL = "TEL"
_CATEGORY_DATE = "DATE"
_CATEGORY_NAME = "NAME"
_CATEGORY_ADDRESS = "ADDRESS"
_CATEGORY_CREDENTIAL = "CREDENTIAL"
_CATEGORY_GENERIC = "GENERIC"

# HTML `autocomplete` tokens -> fictive-data category. Per the HTML
# spec, `autocomplete` may carry several space-separated tokens (e.g.
# "shipping given-name"); only the last (field-type) token is
# classified here.
_AUTOCOMPLETE_CATEGORY = {
    "email": _CATEGORY_EMAIL,
    "tel": _CATEGORY_TEL,
    "tel-national": _CATEGORY_TEL,
    "tel-local": _CATEGORY_TEL,
    "tel-country-code": _CATEGORY_TEL,
    "tel-area-code": _CATEGORY_TEL,
    "bday": _CATEGORY_DATE,
    "bday-day": _CATEGORY_DATE,
    "bday-month": _CATEGORY_DATE,
    "bday-year": _CATEGORY_DATE,
    "name": _CATEGORY_NAME,
    "given-name": _CATEGORY_NAME,
    "family-name": _CATEGORY_NAME,
    "additional-name": _CATEGORY_NAME,
    "honorific-prefix": _CATEGORY_NAME,
    "honorific-suffix": _CATEGORY_NAME,
    "nickname": _CATEGORY_NAME,
    "organization": _CATEGORY_NAME,
    "organization-title": _CATEGORY_NAME,
    "street-address": _CATEGORY_ADDRESS,
    "address-line1": _CATEGORY_ADDRESS,
    "address-line2": _CATEGORY_ADDRESS,
    "address-line3": _CATEGORY_ADDRESS,
    "address-level1": _CATEGORY_ADDRESS,
    "address-level2": _CATEGORY_ADDRESS,
    "postal-code": _CATEGORY_ADDRESS,
    "country": _CATEGORY_ADDRESS,
    "country-name": _CATEGORY_ADDRESS,
    "username": _CATEGORY_CREDENTIAL,
    "new-password": _CATEGORY_CREDENTIAL,
    "current-password": _CATEGORY_CREDENTIAL,
    "one-time-code": _CATEGORY_CREDENTIAL,
}

_DEFAULT_LENGTH_BY_CATEGORY = {
    _CATEGORY_NAME: 16,
    _CATEGORY_ADDRESS: 24,
    _CATEGORY_CREDENTIAL: 20,
    _CATEGORY_GENERIC: 20,
}

_PREFIX_BY_CATEGORY = {
    _CATEGORY_NAME: "Qcc Twin Fictive ",
    _CATEGORY_ADDRESS: "123 Twin Fictive Street ",
    _CATEGORY_CREDENTIAL: "QccTwinFictive",
    _CATEGORY_GENERIC: _FICTIVE_MARKER + "-",
}

# A fixed, obviously-fictive calendar date. Never derived from any
# REAL evidence, so it carries no information about any real person.
_FICTIVE_DATE_VALUE = "1900-01-01"


def _digest(control_key):
    canonical = (
        "QCC_AUTO_TWIN_FICTIVE_DATA_PROJECTION_V1|"
        + str(control_key or "")
    )

    return hashlib.sha256(
        canonical.encode("utf-8")
    ).hexdigest()


def _digits_only(digest, length):
    numeric = "".join(
        character
        for character in digest
        if character.isdigit()
    )

    if not numeric:
        numeric = "0"

    while len(numeric) < length:
        numeric += numeric

    return numeric[:length]


def _autocomplete_category(autocomplete):
    token = str(autocomplete or "").strip().lower()

    if not token or token == "off":
        return _CATEGORY_GENERIC

    last_token = token.split()[-1]

    return _AUTOCOMPLETE_CATEGORY.get(
        last_token,
        _CATEGORY_GENERIC,
    )


def _bounded_length(form_constraints, *, default_length):
    constraints = form_constraints or {}

    length = int(default_length)

    minlength = constraints.get("minlength")

    if minlength is not None:
        try:
            length = max(length, int(minlength))

        except (TypeError, ValueError):
            pass

    maxlength = constraints.get("maxlength")

    if maxlength is not None:
        try:
            length = min(length, max(1, int(maxlength)))

        except (TypeError, ValueError):
            pass

    return max(1, length)


def _fit_length(value, *, length):
    if len(value) >= length:
        return value[:length]

    pad_source = value or _FICTIVE_MARKER

    while len(value) < length:
        value += pad_source

    return value[:length]


def project_fictive_text_value(
    *,
    control_key,
    form_constraints=None,
):
    """Deterministically projects a safe fictive TEXT/TEXTAREA value.

    ``control_key`` is the opaque, already-hashed identity produced by
    ``form_runtime_hydration._control_key`` — never a REAL DOM value.
    ``form_constraints`` is the generic, already-captured evidence
    produced by ``normalize_form_constraints`` (autocomplete/
    minlength/maxlength); it is read-only metadata about the control's
    *shape*, never about any REAL literal it once held.

    The result never depends on, nor reveals, any REAL captured value:
    AUTO TWIN structurally never has one available to begin with (see
    ``backend/automation/site_architecture/form_state.py``).
    """

    if not str(control_key or "").strip():
        raise ValueError(
            "QCC_AUTO_TWIN_FICTIVE_DATA_PROJECTION_CONTROL_KEY_REQUIRED"
        )

    constraints = form_constraints or {}

    digest = _digest(control_key)

    category = _autocomplete_category(
        constraints.get("autocomplete")
    )

    if category == _CATEGORY_EMAIL:
        return (
            _FICTIVE_MARKER
            + "-"
            + digest[:12]
            + "@"
            + FICTIVE_EMAIL_DOMAIN
        )

    if category == _CATEGORY_TEL:
        length = _bounded_length(
            constraints,
            default_length=9,
        )

        return "+0" + _digits_only(digest, length)

    if category == _CATEGORY_DATE:
        return _FICTIVE_DATE_VALUE

    length = _bounded_length(
        constraints,
        default_length=_DEFAULT_LENGTH_BY_CATEGORY.get(
            category,
            _DEFAULT_LENGTH_BY_CATEGORY[_CATEGORY_GENERIC],
        ),
    )

    prefix = _PREFIX_BY_CATEGORY.get(
        category,
        _PREFIX_BY_CATEGORY[_CATEGORY_GENERIC],
    )

    return _fit_length(
        prefix + digest,
        length=length,
    )
