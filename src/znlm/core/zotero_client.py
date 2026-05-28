import asyncio
from datetime import datetime
from pathlib import Path
from typing import Optional

import requests
from loguru import logger
from pyzotero import zotero

from znlm.config import Settings
from znlm.core.processor import ItemProcessor
from znlm.models import ZoteroItem

CACHE_DIR = Path.home() / ".znlm" / "cache"
MAX_RETRIES = 3


class ZoteroClient:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._zot = zotero.Zotero(
            settings.zotero_library_id,
            settings.zotero_library_type,
            settings.zotero_api_key,
        )
        self._processor = ItemProcessor()
        CACHE_DIR.mkdir(parents=True, exist_ok=True)

    async def get_collections(self) -> dict[str, str]:
        raw = await asyncio.to_thread(self._zot.everything, self._zot.collections())
        return {c["key"]: c["data"]["name"] for c in raw}

    async def get_items_since(
        self,
        since: Optional[datetime] = None,
    ) -> list[ZoteroItem]:
        collections_map = await self.get_collections()

        raw_items: list[dict] = await asyncio.to_thread(
            self._zot.everything, self._zot.top()
        )

        results: list[ZoteroItem] = []
        for raw in raw_items:
            item_type = raw.get("data", {}).get("itemType", "")
            if item_type in ("note", "attachment"):
                continue
            try:
                item = self._processor.process(raw, collections_map)
                if since is None or item.date_modified > since:
                    results.append(item)
            except Exception as exc:
                logger.warning(f"Skipping item {raw.get('key')}: {exc}")

        return results

    async def download_pdf(self, item: ZoteroItem) -> Optional[Path]:
        cache_path = CACHE_DIR / f"{item.item_key}.pdf"
        if cache_path.exists():
            logger.debug(f"Cache hit for {item.item_key}")
            return cache_path

        children: list[dict] = await asyncio.to_thread(
            self._zot.children, item.item_key
        )
        pdf_key: Optional[str] = None
        for child in children:
            if child.get("data", {}).get("contentType") == "application/pdf":
                pdf_key = child["key"]
                break

        if pdf_key is None:
            logger.debug(f"No PDF attachment for {item.item_key}")
            return None

        return await self._download_with_retry(item.item_key, pdf_key, cache_path)

    async def _download_with_retry(
        self,
        item_key: str,
        attachment_key: str,
        dest: Path,
    ) -> Optional[Path]:
        lib_type = self._settings.zotero_library_type
        lib_id = self._settings.zotero_library_id
        url = (
            f"https://api.zotero.org/{lib_type}s/{lib_id}"
            f"/items/{attachment_key}/file"
        )
        headers = {"Zotero-API-Key": self._settings.zotero_api_key}

        for attempt in range(MAX_RETRIES):
            try:
                response = await asyncio.to_thread(
                    requests.get, url, headers=headers, timeout=60
                )
                if response.status_code == 429:
                    wait = 0.5 * (2**attempt)
                    logger.warning(f"Rate limited; retrying in {wait}s")
                    await asyncio.sleep(wait)
                    continue
                response.raise_for_status()
                dest.write_bytes(response.content)
                logger.info(f"Downloaded PDF for {item_key} → {dest}")
                return dest
            except requests.RequestException as exc:
                wait = 0.5 * (2**attempt)
                logger.warning(
                    f"Attempt {attempt + 1} failed for {item_key}: {exc}; "
                    f"retrying in {wait}s"
                )
                if attempt < MAX_RETRIES - 1:
                    await asyncio.sleep(wait)

        logger.error(f"Failed to download PDF for {item_key} after {MAX_RETRIES} attempts")
        return None
