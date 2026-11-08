"""Bind existing CRM settings to a single Instagram ingestion run."""
from dataclasses import dataclass
import json
import re
from typing import Protocol
from urllib.parse import urlsplit

from backend.automation.browser_profiles import normalize_browser_profile_key
from backend.trend_intelligence.models import (
    TrendSource, TrendDomain, COLLECTION_MODE_SELENIUM,
)
from backend.trend_intelligence.sources.instagram_browser import (
    InstagramCollectionConfig, InstagramCollectionTarget,
)

SETTINGS_KEY = "IT_INSTAGRAM_COLLECTOR_V1"


class CollectorConfigurationLookup(Protocol):
    """Read existing settings and registrations without creating storage/schema."""

    def get_config(self, key: str, default=None): ...
    def get_source_by_code(self, code: str) -> TrendSource | None: ...
    def get_domain_by_code(self, code: str) -> TrendDomain | None: ...


class InvalidInstagramConfiguration(ValueError):
    pass


def _validate_instagram_source(source: TrendSource):
    """Trust registered identity only; conflicting metadata fails closed.

    SOCIAL is the existing registry source type (there is no type enum).
    Provider is free text in that registry, so only the exact normalized
    Instagram provider is accepted. URL fallback uses canonical web hosts.
    """
    if source.source_type != "SOCIAL":
        raise ValueError("Instagram source must have source_type SOCIAL")
    if source.collection_mode != COLLECTION_MODE_SELENIUM:
        raise ValueError("Instagram source must have collection_mode SELENIUM")
    provider = source.provider
    if provider is not None:
        if not isinstance(provider, str):
            raise ValueError("invalid registered Instagram provider")
        provider = provider.strip().casefold()
        if provider and provider != "instagram":
            raise ValueError("registered provider is not Instagram")
    url = source.base_url
    if url is not None and url != "":
        if not isinstance(url, str) or any(c.isspace() for c in url) or "\\" in url:
            raise ValueError("invalid registered Instagram base_url")
        parsed = urlsplit(url)
        if (parsed.scheme not in {"https", "http"}
                or parsed.hostname not in {"instagram.com", "www.instagram.com"}
                or parsed.username is not None or parsed.password is not None
                or parsed.port not in {None, 443 if parsed.scheme == "https" else 80}):
            raise ValueError("registered base_url is not a canonical Instagram URL")
    elif not provider:
        raise ValueError("registered source lacks Instagram identity metadata")


@dataclass(frozen=True)
class InstagramStartupConfiguration:
    status: str
    config: InstagramCollectionConfig | None = None
    domain_code: str | None = None


class InstagramCollectorConfigurationService:
    def __init__(self, lookup: CollectorConfigurationLookup):
        self.lookup = lookup

    def load(self):
        raw = self.lookup.get_config(SETTINGS_KEY)
        if raw is None:
            return InstagramStartupConfiguration("NOT_CONFIGURED")
        try:
            settings = json.loads(raw)
            if not isinstance(settings, dict):
                raise ValueError("settings must be an object")
            enabled = settings.get("enabled", False)
            if type(enabled) is not bool:
                raise ValueError("enabled must be boolean")
            if not enabled:
                return InstagramStartupConfiguration("DISABLED")
            source = settings.get("source_code")
            if not isinstance(source, str) or not source.strip():
                raise ValueError("source_code required")
            registered = self.lookup.get_source_by_code(source)
            if registered is None or not registered.is_active:
                raise ValueError("source_code must identify an active registered source")
            _validate_instagram_source(registered)
            domain = settings.get("domain_code")
            if domain is not None:
                if not isinstance(domain, str) or not domain.strip():
                    raise ValueError("domain_code must be a code or null")
                registered_domain = self.lookup.get_domain_by_code(domain)
                if registered_domain is None or not registered_domain.is_active:
                    raise ValueError("domain_code must identify an active domain")
            profile = settings.get("profile_key")
            if not isinstance(profile, str) or normalize_browser_profile_key(profile) != profile:
                raise ValueError("profile_key must be a governed profile key")
            headless = settings.get("headless")
            if type(headless) is not bool:
                raise ValueError("headless must be boolean")
            accounts = settings.get("accounts")
            if not isinstance(accounts, list) or not accounts:
                raise ValueError("accounts required")
            targets = []
            for target in accounts:
                if not isinstance(target, dict):
                    raise ValueError("account must be an object")
                account, limit = target.get("account"), target.get("limit")
                if not isinstance(account, str) or not re.fullmatch(r"[A-Za-z0-9_.]{1,30}", account):
                    raise ValueError("invalid account")
                if type(limit) is not int or limit <= 0:
                    raise ValueError("limit must be a positive integer")
                targets.append(InstagramCollectionTarget(account, limit))
            config = InstagramCollectionConfig(source, tuple(targets), profile, headless)
            return InstagramStartupConfiguration("IDLE", config, domain)
        except (ValueError, TypeError) as exc:
            raise InvalidInstagramConfiguration(str(exc)) from exc


def create_crm_instagram_runtime():
    """Compose lazily: constructors perform no reads or browser operations."""
    from backend.repositories.sqlite_trend_intelligence_repository import (
        SQLiteTrendIntelligenceRepository, SQLiteTrendIntelligenceReadOnlyLookup,
    )
    from backend.services.config_service import DB_PATH
    from backend.services.instagram_collector_runtime_service import InstagramCollectorRuntimeService
    from backend.trend_intelligence.ingestion import TrendIngestionService
    from backend.trend_intelligence.service import TrendIntelligenceService

    return InstagramCollectorRuntimeService(
        configuration_service=InstagramCollectorConfigurationService(
            SQLiteTrendIntelligenceReadOnlyLookup(DB_PATH),
        ),
        ingestion_service=TrendIngestionService(
            TrendIntelligenceService(SQLiteTrendIntelligenceRepository(DB_PATH)),
        ),
    )
