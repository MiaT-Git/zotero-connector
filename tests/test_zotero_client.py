from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from znlm.config import Settings
from znlm.core.zotero_client import CACHE_DIR, ZoteroClient
from znlm.models import ZoteroItem


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        zotero_api_key="test-key",
        zotero_library_id="12345",
        state_file_path=tmp_path / "state.json",
    )


def _make_item(**kwargs) -> ZoteroItem:
    defaults = dict(
        item_key="TEST001",
        title="Test Paper",
        authors=[],
        date_added=datetime(2024, 1, 1, tzinfo=timezone.utc),
        date_modified=datetime(2024, 1, 1, tzinfo=timezone.utc),
    )
    defaults.update(kwargs)
    return ZoteroItem(**defaults)


# ---------------------------------------------------------------------------
# get_collections
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_collections(settings):
    with patch("znlm.core.zotero_client.zotero.Zotero") as mock_cls:
        mock_zot = MagicMock()
        mock_cls.return_value = mock_zot
        mock_zot.everything.return_value = [
            {"key": "COL001", "data": {"name": "Machine Learning"}},
            {"key": "COL002", "data": {"name": "NLP"}},
        ]
        client = ZoteroClient(settings)
        result = await client.get_collections()

    assert result == {"COL001": "Machine Learning", "COL002": "NLP"}


# ---------------------------------------------------------------------------
# get_items_since
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_items_since_filters_notes(settings, raw_zotero_item):
    note = {
        "key": "NOTE1",
        "data": {
            "itemType": "note",
            "title": "My note",
            "creators": [],
            "date": "",
            "abstractNote": "",
            "DOI": "",
            "url": "",
            "tags": [],
            "collections": [],
            "dateAdded": "2024-01-01T00:00:00Z",
            "dateModified": "2024-01-01T00:00:00Z",
        },
    }
    with patch("znlm.core.zotero_client.zotero.Zotero") as mock_cls:
        mock_zot = MagicMock()
        mock_cls.return_value = mock_zot
        mock_zot.everything.return_value = [raw_zotero_item, note]

        client = ZoteroClient(settings)
        with patch.object(client, "get_collections", return_value={"COL001": "Machine Learning"}):
            items = await client.get_items_since()

    assert len(items) == 1
    assert items[0].item_key == "ABC123"


@pytest.mark.asyncio
async def test_items_without_collection_get_uncategorized(settings):
    raw = {
        "key": "NOCAT1",
        "data": {
            "itemType": "journalArticle",
            "title": "Uncategorized Paper",
            "creators": [],
            "date": "2023",
            "abstractNote": "",
            "DOI": "",
            "url": "",
            "tags": [],
            "collections": [],
            "dateAdded": "2024-01-01T00:00:00Z",
            "dateModified": "2024-01-15T00:00:00Z",
        },
    }
    with patch("znlm.core.zotero_client.zotero.Zotero") as mock_cls:
        mock_zot = MagicMock()
        mock_cls.return_value = mock_zot
        mock_zot.everything.return_value = [raw]

        client = ZoteroClient(settings)
        with patch.object(client, "get_collections", return_value={}):
            items = await client.get_items_since()

    assert items[0].collection_names == ["Uncategorized"]


@pytest.mark.asyncio
async def test_get_items_since_skips_malformed_items(settings):
    malformed = {"key": "BAD1", "data": {}}  # missing required fields
    with patch("znlm.core.zotero_client.zotero.Zotero") as mock_cls:
        mock_zot = MagicMock()
        mock_cls.return_value = mock_zot
        mock_zot.everything.return_value = [malformed]

        client = ZoteroClient(settings)
        with patch.object(client, "get_collections", return_value={}):
            items = await client.get_items_since()

    assert items == []


# ---------------------------------------------------------------------------
# _download_with_retry (rate-limit and success path)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_download_retries_on_rate_limit(settings, tmp_path):
    success_response = MagicMock(status_code=200, content=b"%PDF-1.4 fake")
    success_response.raise_for_status = MagicMock()
    rate_limited = MagicMock(status_code=429)

    dest = tmp_path / "retry_test.pdf"
    with (
        patch("znlm.core.zotero_client.zotero.Zotero"),
        patch("znlm.core.zotero_client.requests.get", side_effect=[rate_limited, success_response]),
        patch("asyncio.sleep"),  # skip real sleep
    ):
        client = ZoteroClient(settings)
        result = await client._download_with_retry("ITEM1", "ATT1", dest)

    assert result == dest
    assert dest.read_bytes() == b"%PDF-1.4 fake"


@pytest.mark.asyncio
async def test_download_returns_none_after_max_retries(settings, tmp_path):
    import requests as req

    dest = tmp_path / "fail_test.pdf"
    with (
        patch("znlm.core.zotero_client.zotero.Zotero"),
        patch(
            "znlm.core.zotero_client.requests.get",
            side_effect=req.ConnectionError("timeout"),
        ),
        patch("asyncio.sleep"),
    ):
        client = ZoteroClient(settings)
        result = await client._download_with_retry("ITEM1", "ATT1", dest)

    assert result is None


# ---------------------------------------------------------------------------
# download_pdf
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_download_pdf_returns_none_when_no_attachment(settings):
    with patch("znlm.core.zotero_client.zotero.Zotero") as mock_cls:
        mock_zot = MagicMock()
        mock_cls.return_value = mock_zot
        mock_zot.children.return_value = []

        client = ZoteroClient(settings)
        result = await client.download_pdf(_make_item())

    assert result is None


@pytest.mark.asyncio
async def test_download_pdf_uses_cache(settings):
    item = _make_item(item_key="CACHE_HIT_99")
    cache_path = CACHE_DIR / f"{item.item_key}.pdf"
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_bytes(b"%PDF-fake")

    try:
        with patch("znlm.core.zotero_client.zotero.Zotero") as mock_cls:
            mock_zot = MagicMock()
            mock_cls.return_value = mock_zot
            client = ZoteroClient(settings)
            result = await client.download_pdf(item)

        assert result == cache_path
        mock_zot.children.assert_not_called()
    finally:
        cache_path.unlink(missing_ok=True)
