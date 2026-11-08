"""Registered provenance and CRM rejection paths, using temporary SQLite only."""
import sqlite3
from unittest.mock import Mock, patch

import pytest

from scripts.tests.test_instagram_collector_configuration import (
    store, unregistered_store, save, settings,
)
from backend.repositories.sqlite_trend_intelligence_repository import (
    SQLiteTrendIntelligenceReadOnlyLookup, SQLiteTrendIntelligenceRepository,
)
from backend.services.instagram_collector_configuration_service import (
    InstagramCollectorConfigurationService,
)
from backend.services.instagram_collector_runtime_service import InstagramCollectorRuntimeService
from backend.trend_intelligence.models import COLLECTION_MODE_SELENIUM
from backend.trend_intelligence.service import TrendIntelligenceService


@pytest.mark.parametrize('provider,url,source_type,mode,active,accepted', [
    ('Instagram', None, 'SOCIAL', COLLECTION_MODE_SELENIUM, True, True),
    (' INSTAGRAM ', None, 'SOCIAL', COLLECTION_MODE_SELENIUM, True, True),
    (None, 'https://instagram.com/', 'SOCIAL', COLLECTION_MODE_SELENIUM, True, True),
    (None, 'https://WWW.INSTAGRAM.COM/', 'SOCIAL', COLLECTION_MODE_SELENIUM, True, True),
    ('Instagram', 'https://www.instagram.com/', 'SOCIAL', COLLECTION_MODE_SELENIUM, True, True),
    ('Facebook', 'https://instagram.com/', 'SOCIAL', COLLECTION_MODE_SELENIUM, True, False),
    ('Instagram API', None, 'SOCIAL', COLLECTION_MODE_SELENIUM, True, False),
    ('Instagram', None, 'WEB', COLLECTION_MODE_SELENIUM, True, False),
    ('Instagram', None, 'SOCIAL', 'API', True, False),
    ('Instagram', None, 'SOCIAL', 'MANUAL', True, False),
    ('Instagram', None, 'SOCIAL', COLLECTION_MODE_SELENIUM, False, False),
    (None, None, 'SOCIAL', COLLECTION_MODE_SELENIUM, True, False),
    ('', '', 'SOCIAL', COLLECTION_MODE_SELENIUM, True, False),
])
def test_registered_identity(store, provider, url, source_type, mode, active, accepted):
    path, repository = store
    TrendIntelligenceService(repository).create_source(
        code='INSTAGRAM_LOOKALIKE', name='Instagram', provider=provider,
        base_url=url, source_type=source_type, collection_mode=mode, is_active=active,
        configuration={'description': 'instagram', 'provider': 'instagram'},
    )
    save(path, settings(source_code='INSTAGRAM_LOOKALIKE'))
    assert_discovery(path, accepted)


@pytest.mark.parametrize('provider', [None, 'Instagram'])
@pytest.mark.parametrize('url', [
    'https://instagram.com.evil.example/', 'https://evilinstagram.com/',
    'https://instagram.com@evil.example/', 'https://evil.example/instagram.com',
    'https://evil.example/?host=instagram.com', 'https://instagrаm.com/',
    'https://instagram.com\\@evil.example/', 'https://instagram.com:bad/',
    'https://instagram.com:444/', 'https://user@instagram.com/',
    '//instagram.com/', 'ftp://instagram.com/', 'https://[instagram.com/',
    'https://insta\ngram.com/', 'https://instagram.com./',
])
def test_misleading_or_malformed_url(store, provider, url):
    path, _ = store
    with sqlite3.connect(path) as conn:
        conn.execute('UPDATE ti_sources SET provider = ?, base_url = ?', (provider, url))
    save(path, settings())
    assert_discovery(path, False)


def assert_discovery(path, accepted):
    before = path.read_bytes()
    files = set(path.parent.iterdir())
    service = InstagramCollectorConfigurationService(SQLiteTrendIntelligenceReadOnlyLookup(path))
    with patch.object(SQLiteTrendIntelligenceRepository, 'ensure_schema', side_effect=AssertionError):
        if accepted:
            assert service.load().status == 'IDLE'
        else:
            factory = Mock()
            runtime = InstagramCollectorRuntimeService(
                configuration_service=service, collector_factory=factory)
            try:
                runtime.start().result(5)
                assert runtime.snapshot.status == 'NOT_CONFIGURED'
                assert runtime.snapshot.error is not None
                factory.assert_not_called()
            finally:
                runtime.close().result(5)
    assert path.read_bytes() == before
    assert set(path.parent.iterdir()) == files
