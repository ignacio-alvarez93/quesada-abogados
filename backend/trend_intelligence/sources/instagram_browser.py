"""
Frontera de navegador para el collector de Instagram.

Owner logico: IT_INSTAGRAM_COLLECTOR
browser_profile_key: it_instagram_collector

Reutiliza la infraestructura gobernada de navegador ya existente
(``backend.automation``): BrowserSessionConfig, SeleniumBaseBrowserSession,
open_url y la resolucion generica de perfiles persistentes. No crea un
segundo runtime de navegador ni un segundo registro de perfiles.

V1 es deliberadamente conservador:

- solo lectura;
- cuentas objetivo explicitas, nunca descubiertas;
- un limite deterministico de piezas recientes por cuenta;
- selectores DOM centralizados aqui, nunca esparcidos por el resto de
  Trend Intelligence;
- ante login / checkpoint / challenge / restriccion de acceso: falla
  controlado (InstagramAccessBlockedError) sin intentar evadirlo.

No implementa likes, follows, comentarios, DMs, publicacion ni ninguna
accion de escritura. No persiste credenciales: la sesion persistente ya
fue autenticada manualmente por el operador fuera de este codigo.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import urlsplit
from uuid import uuid4

from backend.automation.browser_actions import open_url
from backend.automation.browser_contracts import (
    BrowserSessionConfig,
    BrowserSessionMode,
)
from backend.automation.browser_profiles import get_browser_profile_dir
from backend.automation.seleniumbase_browser_session import (
    SeleniumBaseBrowserSession,
)
from backend.trend_intelligence.sources.instagram import (
    InstagramRawObservation,
    InstagramTrendSourceAdapter,
)
from backend.trend_intelligence.models import canonical_time


OWNER = "IT_INSTAGRAM_COLLECTOR"
DEFAULT_PROFILE_KEY = "it_instagram_collector"

INSTAGRAM_BASE_URL = "https://www.instagram.com/"

# Selectores DOM centralizados. Son la unica superficie que deberia
# requerir ajuste si Instagram cambia su marcado; nunca se duplican en
# otros puntos de Trend Intelligence.
POST_LINK_SELECTOR = (
    "main a[href*='/p/'], main a[href*='/reel/']"
)
CAPTION_META_SELECTOR = "meta[property='og:description']"
PUBLISHED_AT_SELECTOR = "time[datetime]"
# Read only public DOM attributes, in one snapshot. JSON avoids CDP remote
# object serialization differences. The nearest anchor establishes ownership.
PUBLISHED_AT_SCRIPT = """JSON.stringify(Array.from(document.querySelectorAll(
    %s
), node => ({
    datetime: node.getAttribute('datetime'),
    href: node.closest('a[href]')?.getAttribute('href') || null
})))""" % json.dumps(PUBLISHED_AT_SELECTOR)
LOGIN_FORM_SELECTOR = "input[name='username'], form#loginForm"

LOGIN_URL_FRAGMENT = "/accounts/login"
CHALLENGE_URL_FRAGMENT = "/challenge"
CHECKPOINT_URL_FRAGMENT = "/checkpoint"

_SHORTCODE_PATTERN = re.compile(
    r"/(?:[A-Za-z0-9_.]+/)?(?P<kind>p|reel)/(?P<shortcode>[A-Za-z0-9_-]+)/?"
)


class InstagramAccessBlockedError(RuntimeError):
    """Instagram exige login / checkpoint / challenge / esta restringido.

    V1 nunca intenta evadir este estado: falla controlado.
    """


def _resolve_instagram_profile(profile_key):
    """Resolve lazily outside worktrees using the shared profile engine."""
    return get_browser_profile_dir(
        profile_key,
        profiles_root=Path.home() / ".quesada_browser_profiles",
    )


def _default_clock():
    return datetime.now(timezone.utc).isoformat()


def _post_url_parts(url):
    parts = urlsplit(url or "")
    match = _SHORTCODE_PATTERN.fullmatch(parts.path)

    if (
        not match
        or parts.scheme not in ("", "http", "https")
        or (parts.netloc and parts.netloc.lower() not in ("instagram.com", "www.instagram.com"))
        or (parts.scheme and not parts.netloc)
        or parts.path.split("/")[1] in ("stories", "explore")
    ):
        raise ValueError(
            f"No se pudo extraer external_id de la URL de Instagram: {url!r}"
        )

    return match.group("kind"), match.group("shortcode")


def _extract_shortcode(url):
    return _post_url_parts(url)[1]


def _element_value(element, *, attribute):
    if attribute:
        getter = getattr(element, "get_attribute", None)

        if callable(getter):
            return getter(attribute)

        return getattr(element, attribute, None)

    return getattr(element, "text", None)


def _optional_elements(browser, selector):
    """Busqueda de presencia opcional: la ausencia es un resultado normal.

    ``find_elements`` delega en ``select_all`` de SeleniumBase/CDP, que
    espera hasta un timeout acotado y, si el selector nunca aparece,
    levanta ``TimeoutError`` en lugar de devolver una lista vacia. Para
    chequeos de presencia opcional (login wall, meta de caption,
    timestamp, enlaces de posts) la ausencia del selector es la condicion
    normal, nunca un fallo del collector. Un ``TimeoutError`` real de
    navegacion (pagina que nunca carga) no pasa por aqui: solo ocurre
    dentro de esta busqueda de presencia acotada.
    """
    try:
        return browser.find_elements(selector) or []
    except TimeoutError:
        return []


def _first_value(browser, selector, *, attribute=None):
    elements = _optional_elements(browser, selector)

    if not elements:
        return None

    value = _element_value(
        elements[0],
        attribute=attribute,
    )

    value = str(value or "").strip()

    return value or None


def _published_at(browser, url):
    """Accept only a unique, timezone-aware instant owned by this media."""
    evaluate = getattr(browser, "evaluate", None)
    if not callable(evaluate):
        return None

    target = _post_url_parts(url)
    candidates = json.loads(evaluate(PUBLISHED_AT_SCRIPT))
    dates = set()
    for candidate in candidates:
        try:
            # Full path matching excludes /c/<id>/ and all other suffixes.
            if _post_url_parts(candidate["href"]) != target:
                continue
        except ValueError:
            continue
        try:
            raw = str(candidate["datetime"] or "").strip()
            if datetime.fromisoformat(raw.replace("Z", "+00:00")).tzinfo is None:
                return None
            dates.add(canonical_time(raw))
        except (ValueError, OverflowError):
            return None

    return next(iter(dates)) if len(dates) == 1 else None


@dataclass(
    frozen=True,
    slots=True,
)
class InstagramCollectionTarget:
    account: str
    limit: int = 5

    def __post_init__(self):
        account = str(self.account or "").strip().lstrip("@")

        if not account:
            raise ValueError("account obligatorio")

        object.__setattr__(self, "account", account)

        limit = int(self.limit)

        if limit <= 0:
            raise ValueError("limit debe ser positivo")

        object.__setattr__(self, "limit", limit)


@dataclass(
    frozen=True,
    slots=True,
)
class InstagramCollectionConfig:
    """Configuracion explicita de un run de recoleccion.

    Las cuentas objetivo nunca se hardcodean en logica de produccion:
    siempre llegan desde esta configuracion, construida por el
    entrypoint del operador.
    """

    source_code: str
    targets: tuple[InstagramCollectionTarget, ...]
    profile_key: str = DEFAULT_PROFILE_KEY
    headless: bool = True

    def __post_init__(self):
        source_code = str(self.source_code or "").strip()

        if not source_code:
            raise ValueError("source_code obligatorio")

        object.__setattr__(self, "source_code", source_code)

        targets = tuple(self.targets or ())

        if not targets:
            raise ValueError("targets obligatorio (lista de cuentas)")

        for target in targets:
            if not isinstance(target, InstagramCollectionTarget):
                raise TypeError(
                    "targets debe contener InstagramCollectionTarget"
                )

        object.__setattr__(self, "targets", targets)


class InstagramBrowserCollector:
    """Collector de solo lectura sobre la sesion persistente gobernada.

    ``browser_session_factory`` y ``profile_resolver`` son inyectables
    para permitir tests deterministicos sin abrir Chrome real (TI-IG V1
    objetivo 7: el job de implementacion nunca lanza Chrome ni accede a
    Instagram real).
    """

    def __init__(
        self,
        *,
        profile_key=DEFAULT_PROFILE_KEY,
        headless=True,
        browser_session_factory=None,
        profile_resolver=None,
        clock=None,
    ):
        self.profile_key = str(
            profile_key or DEFAULT_PROFILE_KEY
        ).strip()

        if not self.profile_key:
            raise ValueError("profile_key de Instagram vacio")

        self.headless = bool(headless)

        self._browser_session_factory = (
            browser_session_factory
            or SeleniumBaseBrowserSession
        )

        if not callable(self._browser_session_factory):
            raise TypeError(
                "browser_session_factory debe ser callable"
            )

        self._profile_resolver = (
            profile_resolver
            or _resolve_instagram_profile
        )

        if not callable(self._profile_resolver):
            raise TypeError(
                "profile_resolver debe ser callable"
            )

        self._clock = clock or _default_clock

        if not callable(self._clock):
            raise TypeError("clock debe ser callable")

        self._browser_session = None
        self.browser = None

    def _build_browser_session(self):
        if self._browser_session is None:
            config = BrowserSessionConfig(
                consumer=OWNER,
                mode=BrowserSessionMode.PERSISTENT,
                headless=self.headless,
                profile_key=self.profile_key,
            )

            self._browser_session = self._browser_session_factory(
                config=config,
                profile_resolver=self._profile_resolver,
            )

        return self._browser_session

    def start(self):
        session = self._build_browser_session()
        self.browser = session.start()
        return self.browser

    def shutdown(self):
        if self._browser_session is None:
            return None

        return self._browser_session.shutdown()

    def _current_url(self):
        url = getattr(self.browser, "url", None)

        if url:
            return url

        evaluate = getattr(self.browser, "evaluate", None)

        if callable(evaluate):
            return evaluate("window.location.href")

        return None

    def _assert_not_blocked(self, account):
        url = str(self._current_url() or "")

        if any(fragment in url for fragment in (
            LOGIN_URL_FRAGMENT, CHALLENGE_URL_FRAGMENT, CHECKPOINT_URL_FRAGMENT,
        )):
            raise InstagramAccessBlockedError(
                "Instagram redirigio a login/challenge/checkpoint al acceder a "
                f"{account!r} (url={url!r})"
            )

        if _optional_elements(self.browser, LOGIN_FORM_SELECTOR):
            raise InstagramAccessBlockedError(
                f"Instagram solicito login para acceder a {account!r}"
            )

    def collect_account(self, account, *, limit=5):
        if self.browser is None:
            raise RuntimeError(
                "InstagramBrowserCollector no iniciado: "
                "llama start() antes de collect_account()"
            )

        target = InstagramCollectionTarget(
            account=account,
            limit=limit,
        )

        open_url(
            self.browser,
            f"{INSTAGRAM_BASE_URL}{target.account}/",
        )

        self._assert_not_blocked(target.account)

        post_urls = self._bounded_post_urls(target.limit)

        collection_run_id = uuid4().hex

        return [
            self._collect_post(
                target.account,
                url,
                collection_run_id=collection_run_id,
            )
            for url in post_urls
        ]

    def _bounded_post_urls(self, limit):
        links = _optional_elements(self.browser, POST_LINK_SELECTOR)

        urls = []
        seen = set()

        for link in links:
            href = _element_value(link, attribute="href")

            if not href:
                continue

            try:
                kind, shortcode = _post_url_parts(href)
            except ValueError:
                # A matching href substring is only a candidate, not a post.
                continue

            if shortcode in seen:
                continue

            seen.add(shortcode)
            urls.append(f"{INSTAGRAM_BASE_URL}{kind}/{shortcode}/")

            if len(urls) >= limit:
                break

        return urls

    def _collect_post(self, account, url, *, collection_run_id):
        open_url(self.browser, url)

        self._assert_not_blocked(account)

        external_id = _extract_shortcode(url)

        caption = _first_value(
            self.browser,
            CAPTION_META_SELECTOR,
            attribute="content",
        )

        published_at = _published_at(self.browser, url)

        content_type = "REEL" if "/reel/" in url else "POST"

        raw_hash = hashlib.sha256(
            json.dumps(
                {
                    "url": url,
                    "caption": caption,
                    "published_at": published_at,
                },
                sort_keys=True,
                ensure_ascii=False,
            ).encode("utf-8")
        ).hexdigest()

        return InstagramRawObservation(
            source_account=account,
            external_id=external_id,
            canonical_url=url,
            content_type=content_type,
            observed_at=self._clock(),
            published_at=published_at,
            caption=caption,
            raw_hash=raw_hash,
            collection_run_id=collection_run_id,
        )


def run_instagram_collection(
    *,
    collector,
    config,
    ingestion_service,
    domain_code=None,
):
    """Orquesta collector -> adapter -> TrendIngestionService.ingest.

    No reimplementa dedupe/scoring: delega integramente en el
    ingestion entrypoint ya existente.
    """

    if not isinstance(config, InstagramCollectionConfig):
        raise TypeError(
            "config debe ser InstagramCollectionConfig"
        )

    raw_observations = []

    for target in config.targets:
        raw_observations.extend(
            collector.collect_account(
                target.account,
                limit=target.limit,
            )
        )

    adapter = InstagramTrendSourceAdapter(
        config.source_code,
        raw_observations,
    )

    return ingestion_service.ingest(
        adapter,
        domain_code=domain_code,
    )
