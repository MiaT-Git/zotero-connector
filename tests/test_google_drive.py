import hashlib
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from znlm.config import Settings
from znlm.models import ZoteroItem
from znlm.providers.google_drive import GoogleDriveProvider


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        zotero_api_key="test",
        zotero_library_id="12345",
        google_credentials_path=tmp_path / "credentials.json",
    )


@pytest.fixture
def provider(settings) -> GoogleDriveProvider:
    p = GoogleDriveProvider(settings)
    p._service = MagicMock()
    p._root_folder_id = "root-folder-id"
    return p


@pytest.fixture
def item_with_pdf(sample_item, tmp_path) -> ZoteroItem:
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake content")
    return sample_item.model_copy(update={"pdf_path": pdf})


# ---------------------------------------------------------------------------
# Filename helpers
# ---------------------------------------------------------------------------

def test_build_filename_standard(provider, sample_item):
    # sample_item.authors[0] = "Ashish Vaswani", last name = "Vaswani"
    filename = provider._build_filename(sample_item)
    assert filename.startswith("Vaswani_et_al_2017_")
    assert filename.endswith(".pdf")


def test_build_filename_no_authors(provider, sample_item):
    item = sample_item.model_copy(update={"authors": [], "year": None})
    filename = provider._build_filename(item)
    assert filename.startswith("Unknown_undated_")


def test_build_filename_single_author(provider, sample_item):
    item = sample_item.model_copy(update={"authors": ["Jane Smith"]})
    filename = provider._build_filename(item)
    assert filename.startswith("Smith_2017_")
    assert "et_al" not in filename


def test_slugify_removes_special_chars(provider):
    assert provider._slugify("Hello, World! Test") == "hello_world_test"


def test_slugify_strips_edges(provider):
    assert provider._slugify("  Spaces  ") == "spaces"


def test_slugify_collapses_separators(provider):
    assert provider._slugify("multi  ---  space") == "multi_space"


# ---------------------------------------------------------------------------
# Folder management
# ---------------------------------------------------------------------------

def test_get_or_create_folder_creates_when_missing(provider):
    service = provider._service
    service.files().list().execute.return_value = {"files": []}
    service.files().create().execute.return_value = {"id": "new-folder-id"}

    folder_id = provider._get_or_create_folder(service, "MyFolder", "parent-id")
    assert folder_id == "new-folder-id"


def test_get_or_create_folder_returns_existing(provider):
    service = provider._service
    service.files().list().execute.return_value = {"files": [{"id": "existing-id"}]}

    folder_id = provider._get_or_create_folder(service, "MyFolder", "parent-id")
    assert folder_id == "existing-id"


def test_get_or_create_folder_caches_result(provider):
    service = provider._service
    # Configure return value without calling list() (avoids polluting call_count)
    service.files.return_value.list.return_value.execute.return_value = {
        "files": [{"id": "cached-id"}]
    }

    first_id = provider._get_or_create_folder(service, "CachedFolder", "parent-id")
    second_id = provider._get_or_create_folder(service, "CachedFolder", "parent-id")

    assert first_id == second_id == "cached-id"
    # list() called exactly once — second call hits the in-memory cache
    assert service.files.return_value.list.call_count == 1


# ---------------------------------------------------------------------------
# MD5 idempotency
# ---------------------------------------------------------------------------

def test_md5_matches_returns_true_when_identical(provider, tmp_path):
    content = b"test content"
    local = tmp_path / "test.pdf"
    local.write_bytes(content)
    md5 = hashlib.md5(content).hexdigest()
    provider._service.files().get().execute.return_value = {"md5Checksum": md5}

    assert provider._md5_matches(provider._service, "file-id", local) is True


def test_md5_matches_returns_false_when_different(provider, tmp_path):
    local = tmp_path / "test.pdf"
    local.write_bytes(b"different content")
    provider._service.files().get().execute.return_value = {"md5Checksum": "abc123"}

    assert provider._md5_matches(provider._service, "file-id", local) is False


# ---------------------------------------------------------------------------
# upload()
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_upload_skips_when_no_pdf(provider, sample_item):
    result = await provider.upload(sample_item)  # pdf_path is None
    assert result.success is True
    assert "No PDF" in (result.error or "")


@pytest.mark.asyncio
async def test_upload_returns_success(provider, item_with_pdf):
    with patch.object(provider, "_upload_sync", return_value="file-123"):
        result = await provider.upload(item_with_pdf)
    assert result.success is True
    assert result.drive_file_id == "file-123"


@pytest.mark.asyncio
async def test_upload_returns_failure_on_exception(provider, item_with_pdf):
    with patch.object(provider, "_upload_sync", side_effect=Exception("quota exceeded")):
        result = await provider.upload(item_with_pdf)
    assert result.success is False
    assert "quota exceeded" in (result.error or "")


# ---------------------------------------------------------------------------
# delete() / list_existing()
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_delete_returns_true_on_success(provider):
    provider._service.files().list().execute.return_value = {"files": [{"id": "f1"}]}
    result = await provider.delete("ABC123")
    assert result is True


@pytest.mark.asyncio
async def test_list_existing_returns_item_keys(provider):
    provider._service.files().list().execute.return_value = {
        "files": [
            {"appProperties": {"item_key": "ABC123"}},
            {"appProperties": {"item_key": "DEF456"}},
        ]
    }
    keys = await provider.list_existing()
    assert set(keys) == {"ABC123", "DEF456"}


# ---------------------------------------------------------------------------
# _upload_sync (internal — tests the actual upload logic paths)
# ---------------------------------------------------------------------------

def test_upload_sync_creates_new_file(provider, item_with_pdf):
    provider._service.files.return_value.create.return_value.execute.return_value = {
        "id": "new-file-id"
    }
    with (
        patch.object(provider, "_ensure_root_folder", return_value="root-id"),
        patch.object(provider, "_get_or_create_folder", return_value="folder-id"),
        patch.object(provider, "_find_existing", return_value=None),
    ):
        result = provider._upload_sync(item_with_pdf)
    assert result == "new-file-id"


def test_upload_sync_skips_unchanged_file(provider, item_with_pdf):
    with (
        patch.object(provider, "_ensure_root_folder", return_value="root-id"),
        patch.object(provider, "_get_or_create_folder", return_value="folder-id"),
        patch.object(provider, "_find_existing", return_value="existing-id"),
        patch.object(provider, "_md5_matches", return_value=True),
    ):
        result = provider._upload_sync(item_with_pdf)
    assert result == "existing-id"
    provider._service.files.return_value.create.assert_not_called()


def test_upload_sync_updates_changed_file(provider, item_with_pdf):
    provider._service.files.return_value.update.return_value.execute.return_value = {}
    with (
        patch.object(provider, "_ensure_root_folder", return_value="root-id"),
        patch.object(provider, "_get_or_create_folder", return_value="folder-id"),
        patch.object(provider, "_find_existing", return_value="existing-id"),
        patch.object(provider, "_md5_matches", return_value=False),
    ):
        result = provider._upload_sync(item_with_pdf)
    assert result == "existing-id"
    provider._service.files.return_value.update.assert_called_once()
