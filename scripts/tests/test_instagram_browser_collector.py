"""IT Instagram Collector v1: browser boundary, read-only, no real Chrome.

Per the WORK ORDER (objective 7), this suite never launches Chrome and
never accesses Instagram real: ``InstagramBrowserCollector`` is exercised
entirely against a fake browser/session, injected through the same
``browser_session_factory`` / ``profile_resolver`` seams already used by
other SeleniumBaseBrowserSession consumers (see WhatsAppConnector).
"""
import inspect
import json
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from backend.automation import browser_profiles
from backend.automation.seleniumbase_browser_session import SeleniumBaseBrowserSession

from backend.automation.browser_contracts import BrowserSessionMode
from backend.automation.browser_profiles import get_browser_profile_dir
from backend.trend_intelligence.ingestion import TrendIngestionService
from backend.trend_intelligence.sources.instagram_browser import (
    CAPTION_META_SELECTOR,
    DEFAULT_PROFILE_KEY,
    InstagramAccessBlockedError,
    InstagramDestinationError,
    InstagramBrowserCollector,
    InstagramCollectionConfig,
    InstagramCollectionTarget,
    LOGIN_FORM_SELECTOR,
    OWNER,
    POST_LINK_SELECTOR,
    PUBLISHED_AT_SELECTOR,
    PUBLISHED_AT_SCRIPT,
    run_instagram_collection,
)


class FakeElement:
    def __init__(self, attributes=None):
        self._attributes = attributes or {}

    def get_attribute(self, name):
        return self._attributes.get(name)


class FakeInstagramBrowser:
    """Minimal stand-in for sb_cdp.Chrome used only in tests."""

    def __init__(self, *, pages, redirects=None):
        self._pages = pages
        self._redirects = redirects or {}
        self.url = None
        self.visited = []

    def open(self, url):
        self.visited.append(url)
        self.url = self._redirects.get(url, url)

    def evaluate(self, expression):
        assert expression == PUBLISHED_AT_SCRIPT
        value = self._pages.get(self.url, {}).get("published_at")
        return json.dumps([
            {"datetime": value, "href": self.url}
        ] if value is not None else [])

    def find_elements(self, selector):
        page = self._pages.get(self.url, {})

        if selector == POST_LINK_SELECTOR:
            return [FakeElement({"href": href}) for href in page.get("links", ())]

        if selector == CAPTION_META_SELECTOR:
            caption = page.get("caption")
            return [FakeElement({"content": caption})] if caption is not None else []

        if selector == PUBLISHED_AT_SELECTOR:
            published_at = page.get("published_at")
            return (
                [FakeElement({"datetime": published_at})]
                if published_at is not None
                else []
            )

        if selector == LOGIN_FORM_SELECTOR:
            return [FakeElement()] if page.get("login_wall") else []

        return []


class FakeTimeoutRaisingInstagramBrowser(FakeInstagramBrowser):
    """Reproduces the REAL SeleniumBase/CDP ``select_all`` behaviour.

    In current SeleniumBase CDP, ``find_elements`` (-> ``select_all``)
    does not return an empty list when a selector never appears: it waits
    out its bounded timeout and raises ``TimeoutError``. Absence of an
    optional selector (login wall, challenge markup, etc.) must still be
    treated as "not present", never as a collector failure.
    """

    def find_elements(self, selector):
        elements = super().find_elements(selector)

        if not elements:
            raise TimeoutError(
                f"Time ran out while waiting for: {{{selector}}}"
            )

        return elements


class FakeBrowserSession:
    def __init__(self, *, config, profile_resolver, browser):
        self.config = config
        self.profile_resolver = profile_resolver
        self._browser = browser
        self.started = False
        self.shutdown_called = False

    def start(self):
        self.started = True
        return self._browser

    def shutdown(self):
        self.shutdown_called = True
        return "SHUTDOWN_OK"


def _factory(browser):
    sessions = []

    def factory(*, config, profile_resolver):
        session = FakeBrowserSession(
            config=config,
            profile_resolver=profile_resolver,
            browser=browser,
        )
        sessions.append(session)
        return session

    factory.sessions = sessions
    return factory


def _collector(browser, *, profile_key=DEFAULT_PROFILE_KEY, **kwargs):
    factory = _factory(browser)

    collector = InstagramBrowserCollector(
        profile_key=profile_key,
        browser_session_factory=factory,
        profile_resolver=kwargs.pop(
            "profile_resolver",
            lambda key: f"/fake/profiles/{key}",
        ),
        clock=kwargs.pop("clock", lambda: "2026-10-11T10:00:00+00:00"),
        **kwargs,
    )

    collector.start()
    return collector, factory


class HtmlInstagramBrowser(FakeInstagramBrowser):
    """Evaluate actual CSS against synthetic HTML, never launch a browser."""

    def evaluate(self, expression):
        from bs4 import BeautifulSoup

        assert expression == PUBLISHED_AT_SCRIPT
        nodes = BeautifulSoup(self._pages[self.url], "html.parser").select(PUBLISHED_AT_SELECTOR)
        candidates = []
        for node in nodes:
            anchor = node.find_parent("a", href=True)
            candidates.append({"datetime": node.get("datetime"),
                               "href": anchor.get("href") if anchor else None})
        return json.dumps(candidates)

    def find_elements(self, selector):
        from bs4 import BeautifulSoup

        page = self._pages[self.url]
        return [FakeElement(dict(node.attrs)) for node in
                BeautifulSoup(page, "html.parser").select(selector)]


def nested_profile_pages():
    return {
        "https://www.instagram.com/natgeo/": """
            <nav><a href='/p/Outside/'>Outside main</a></nav>
            <main><header>natgeo</header><div role='tablist'>
              <a href='/natgeo/reels/'>Reels</a>
              <a href='/natgeo/tagged/'>Tagged</a>
              <a href='/natgeo/reposts/'>Reposts</a>
              <a href='/stories/highlights/123/'>Highlight</a>
              <a href='/explore/'>Explore</a>
            </div><div class='grid'>
              <a href='/natgeo/reel/DdG4RIxIPyf/'><img alt='Synthetic reel'></a>
              <a href='https://www.instagram.com/reel/DdG4RIxIPyf/?igsh=x'>Duplicate</a>
              <a href='/natgeo/p/DeWne1TF__R/'><img alt='Synthetic post'></a>
              <a href='/natgeo/reel/DbIdlf0j6uA/'>Third</a>
            </div></main>""",
        **{
            f"https://www.instagram.com/{kind}/{code}/":
                f"<head><meta property='og:description' content='Synthetic #{kind}'></head>"
                f"<main><a href='/{kind}/{code}/'>"
                "<time datetime='2026-10-10T00:00:00+00:00'></time></a></main>"
            for kind, code in (("reel", "DdG4RIxIPyf"), ("p", "DeWne1TF__R"),
                               ("reel", "DbIdlf0j6uA"))
        },
    }


class InstagramPublicationAttributionTest(unittest.TestCase):
    def collect_html(self, html, *, kind="p", redirect=None):
        url = f"https://www.instagram.com/{kind}/DeWne1TF__R/"
        browser = HtmlInstagramBrowser(pages={
            "https://www.instagram.com/natgeo/": f"<main><a href='{url}'>Media</a></main>",
            redirect or url: html,
        }, redirects={url: redirect} if redirect else {})
        collector, _ = _collector(browser)
        return collector.collect_account("natgeo", limit=1)[0]

    @staticmethod
    def linked_time(href, value="2026-10-12T01:00:01.000Z"):
        return f"<a href='{href}'><span><time datetime='{value}'></time></span></a>"

    def test_publication_after_ambiguous_time_and_eleven_comments(self):
        html = "<time datetime='2026-10-12T01:00:03.000Z'></time>"
        html += "".join(self.linked_time(
            f"/p/DeWne1TF__R/c/{index}/", "2026-10-12T02:00:00Z"
        ) for index in range(11))
        html += self.linked_time("/natgeo/p/DeWne1TF__R/")
        row = self.collect_html(html)
        self.assertEqual(row.published_at, "2026-10-12T01:00:01+00:00")
        self.assertNotEqual(row.published_at, row.observed_at)

    def test_direct_global_and_account_links(self):
        for href in ("/p/DeWne1TF__R/", "/natgeo/p/DeWne1TF__R/",
                     "https://www.instagram.com/p/DeWne1TF__R/?x=1#date",
                     "https://instagram.com/natgeo/p/DeWne1TF__R/"):
            with self.subTest(href=href):
                row = self.collect_html(self.linked_time(href, "2026-10-12T03:00:01+02:00"))
                self.assertEqual(row.published_at, "2026-10-12T01:00:01+00:00")

    def test_comments_other_media_and_invalid_owners_are_ignored(self):
        for href in ("/p/DeWne1TF__R/c/123/", "/natgeo/p/DeWne1TF__R/c/123/",
                     "/p/Other/", "/reel/DeWne1TF__R/", "/p/dewne1tf__r/",
                     "https://example.com/p/DeWne1TF__R/", "/p/DeWne1TF__R/extra/"):
            with self.subTest(href=href):
                self.assertIsNone(self.collect_html(self.linked_time(href)).published_at)

    def test_missing_unowned_invalid_and_naive_dates(self):
        for html in ("<main></main>", "<time datetime='2026-10-12T01:00:03Z'></time>",
                     self.linked_time("/p/DeWne1TF__R/", "invalid"),
                     self.linked_time("/p/DeWne1TF__R/", "2026-10-12T01:00:01")):
            with self.subTest(html=html):
                self.assertIsNone(self.collect_html(html).published_at)

    def test_reel_redirect_without_time_preserves_identity(self):
        row = self.collect_html("<main></main>", kind="reel",
                                redirect="https://www.instagram.com/reels/DeWne1TF__R/")
        self.assertIsNone(row.published_at)
        self.assertEqual(row.content_type, "REEL")
        self.assertEqual(row.canonical_url, "https://www.instagram.com/reel/DeWne1TF__R/")

    def test_conflicting_dates_are_ambiguous_in_either_order(self):
        first = self.linked_time("/p/DeWne1TF__R/")
        second = self.linked_time("/natgeo/p/DeWne1TF__R/", "2026-10-12T01:00:03Z")
        for html in (first + second, second + first):
            self.assertIsNone(self.collect_html(html).published_at)

    def test_equivalent_dates_are_one_instant(self):
        html = self.linked_time("/p/DeWne1TF__R/")
        html += self.linked_time("/natgeo/p/DeWne1TF__R/", "2026-10-12T03:00:01+02:00")
        self.assertEqual(self.collect_html(html).published_at, "2026-10-12T01:00:01+00:00")

    def test_evaluation_errors_are_not_swallowed(self):
        with patch.object(HtmlInstagramBrowser, "evaluate", side_effect=RuntimeError("connection lost")):
            with self.assertRaisesRegex(RuntimeError, "connection lost"):
                self.collect_html("<main></main>")


class InstagramNestedDomTest(unittest.TestCase):
    def test_global_and_scoped_urls_have_identical_observations(self):
        pages = nested_profile_pages()
        collector, _ = _collector(HtmlInstagramBrowser(pages=pages))
        nested = collector.collect_account("natgeo", limit=5)
        pages["https://www.instagram.com/natgeo/"] = """
            <main><article>
              <a href='/reel/DdG4RIxIPyf/?utm_source=test#fragment'>Reel</a>
              <a href='https://instagram.com/p/DeWne1TF__R/'>Post</a>
              <a href='/reel/DbIdlf0j6uA/'>Reel</a>
            </article></main>"""
        global_rows = collector.collect_account("natgeo", limit=5)
        self.assertEqual(
            [(r.external_id, r.canonical_url, r.raw_hash) for r in nested],
            [(r.external_id, r.canonical_url, r.raw_hash) for r in global_rows],
        )

    def test_false_candidates_are_ignored_before_limit(self):
        pages = nested_profile_pages()
        pages["https://www.instagram.com/natgeo/"] = """
            <main>
              <a href='/stories/p/Fake/'>Story</a>
              <a href='/explore/reel/Fake/'>Explore</a>
              <a href='/natgeo/reels/'>Tab</a>
              <a href='/natgeo/tagged/'>Tab</a>
              <a href='/natgeo/reposts/'>Tab</a>
              <a href='/stories/highlights/123/'>Highlight</a>
              <a href='https://example.com/p/Fake/'>External</a>
              <a href='/one/two/p/Fake/'>Extra prefix</a>
              <a href='/p/Fake/extra/'>Extra suffix</a>
              <a href='/p/bad%20code/'>Invalid shortcode</a>
              <a href='/p/'>Missing shortcode</a>
              <a href='/natgeo/p/DeWne1TF__R/'>Valid</a>
            </main>"""
        browser = HtmlInstagramBrowser(pages=pages)
        collector, _ = _collector(browser)
        rows = collector.collect_account("natgeo", limit=1)
        self.assertEqual([r.external_id for r in rows], ["DeWne1TF__R"])
        self.assertEqual(len(browser.visited), 2)

    def test_nested_dom_collection_and_limit(self):
        for limit in (2, 5):
            browser = HtmlInstagramBrowser(pages=nested_profile_pages())
            collector, _ = _collector(browser)
            rows = collector.collect_account("natgeo", limit=limit)
            self.assertEqual([row.external_id for row in rows],
                             ["DdG4RIxIPyf", "DeWne1TF__R", "DbIdlf0j6uA"][:limit])
            self.assertEqual([row.content_type for row in rows], ["REEL", "POST", "REEL"][:limit])
            self.assertEqual(rows[1].canonical_url, "https://www.instagram.com/p/DeWne1TF__R/")
            self.assertEqual(rows[0].caption, "Synthetic #reel")
            self.assertEqual(rows[0].published_at, "2026-10-10T00:00:00+00:00")
            self.assertEqual(len(browser.visited), len(rows) + 1)

    def test_nested_dom_ingestion_is_idempotent(self):
        import tempfile
        from backend.repositories.sqlite_trend_intelligence_repository import SQLiteTrendIntelligenceRepository
        from backend.trend_intelligence.service import TrendIntelligenceService

        with tempfile.TemporaryDirectory() as directory:
            service = TrendIntelligenceService(repository=SQLiteTrendIntelligenceRepository(Path(directory) / "synthetic.db"))
            service.ensure_schema()
            service.create_source(code="IG_SYNTHETIC", name="Synthetic", source_type="SOCIAL", collection_mode="SELENIUM")
            collector, _ = _collector(HtmlInstagramBrowser(pages=nested_profile_pages()))
            config = InstagramCollectionConfig(source_code="IG_SYNTHETIC", targets=(InstagramCollectionTarget("natgeo", 2),))
            reports = [run_instagram_collection(collector=collector, config=config,
                       ingestion_service=TrendIngestionService(service)) for _ in range(2)]
            self.assertEqual((reports[0].total, reports[0].created, reports[0].duplicates), (2, 2, 0))
            self.assertEqual((reports[1].total, reports[1].created, reports[1].duplicates), (2, 0, 2))
            self.assertEqual(reports[0].observation_ids, reports[1].observation_ids)


class InstagramBrowserCollectorLogicalProfileTest(unittest.TestCase):
    def test_uses_logical_profile_key_and_owner(self):
        browser = FakeInstagramBrowser(pages={})
        collector, factory = _collector(browser)

        session = factory.sessions[0]
        self.assertEqual(session.config.profile_key, DEFAULT_PROFILE_KEY)
        self.assertEqual(session.config.consumer, OWNER)
        self.assertEqual(session.config.mode, BrowserSessionMode.PERSISTENT)
        self.assertTrue(session.started)

    def test_default_profile_resolver_reuses_generic_infrastructure(self):
        collector = InstagramBrowserCollector(
            browser_session_factory=_factory(FakeInstagramBrowser(pages={})),
        )

        with patch(
            "backend.trend_intelligence.sources.instagram_browser.get_browser_profile_dir"
        ) as resolve, patch.object(Path, "home", return_value=Path("/fake/home")):
            result = collector._profile_resolver(DEFAULT_PROFILE_KEY)
        resolve.assert_called_once_with(
            DEFAULT_PROFILE_KEY,
            profiles_root=Path("/fake/home") / ".quesada_browser_profiles",
        )
        self.assertIs(result, resolve.return_value)

    def test_no_credentials_accepted_or_persisted(self):
        signature = inspect.signature(InstagramBrowserCollector.__init__)
        forbidden_params = {"username", "password", "session_cookie", "token"}
        self.assertFalse(forbidden_params & set(signature.parameters))

        browser = FakeInstagramBrowser(
            pages={
                "https://www.instagram.com/example_account/": {
                    "links": ["https://www.instagram.com/p/ABC/"],
                },
                "https://www.instagram.com/p/ABC/": {
                    "caption": "hello",
                    "published_at": "2026-10-10T00:00:00+00:00",
                },
            }
        )
        collector, _ = _collector(browser)

        observations = collector.collect_account("example_account", limit=5)
        payload = str(observations)

        for secret_marker in ("password", "cookie", "token"):
            self.assertNotIn(secret_marker, payload.lower())


class InstagramBrowserCollectorNoWriteActionsTest(unittest.TestCase):
    def test_exposes_no_interactive_or_write_actions(self):
        forbidden_methods = (
            "like",
            "follow",
            "unfollow",
            "comment",
            "send_message",
            "send_dm",
            "post",
            "publish",
            "edit_profile",
        )

        for method_name in forbidden_methods:
            self.assertFalse(
                hasattr(InstagramBrowserCollector, method_name),
                f"InstagramBrowserCollector no debe exponer {method_name}",
            )


class InstagramBrowserCollectorExtractionTest(unittest.TestCase):
    def test_bounded_collection_respects_deterministic_limit(self):
        links = [
            f"https://www.instagram.com/p/POST-{i}/" for i in range(10)
        ]
        pages = {
            "https://www.instagram.com/example_account/": {"links": links},
        }
        for link in links:
            pages[link] = {"caption": None, "published_at": None}

        browser = FakeInstagramBrowser(pages=pages)
        collector, _ = _collector(browser)

        observations = collector.collect_account("example_account", limit=3)

        self.assertEqual(len(observations), 3)
        self.assertEqual(
            [item.external_id for item in observations],
            ["POST-0", "POST-1", "POST-2"],
        )

    def test_only_the_configured_account_is_visited(self):
        pages = {
            "https://www.instagram.com/example_account/": {
                "links": ["https://www.instagram.com/p/ABC/"],
            },
            "https://www.instagram.com/p/ABC/": {
                "caption": "hi",
                "published_at": "2026-10-10T00:00:00+00:00",
            },
        }
        browser = FakeInstagramBrowser(pages=pages)
        collector, _ = _collector(browser)

        collector.collect_account("example_account", limit=5)

        visited_accounts = {
            url
            for url in browser.visited
            if url.startswith("https://www.instagram.com/")
            and "/p/" not in url
        }
        self.assertEqual(
            visited_accounts,
            {"https://www.instagram.com/example_account/"},
        )

    def test_missing_optional_values_remain_null(self):
        pages = {
            "https://www.instagram.com/example_account/": {
                "links": ["https://www.instagram.com/p/ABC/"],
            },
            "https://www.instagram.com/p/ABC/": {},
        }
        browser = FakeInstagramBrowser(pages=pages)
        collector, _ = _collector(browser)

        observations = collector.collect_account("example_account", limit=5)

        self.assertEqual(len(observations), 1)
        observation = observations[0]
        self.assertIsNone(observation.caption)
        self.assertIsNone(observation.published_at)
        self.assertIsNone(observation.like_count)

    def test_caption_and_published_at_are_extracted_when_visible(self):
        pages = {
            "https://www.instagram.com/example_account/": {
                "links": ["https://www.instagram.com/reel/XYZ/"],
            },
            "https://www.instagram.com/reel/XYZ/": {
                "caption": "Trip to #madrid",
                "published_at": "2026-10-09T12:00:00+00:00",
            },
        }
        browser = FakeInstagramBrowser(pages=pages)
        collector, _ = _collector(browser)

        observations = collector.collect_account("example_account", limit=5)

        self.assertEqual(len(observations), 1)
        observation = observations[0]
        self.assertEqual(observation.content_type, "REEL")
        self.assertEqual(observation.caption, "Trip to #madrid")
        self.assertEqual(observation.published_at, "2026-10-09T12:00:00+00:00")


class InstagramBrowserCollectorAccessBlockedTest(unittest.TestCase):
    def test_redirect_to_login_fails_controlled(self):
        browser = FakeInstagramBrowser(
            pages={
                "https://www.instagram.com/example_account/": {
                    "links": ["https://www.instagram.com/p/ABC/"],
                },
            },
            redirects={
                "https://www.instagram.com/example_account/": (
                    "https://www.instagram.com/accounts/login/?next=/example_account/"
                ),
            },
        )
        collector, _ = _collector(browser)

        with self.assertRaises(InstagramAccessBlockedError):
            collector.collect_account("example_account", limit=5)

        # Never attempted to scrape a post after the access block.
        self.assertNotIn(
            "https://www.instagram.com/p/ABC/",
            browser.visited,
        )

    def test_login_form_present_fails_controlled(self):
        browser = FakeInstagramBrowser(
            pages={
                "https://www.instagram.com/example_account/": {
                    "login_wall": True,
                    "links": ["https://www.instagram.com/p/ABC/"],
                },
            },
        )
        collector, _ = _collector(browser)

        with self.assertRaises(InstagramAccessBlockedError):
            collector.collect_account("example_account", limit=5)

    def test_challenge_redirect_fails_controlled(self):
        browser = FakeInstagramBrowser(
            pages={
                "https://www.instagram.com/example_account/": {
                    "links": ["https://www.instagram.com/p/ABC/"],
                },
            },
            redirects={
                "https://www.instagram.com/example_account/": (
                    "https://www.instagram.com/challenge/"
                ),
            },
        )
        collector, _ = _collector(browser)

        with self.assertRaises(InstagramAccessBlockedError):
            collector.collect_account("example_account", limit=5)


class InstagramBrowserCollectorOptionalSelectorTimeoutTest(unittest.TestCase):
    """REAL defect: absence of an optional selector must never fail the
    collector, even when SeleniumBase/CDP signals absence via
    ``TimeoutError`` instead of an empty list."""

    def test_absent_login_selector_raising_timeout_is_not_blocked(self):
        browser = FakeTimeoutRaisingInstagramBrowser(
            pages={
                "https://www.instagram.com/example_account/": {
                    "links": ["https://www.instagram.com/p/ABC/"],
                },
                "https://www.instagram.com/p/ABC/": {
                    "caption": "hello",
                    "published_at": "2026-10-10T00:00:00+00:00",
                },
            }
        )
        collector, _ = _collector(browser)

        observations = collector.collect_account("example_account", limit=5)

        self.assertEqual(len(observations), 1)
        self.assertEqual(observations[0].caption, "hello")

    def test_present_login_selector_still_blocks_under_timeout_raising_fake(self):
        browser = FakeTimeoutRaisingInstagramBrowser(
            pages={
                "https://www.instagram.com/example_account/": {
                    "login_wall": True,
                    "links": ["https://www.instagram.com/p/ABC/"],
                },
            }
        )
        collector, _ = _collector(browser)

        with self.assertRaises(InstagramAccessBlockedError):
            collector.collect_account("example_account", limit=5)

    def test_present_challenge_redirect_still_blocks_under_timeout_raising_fake(self):
        browser = FakeTimeoutRaisingInstagramBrowser(
            pages={
                "https://www.instagram.com/example_account/": {
                    "links": ["https://www.instagram.com/p/ABC/"],
                },
            },
            redirects={
                "https://www.instagram.com/example_account/": (
                    "https://www.instagram.com/challenge/"
                ),
            },
        )
        collector, _ = _collector(browser)

        with self.assertRaises(InstagramAccessBlockedError):
            collector.collect_account("example_account", limit=5)

    def test_unexpected_non_timeout_browser_error_is_not_swallowed(self):
        class FakeBrokenInstagramBrowser(FakeInstagramBrowser):
            def find_elements(self, selector):
                if selector == LOGIN_FORM_SELECTOR:
                    raise RuntimeError("devtools connection lost")

                return super().find_elements(selector)

        browser = FakeBrokenInstagramBrowser(
            pages={
                "https://www.instagram.com/example_account/": {
                    "links": ["https://www.instagram.com/p/ABC/"],
                },
            },
        )
        collector, _ = _collector(browser)

        with self.assertRaises(RuntimeError):
            collector.collect_account("example_account", limit=5)


class InstagramFailureContractTest(unittest.TestCase):
    def setUp(self):
        self.profile = "https://www.instagram.com/first/"
        self.post = "https://www.instagram.com/p/FIRST/"
        self.browser = FakeInstagramBrowser(pages={
            self.profile: {"links": [self.post]},
            self.post: {"caption": "first"},
            "https://www.instagram.com/empty/": {},
            "https://www.instagram.com/second/": {"links": ["/reel/SECOND/"]},
            "https://www.instagram.com/reel/SECOND/": {"caption": "second"},
        })
        self.collector, self.factory = _collector(self.browser)
        self.addCleanup(self.collector.shutdown)

    def test_invalid_destinations_fail_before_content_extraction_or_ingestion(self):
        destinations = {
            self.profile: (
                "https://example.com/first/", "https://www.instagram.com/other/",
                "https://www.instagram.com/first/tagged/",
                "https://www.instagram.com.evil.test/first/",
                "https://www.instagram.com@evil.test/first/",
                "/first/", "about:blank", "https://[invalid", "",
            ),
            self.post: (
                "https://example.com/p/FIRST/", "https://www.instagram.com/p/OTHER/",
                "https://www.instagram.com/p/first/", "https://www.instagram.com/reel/FIRST/",
                "https://www.instagram.com/p/FIRST/extra/", "/p/FIRST/",
                "https://www.instagram.com/p/FIRST/c/123/", "about:blank", "",
                "https://www.instagram.com/other/p/FIRST/",
            ),
        }
        config = InstagramCollectionConfig(source_code="IG_TEST", targets=tuple(
            InstagramCollectionTarget(account) for account in ("second", "first", "empty")
        ))
        for location, urls in destinations.items():
            for destination in urls:
                with self.subTest(location=location, destination=destination):
                    self.browser._redirects = {location: destination}
                    self.browser.visited.clear()
                    ingestion = Mock()
                    original_find = self.browser.find_elements

                    def guarded_find(selector):
                        if self.browser.url == destination and selector != LOGIN_FORM_SELECTOR:
                            self.fail("Content read from an unverified destination")
                        return original_find(selector)

                    original_evaluate = self.browser.evaluate

                    def guarded_evaluate(expression):
                        if expression == "window.location.href":
                            return self.browser.url
                        if self.browser.url == destination:
                            self.fail("Metadata read from an unverified destination")
                        return original_evaluate(expression)

                    with patch.object(self.browser, "find_elements", side_effect=guarded_find), patch.object(
                        self.browser, "evaluate", side_effect=guarded_evaluate,
                    ), self.assertRaises(InstagramDestinationError):
                        run_instagram_collection(collector=self.collector, config=config,
                                                 ingestion_service=ingestion)
                    ingestion.ingest.assert_not_called()
                    self.assertNotIn("https://www.instagram.com/empty/", self.browser.visited)

    def test_equivalent_canonical_destinations_preserve_observation(self):
        profile_destination = "https://instagram.com/FIRST?next=/accounts/login/#/challenge/"
        self.browser._pages[profile_destination] = self.browser._pages[self.profile]
        for destination in (
            "https://instagram.com/p/FIRST", "https://www.instagram.com/first/p/FIRST/",
            "https://www.instagram.com/p/FIRST/?next=/checkpoint/#/accounts/login/",
        ):
            with self.subTest(destination=destination):
                self.browser._pages[destination] = {
                    "caption": "verified", "published_at": "2026-10-10T00:00:00+00:00",
                }
                self.browser._redirects = {self.profile: profile_destination, self.post: destination}
                row, = self.collector.collect_account("first")
                self.assertEqual((row.source_account, row.external_id, row.content_type),
                                 ("first", "FIRST", "POST"))
                self.assertEqual(row.canonical_url, self.post)
                self.assertEqual(row.caption, "verified")
                self.assertEqual(row.published_at, "2026-10-10T00:00:00+00:00")

    def test_reel_variant_checks_shortcode_and_type(self):
        reel = "https://www.instagram.com/reel/SECOND/"
        for destination, valid in (
            ("https://instagram.com/reels/SECOND/?x=1#video", True),
            ("https://www.instagram.com/second/reel/SECOND/", True),
            ("https://www.instagram.com/reels/OTHER/", False),
            ("https://www.instagram.com/p/SECOND/", False),
        ):
            with self.subTest(destination=destination):
                self.browser._redirects = {reel: destination}
                self.browser._pages[destination] = {"caption": "reel"}
                if valid:
                    row, = self.collector.collect_account("second")
                    self.assertEqual((row.external_id, row.content_type, row.canonical_url),
                                     ("SECOND", "REEL", reel))
                else:
                    with self.assertRaises(InstagramDestinationError):
                        self.collector.collect_account("second")

    def test_blocks_redirects_on_profiles_and_posts(self):
        for destination in ("accounts/login/", "challenge/", "checkpoint/"):
            for location in (self.profile, self.post):
                with self.subTest(destination=destination, location=location):
                    self.browser._redirects = {
                        location: "https://www.instagram.com/" + destination,
                    }
                    self.browser.visited.clear()
                    with self.assertRaisesRegex(InstagramAccessBlockedError, "first"):
                        self.collector.collect_account("first")
                    self.assertEqual(self.browser.visited, [self.profile] + (
                        [self.post] if location == self.post else []
                    ))
                    self.assertFalse(self.factory.sessions[0].shutdown_called)

    def test_post_login_form_blocks_observation(self):
        self.browser._pages[self.post]["login_wall"] = True
        with self.assertRaises(InstagramAccessBlockedError):
            self.collector.collect_account("first")

    def test_navigation_errors_propagate_without_retry_or_stale_rows(self):
        original_open = self.browser.open
        for location in (self.profile, self.post):
            for error_type in (RuntimeError, TimeoutError):
                with self.subTest(location=location, error_type=error_type):
                    error = error_type("navigation failed")

                    def failing_open(url):
                        if url == location:
                            raise error
                        return original_open(url)

                    with patch.object(self.browser, "open", side_effect=failing_open) as opened:
                        with self.assertRaises(error_type) as caught:
                            self.collector.collect_account("first")
                        self.assertIs(caught.exception, error)
                        self.assertEqual(opened.call_count, 1 if location == self.profile else 2)
                    self.assertFalse(self.factory.sessions[0].shutdown_called)
                    rows = self.collector.collect_account("second")
                    self.assertEqual([(r.source_account, r.external_id) for r in rows],
                                     [("second", "SECOND")])

    def test_dom_lookup_errors_are_not_empty_or_valid_observations(self):
        original_find = self.browser.find_elements
        for failing_selector in (LOGIN_FORM_SELECTOR, POST_LINK_SELECTOR, CAPTION_META_SELECTOR):
            with self.subTest(selector=failing_selector):
                error = RuntimeError("DOM disconnected")

                def failing_find(selector):
                    if selector == failing_selector:
                        raise error
                    return original_find(selector)

                with patch.object(self.browser, "find_elements", side_effect=failing_find):
                    with self.assertRaises(RuntimeError) as caught:
                        self.collector.collect_account("first")
                    self.assertIs(caught.exception, error)

    def test_evaluation_errors_propagate_for_location_and_publication(self):
        for location_lookup in (False, True):
            for error_type in (RuntimeError, TimeoutError):
                with self.subTest(location_lookup=location_lookup, error_type=error_type):
                    error = error_type("evaluation failed")
                    original_open = self.browser.open

                    def opened(url):
                        original_open(url)
                        if location_lookup:
                            self.browser.url = None

                    with patch.object(self.browser, "open", side_effect=opened), patch.object(
                        self.browser, "evaluate", side_effect=error,
                    ) as evaluate:
                        with self.assertRaises(error_type) as caught:
                            self.collector.collect_account("first")
                        self.assertIs(caught.exception, error)
                        evaluate.assert_called_once_with(
                            "window.location.href" if location_lookup else PUBLISHED_AT_SCRIPT
                        )

    def test_empty_and_sequential_accounts_have_no_shared_observations(self):
        first = self.collector.collect_account("first", limit=1)
        self.assertEqual(self.collector.collect_account("empty"), [])
        second = self.collector.collect_account("second", limit=1)
        self.assertEqual([(r.source_account, r.external_id, r.caption) for r in first + second],
                         [("first", "FIRST", "first"), ("second", "SECOND", "second")])
        self.assertNotEqual(first[0].collection_run_id, second[0].collection_run_id)
        self.assertEqual(len(self.factory.sessions), 1)

    def test_optional_selector_absence_can_be_legitimately_empty(self):
        collector, _ = _collector(FakeTimeoutRaisingInstagramBrowser(pages={self.profile: {}}))
        try:
            self.assertEqual(collector.collect_account("first"), [])
        finally:
            collector.shutdown()

    def test_batch_failure_discards_prior_accounts_and_leaves_cleanup_to_owner(self):
        config = InstagramCollectionConfig(source_code="IG_TEST", targets=tuple(
            InstagramCollectionTarget(account) for account in ("second", "first", "empty")
        ))
        ingestion = Mock()
        self.browser._redirects[self.post] = "https://www.instagram.com/challenge/"
        with self.assertRaises(InstagramAccessBlockedError):
            run_instagram_collection(collector=self.collector, config=config,
                                     ingestion_service=ingestion)
        ingestion.ingest.assert_not_called()
        self.assertNotIn("https://www.instagram.com/empty/", self.browser.visited)
        self.assertFalse(self.factory.sessions[0].shutdown_called)
        self.assertEqual(self.collector.shutdown(), "SHUTDOWN_OK")
        self.assertTrue(self.factory.sessions[0].shutdown_called)

    def test_start_failure_and_shutdown_are_delegated_to_same_session(self):
        session = Mock()
        error = RuntimeError("startup failed")
        session.start.side_effect = error
        factory = Mock(return_value=session)
        collector = InstagramBrowserCollector(browser_session_factory=factory,
                                              profile_resolver=Mock())
        with self.assertRaises(RuntimeError) as caught:
            collector.start()
        self.assertIs(caught.exception, error)
        self.assertIsNone(collector.browser)
        with self.assertRaisesRegex(RuntimeError, "no iniciado"):
            collector.collect_account("first")
        session.shutdown.assert_not_called()
        self.assertIs(collector.shutdown(), session.shutdown.return_value)
        session.shutdown.assert_called_once_with()
        factory.assert_called_once()


class InstagramCollectionConfigTest(unittest.TestCase):
    def test_account_normalization_is_used_in_navigation_and_observations(self):
        browser = FakeInstagramBrowser(pages={
            "https://www.instagram.com/example_account/": {
                "links": ["https://www.instagram.com/p/ABC123/"],
            },
            "https://www.instagram.com/p/ABC123/": {},
        })
        collector, _ = _collector(browser)
        target = InstagramCollectionTarget(account="  @example_account  ", limit=1)
        self.assertEqual(target.account, "example_account")
        observations = collector.collect_account(target.account, limit=target.limit)
        self.assertEqual(browser.visited[0], "https://www.instagram.com/example_account/")
        self.assertEqual(observations[0].source_account, "example_account")

    def test_empty_normalized_account_is_rejected(self):
        for account in ("", "   ", "@", None):
            with self.subTest(account=account), self.assertRaises(ValueError):
                InstagramCollectionTarget(account=account)

    def test_requires_explicit_targets(self):
        with self.assertRaises(ValueError):
            InstagramCollectionConfig(source_code="INSTAGRAM_TEST", targets=())

    def test_limit_must_be_positive(self):
        with self.assertRaises(ValueError):
            InstagramCollectionTarget(account="example", limit=0)


class RunInstagramCollectionTest(unittest.TestCase):
    def test_wires_collector_adapter_and_existing_ingestion_entrypoint(self):
        from pathlib import Path
        import tempfile

        from backend.repositories.sqlite_trend_intelligence_repository import (
            SQLiteTrendIntelligenceRepository,
        )
        from backend.trend_intelligence.service import TrendIntelligenceService

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)

        repository = SQLiteTrendIntelligenceRepository(
            Path(tmp.name) / "run_collection.db"
        )
        service = TrendIntelligenceService(repository=repository)
        service.ensure_schema()
        service.create_domain(code="MARKETING_TEST", name="Marketing Test")
        service.create_source(
            code="INSTAGRAM_TEST",
            name="Instagram Test",
            source_type="SOCIAL",
            collection_mode="SELENIUM",
        )

        ingestion_service = TrendIngestionService(service)

        pages = {
            "https://www.instagram.com/example_account/": {
                "links": ["https://www.instagram.com/p/ABC/"],
            },
            "https://www.instagram.com/p/ABC/": {
                "caption": "Hello #world",
                "published_at": "2026-10-10T00:00:00+00:00",
            },
        }
        browser = FakeInstagramBrowser(pages=pages)
        collector, _ = _collector(browser)

        config = InstagramCollectionConfig(
            source_code="INSTAGRAM_TEST",
            targets=(InstagramCollectionTarget(account="example_account", limit=3),),
        )

        report = run_instagram_collection(
            collector=collector,
            config=config,
            ingestion_service=ingestion_service,
            domain_code="MARKETING_TEST",
        )

        self.assertEqual(report.created, 1)

        second_report = run_instagram_collection(
            collector=collector,
            config=config,
            ingestion_service=ingestion_service,
            domain_code="MARKETING_TEST",
        )

        self.assertEqual(second_report.created, 0)
        self.assertEqual(second_report.duplicates, 1)


def test_stable_profile_across_worktrees_does_not_change_legacy(tmp_path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setattr(Path, "home", lambda: home)
    expected = home / ".quesada_browser_profiles" / DEFAULT_PROFILE_KEY
    results = []
    with patch.object(Path, "mkdir"):
        for checkout, cwd in (
            (tmp_path / "worktree-a", tmp_path),
            (tmp_path / "worktree-b", tmp_path.parent),
        ):
            # The temporary directory already exists; no profile directory is created.
            monkeypatch.chdir(cwd)
            monkeypatch.setattr(browser_profiles, "get_project_root", lambda: checkout)
            before = get_browser_profile_dir("mercurio")
            collector = InstagramBrowserCollector()
            results.append(collector._profile_resolver(collector.profile_key))
            assert get_browser_profile_dir("mercurio") == before
            for key in ("qcc_assisted", "whatsapp", "dehu"):
                assert get_browser_profile_dir(key) == checkout / "data" / "browser_profiles" / key
            assert before == checkout / "data" / "browser_profiles" / "mercurio"
    assert results == [expected, expected]
    assert not expected.exists()


def test_collector_passes_stable_profile_to_seleniumbase(tmp_path):
    import sys
    from types import SimpleNamespace

    chrome = Mock(return_value=FakeInstagramBrowser(pages={}))
    fake_seleniumbase = SimpleNamespace(sb_cdp=SimpleNamespace(Chrome=chrome))
    with patch.dict(sys.modules, {"seleniumbase": fake_seleniumbase}), patch.object(
        Path, "home", return_value=tmp_path,
    ), patch.object(Path, "mkdir") as mkdir:
        collector = InstagramBrowserCollector()
        assert collector._browser_session_factory is SeleniumBaseBrowserSession
        mkdir.assert_not_called()
        collector.start()
    expected = tmp_path / ".quesada_browser_profiles" / DEFAULT_PROFILE_KEY
    chrome.assert_called_once_with(headless=True, user_data_dir=str(expected.resolve()))
    mkdir.assert_called_once_with(parents=True, exist_ok=True)
    assert not expected.exists()


def test_injected_single_argument_resolver_is_preserved():
    browser = FakeInstagramBrowser(pages={})
    resolver = Mock(return_value=Path("fake-profiles") / "custom_key")
    browser_factory = Mock(return_value=browser)

    def session_factory(**kwargs):
        return SeleniumBaseBrowserSession(browser_factory=browser_factory, **kwargs)

    with patch.object(Path, "home", side_effect=AssertionError("Unexpected home lookup")):
        collector = InstagramBrowserCollector(
            profile_key="custom_key",
            profile_resolver=resolver,
            browser_session_factory=session_factory,
        )
        assert collector.start() is browser
    resolver.assert_called_once_with("custom_key")
    browser_factory.assert_called_once_with(headless=True, user_data_dir=resolver.return_value)


if __name__ == "__main__":
    unittest.main()
