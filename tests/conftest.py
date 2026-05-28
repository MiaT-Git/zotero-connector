from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from znlm.models import SyncResult, ZoteroItem


@pytest.fixture
def sample_item() -> ZoteroItem:
    return ZoteroItem(
        item_key="ABC123",
        title="Attention Is All You Need",
        authors=["Ashish Vaswani", "Noam Shazeer"],
        year=2017,
        abstract="The dominant sequence transduction models...",
        doi="10.48550/arXiv.1706.03762",
        url=None,
        tags=["deep learning", "transformers"],
        collections=["COL001"],
        collection_names=["Machine Learning"],
        pdf_path=None,
        date_added=datetime(2024, 1, 1, tzinfo=timezone.utc),
        date_modified=datetime(2024, 1, 15, tzinfo=timezone.utc),
    )


@pytest.fixture
def mock_provider(sample_item) -> AsyncMock:
    provider = AsyncMock()
    provider.name = "mock_provider"
    provider.upload.return_value = SyncResult(
        item=sample_item, success=True, drive_file_id="mock-file-id"
    )
    provider.delete.return_value = True
    provider.list_existing.return_value = []
    return provider


@pytest.fixture
def raw_zotero_item() -> dict:
    return {
        "key": "ABC123",
        "data": {
            "itemType": "journalArticle",
            "title": "Attention Is All You Need",
            "creators": [
                {"creatorType": "author", "firstName": "Ashish", "lastName": "Vaswani"},
                {"creatorType": "author", "firstName": "Noam", "lastName": "Shazeer"},
            ],
            "date": "2017",
            "abstractNote": "The dominant sequence transduction models...",
            "DOI": "10.48550/arXiv.1706.03762",
            "url": "",
            "tags": [{"tag": "deep learning"}, {"tag": "transformers"}],
            "collections": ["COL001"],
            "dateAdded": "2024-01-01T00:00:00Z",
            "dateModified": "2024-01-15T00:00:00Z",
        },
    }
