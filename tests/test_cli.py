from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from typer.testing import CliRunner

from znlm.cli import app
from znlm.models import SyncResult, SyncState

runner = CliRunner()


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------

def test_status_shows_never_when_no_sync(sample_item):
    with patch("znlm.cli.get_settings"), patch("znlm.cli._build_engine") as mock_engine:
        mock_engine.return_value.load_state.return_value = SyncState()
        result = runner.invoke(app, ["status"])
    assert result.exit_code == 0
    assert "never" in result.output


def test_status_shows_last_sync_when_set(sample_item):
    from datetime import datetime, timezone

    with patch("znlm.cli.get_settings"), patch("znlm.cli._build_engine") as mock_engine:
        mock_engine.return_value.load_state.return_value = SyncState(
            last_sync=datetime(2024, 1, 15, tzinfo=timezone.utc),
            synced_items={"ABC123": datetime(2024, 1, 15, tzinfo=timezone.utc)},
        )
        result = runner.invoke(app, ["status"])
    assert result.exit_code == 0
    assert "2024" in result.output


# ---------------------------------------------------------------------------
# sync
# ---------------------------------------------------------------------------

def test_sync_command_success(sample_item):
    with patch("znlm.cli.get_settings"), patch("znlm.cli._build_engine") as mock_engine:
        mock_engine.return_value.sync = AsyncMock(
            return_value=[SyncResult(item=sample_item, success=True)]
        )
        result = runner.invoke(app, ["sync"])
    assert result.exit_code == 0
    assert "1" in result.output


def test_sync_command_reports_failures(sample_item):
    with patch("znlm.cli.get_settings"), patch("znlm.cli._build_engine") as mock_engine:
        mock_engine.return_value.sync = AsyncMock(
            return_value=[
                SyncResult(item=sample_item, success=False, error="quota exceeded")
            ]
        )
        result = runner.invoke(app, ["sync"])
    assert result.exit_code == 0
    assert "quota exceeded" in result.output


def test_sync_dry_run_shows_preview(sample_item):
    with patch("znlm.cli.get_settings"), patch("znlm.cli._build_engine") as mock_engine:
        mock_engine.return_value.sync = AsyncMock(
            return_value=[SyncResult(item=sample_item, success=True)]
        )
        result = runner.invoke(app, ["sync", "--dry-run"])
    assert result.exit_code == 0
    assert "items would be processed" in result.output


def test_sync_command_passes_collection_filter(sample_item):
    with patch("znlm.cli.get_settings"), patch("znlm.cli._build_engine") as mock_engine:
        mock_engine.return_value.sync = AsyncMock(return_value=[])
        runner.invoke(app, ["sync", "--collection", "Machine Learning"])
        mock_engine.return_value.sync.assert_called_once_with(
            collection_filter="Machine Learning", full=False, dry_run=False
        )


def test_sync_command_passes_full_flag(sample_item):
    with patch("znlm.cli.get_settings"), patch("znlm.cli._build_engine") as mock_engine:
        mock_engine.return_value.sync = AsyncMock(return_value=[])
        runner.invoke(app, ["sync", "--full"])
        mock_engine.return_value.sync.assert_called_once_with(
            collection_filter=None, full=True, dry_run=False
        )


# ---------------------------------------------------------------------------
# list-collections
# ---------------------------------------------------------------------------

def test_list_collections_command():
    with patch("znlm.cli.get_settings"), patch("znlm.cli.ZoteroClient") as mock_client:
        mock_client.return_value.get_collections = AsyncMock(
            return_value={"COL001": "Machine Learning", "COL002": "NLP"}
        )
        result = runner.invoke(app, ["list-collections"])
    assert result.exit_code == 0
    assert "Machine Learning" in result.output
    assert "NLP" in result.output


# ---------------------------------------------------------------------------
# auth
# ---------------------------------------------------------------------------

def test_auth_command_success():
    with patch("znlm.cli.get_settings"), patch("znlm.cli.GoogleDriveProvider") as mock_prov:
        mock_prov.return_value._get_service.return_value = MagicMock()
        result = runner.invoke(app, ["auth"])
    assert result.exit_code == 0
    assert "successful" in result.output


def test_auth_command_failure():
    with patch("znlm.cli.get_settings"), patch("znlm.cli.GoogleDriveProvider") as mock_prov:
        mock_prov.return_value._get_service.side_effect = Exception("OAuth failed")
        result = runner.invoke(app, ["auth"])
    assert result.exit_code == 1
    assert "failed" in result.output.lower()
