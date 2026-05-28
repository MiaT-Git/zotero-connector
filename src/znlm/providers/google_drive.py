import asyncio
import hashlib
import re
from pathlib import Path
from typing import Optional

from loguru import logger

from znlm.config import Settings
from znlm.models import SyncResult, ZoteroItem
from znlm.providers.base import BaseProvider

TOKEN_PATH = Path.home() / ".znlm" / "google_token.json"
SCOPES = ["https://www.googleapis.com/auth/drive.file"]


class GoogleDriveProvider(BaseProvider):
    name = "google_drive"

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._service = None
        self._root_folder_id: Optional[str] = None
        self._folder_cache: dict[str, str] = {}  # "{parent_id}/{name}" → folder_id

    # ------------------------------------------------------------------
    # BaseProvider interface
    # ------------------------------------------------------------------

    async def upload(self, item: ZoteroItem) -> SyncResult:
        if item.pdf_path is None:
            logger.warning(f"No PDF for {item.item_key} — syncing metadata only")
            return SyncResult(item=item, success=True, error="No PDF available")
        try:
            file_id = await asyncio.to_thread(self._upload_sync, item)
            return SyncResult(item=item, drive_file_id=file_id, success=True)
        except Exception as exc:
            logger.error(f"Drive upload failed for {item.item_key}: {exc}")
            return SyncResult(item=item, success=False, error=str(exc))

    async def delete(self, item_key: str) -> bool:
        try:
            return await asyncio.to_thread(self._delete_sync, item_key)
        except Exception as exc:
            logger.error(f"Delete failed for {item_key}: {exc}")
            return False

    async def list_existing(self) -> list[str]:
        return await asyncio.to_thread(self._list_existing_sync)

    # ------------------------------------------------------------------
    # Sync internals (run via asyncio.to_thread)
    # ------------------------------------------------------------------

    def _upload_sync(self, item: ZoteroItem) -> str:
        from googleapiclient.http import MediaFileUpload

        service = self._get_service()
        root_id = self._ensure_root_folder(service)
        filename = self._build_filename(item)
        file_ids: list[str] = []

        for collection_name in item.collection_names:
            folder_id = self._get_or_create_folder(service, collection_name, root_id)
            existing_id = self._find_existing(service, item.item_key, folder_id)

            if existing_id:
                if self._md5_matches(service, existing_id, item.pdf_path):
                    logger.info(f"Skipping {item.item_key} in '{collection_name}' (unchanged)")
                    file_ids.append(existing_id)
                    continue
                # Content changed — update in place
                media = MediaFileUpload(str(item.pdf_path), mimetype="application/pdf")
                service.files().update(fileId=existing_id, media_body=media).execute()
                logger.info(f"Updated {item.item_key} in '{collection_name}'")
                file_ids.append(existing_id)
            else:
                file_metadata = {
                    "name": filename,
                    "parents": [folder_id],
                    "appProperties": {"item_key": item.item_key},
                }
                media = MediaFileUpload(str(item.pdf_path), mimetype="application/pdf")
                f = (
                    service.files()
                    .create(body=file_metadata, media_body=media, fields="id")
                    .execute()
                )
                logger.info(f"Uploaded {item.item_key} to '{collection_name}'")
                file_ids.append(f["id"])

        return file_ids[0] if file_ids else ""

    def _delete_sync(self, item_key: str) -> bool:
        service = self._get_service()
        query = (
            f"appProperties has {{ key='item_key' and value='{item_key}' }}"
            " and trashed=false"
        )
        results = service.files().list(q=query, fields="files(id)").execute()
        for f in results.get("files", []):
            service.files().delete(fileId=f["id"]).execute()
        return True

    def _list_existing_sync(self) -> list[str]:
        service = self._get_service()
        query = "appProperties has { key='item_key' } and trashed=false"
        results = (
            service.files()
            .list(q=query, fields="files(appProperties)")
            .execute()
        )
        return [
            f["appProperties"]["item_key"]
            for f in results.get("files", [])
            if "item_key" in f.get("appProperties", {})
        ]

    # ------------------------------------------------------------------
    # Folder management
    # ------------------------------------------------------------------

    def _ensure_root_folder(self, service) -> str:
        if self._root_folder_id:
            return self._root_folder_id
        self._root_folder_id = self._get_or_create_folder(
            service, self._settings.google_drive_root_folder, "root"
        )
        return self._root_folder_id

    def _get_or_create_folder(self, service, name: str, parent_id: str) -> str:
        cache_key = f"{parent_id}/{name}"
        if cache_key in self._folder_cache:
            return self._folder_cache[cache_key]

        safe_name = name.replace("'", "\\'")
        query = (
            f"name='{safe_name}' and "
            "mimeType='application/vnd.google-apps.folder' and "
            f"'{parent_id}' in parents and trashed=false"
        )
        results = service.files().list(q=query, fields="files(id)").execute()
        files = results.get("files", [])

        if files:
            folder_id = files[0]["id"]
        else:
            metadata = {
                "name": name,
                "mimeType": "application/vnd.google-apps.folder",
                "parents": [parent_id],
            }
            folder = service.files().create(body=metadata, fields="id").execute()
            folder_id = folder["id"]

        self._folder_cache[cache_key] = folder_id
        return folder_id

    def _find_existing(
        self, service, item_key: str, folder_id: str
    ) -> Optional[str]:
        safe_key = item_key.replace("'", "\\'")
        query = (
            f"appProperties has {{ key='item_key' and value='{safe_key}' }} and "
            f"'{folder_id}' in parents and trashed=false"
        )
        results = service.files().list(q=query, fields="files(id)").execute()
        files = results.get("files", [])
        return files[0]["id"] if files else None

    def _md5_matches(self, service, file_id: str, local_path: Path) -> bool:
        remote = service.files().get(fileId=file_id, fields="md5Checksum").execute()
        remote_md5 = remote.get("md5Checksum", "")
        local_md5 = hashlib.md5(local_path.read_bytes()).hexdigest()
        return remote_md5 == local_md5

    # ------------------------------------------------------------------
    # Filename helpers
    # ------------------------------------------------------------------

    def _build_filename(self, item: ZoteroItem) -> str:
        if item.authors:
            last_name = item.authors[0].split()[-1]
            if len(item.authors) > 1:
                last_name += "_et_al"
        else:
            last_name = "Unknown"
        year = str(item.year) if item.year else "undated"
        slug = self._slugify(item.title)[:60]
        raw = f"{last_name}_{year}_{slug}.pdf"
        # Keep only safe filename characters
        return re.sub(r"[^\w\-.]", "_", raw)

    def _slugify(self, text: str) -> str:
        text = text.lower()
        text = re.sub(r"[^\w\s-]", "", text)
        text = re.sub(r"[\s_-]+", "_", text)
        return text.strip("_")

    # ------------------------------------------------------------------
    # Auth
    # ------------------------------------------------------------------

    def _get_service(self):
        if self._service is None:
            self._service = self._authenticate()
        return self._service

    def _authenticate(self):
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build

        TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
        creds = None

        if TOKEN_PATH.exists():
            creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(
                    str(self._settings.google_credentials_path), SCOPES
                )
                creds = flow.run_local_server(port=0)
            TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")

        return build("drive", "v3", credentials=creds)
