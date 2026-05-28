from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from znlm.config import Settings
from znlm.core.engine import SyncEngine
from znlm.models import SyncResult, SyncState


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        zotero_api_key="test",
        zotero_library_id="12345",
        state_file_path=tmp_path / "state" / "sync_state.json",
    )


@pytest.fixture
def engine(settings, mock_provider) -> SyncEngine:
    return SyncEngine(settings, [mock_provider])


# ---------------------------------------------------------------------------
# dry_run
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_sync_dry_run_returns_items_without_writing(engine, settings, sample_item):
    with patch.object(engine._zotero, "get_items_since", return_value=[sample_item]):
        results = await engine.sync(dry_run=True)

    assert len(results) == 1
    assert results[0].success is True
    # dry_run must not write state
    assert not settings.state_file_path.exists()


# ---------------------------------------------------------------------------
# state update rules
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_sync_updates_state_on_success(engine, settings, sample_item, mock_provider):
    mock_provider.upload = AsyncMock(
        return_value=SyncResult(item=sample_item, success=True)
    )
    with patch.object(engine._zotero, "get_items_since", return_value=[sample_item]):
        with patch.object(engine._zotero, "download_pdf", return_value=None):
            await engine.sync()

    state = engine.load_state()
    assert sample_item.item_key in state.synced_items
    assert state.last_sync is not None


@pytest.mark.asyncio
async def test_sync_does_not_update_item_on_failure(engine, settings, sample_item, mock_provider):
    mock_provider.upload = AsyncMock(
        return_value=SyncResult(item=sample_item, success=False, error="upload failed")
    )
    with patch.object(engine._zotero, "get_items_since", return_value=[sample_item]):
        with patch.object(engine._zotero, "download_pdf", return_value=None):
            await engine.sync()

    state = engine.load_state()
    assert sample_item.item_key not in state.synced_items


@pytest.mark.asyncio
async def test_sync_does_not_update_last_sync_on_partial_failure(
    engine, settings, sample_item, mock_provider
):
    mock_provider.upload = AsyncMock(
        return_value=SyncResult(item=sample_item, success=False, error="failed")
    )
    with patch.object(engine._zotero, "get_items_since", return_value=[sample_item]):
        with patch.object(engine._zotero, "download_pdf", return_value=None):
            await engine.sync()

    state = engine.load_state()
    assert state.last_sync is None


# ---------------------------------------------------------------------------
# collection filter
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_sync_collection_filter(engine, sample_item, mock_provider):
    mock_provider.upload = AsyncMock(
        return_value=SyncResult(item=sample_item, success=True)
    )
    other_item = sample_item.model_copy(
        update={"item_key": "XYZ999", "collection_names": ["Physics"]}
    )
    with patch.object(
        engine._zotero, "get_items_since", return_value=[sample_item, other_item]
    ):
        with patch.object(engine._zotero, "download_pdf", return_value=None):
            results = await engine.sync(collection_filter="Machine Learning")

    assert all(r.item.item_key == "ABC123" for r in results)


# ---------------------------------------------------------------------------
# state persistence
# ---------------------------------------------------------------------------

def test_load_state_returns_empty_when_missing(engine):
    state = engine.load_state()
    assert state.last_sync is None
    assert state.synced_items == {}


def test_save_and_load_roundtrip(engine):
    state = SyncState(
        last_sync=datetime(2024, 1, 15, tzinfo=timezone.utc),
        synced_items={"ABC123": datetime(2024, 1, 15, tzinfo=timezone.utc)},
    )
    engine.save_state(state)
    loaded = engine.load_state()

    assert loaded.last_sync == state.last_sync
    assert "ABC123" in loaded.synced_items


def test_save_state_is_atomic(engine, settings):
    """No .tmp file should remain after save."""
    engine.save_state(SyncState())
    assert not settings.state_file_path.with_suffix(".tmp").exists()
    assert settings.state_file_path.exists()


def test_load_state_recovers_from_corrupt_file(engine, settings):
    settings.state_file_path.parent.mkdir(parents=True, exist_ok=True)
    settings.state_file_path.write_text("not valid json", encoding="utf-8")
    state = engine.load_state()
    assert state.last_sync is None  # falls back to empty state
