import os
from datetime import datetime, timezone
from typing import Optional

from loguru import logger

from znlm.config import Settings
from znlm.core.zotero_client import ZoteroClient
from znlm.models import SyncResult, SyncState, ZoteroItem
from znlm.providers.base import BaseProvider


class SyncEngine:
    def __init__(self, settings: Settings, providers: list[BaseProvider]) -> None:
        self._settings = settings
        self._providers = providers
        self._zotero = ZoteroClient(settings)

    async def sync(
        self,
        collection_filter: Optional[str] = None,
        full: bool = False,
        dry_run: bool = False,
    ) -> list[SyncResult]:
        state = self.load_state()
        since = None if full else state.last_sync

        logger.info(f"Fetching items since {since or 'beginning'}")
        items = await self._zotero.get_items_since(since)

        if collection_filter:
            items = [i for i in items if collection_filter in i.collection_names]
            logger.info(f"Filtered to {len(items)} items in collection '{collection_filter}'")

        if dry_run:
            logger.info(f"[dry-run] Would process {len(items)} items")
            return [SyncResult(item=item, success=True) for item in items]

        results: list[SyncResult] = []
        sync_time = datetime.now(timezone.utc)
        all_succeeded = True

        for item in items:
            item = await self._download_pdf_for_item(item)
            item_results = await self._run_providers(item)
            results.extend(item_results)

            if all(r.success for r in item_results):
                state.synced_items[item.item_key] = sync_time
            else:
                all_succeeded = False

        if all_succeeded and items:
            state.last_sync = sync_time

        self.save_state(state)
        return results

    async def _download_pdf_for_item(self, item: ZoteroItem) -> ZoteroItem:
        try:
            pdf_path = await self._zotero.download_pdf(item)
            return item.model_copy(update={"pdf_path": pdf_path})
        except Exception as exc:
            logger.warning(f"PDF download failed for {item.item_key}: {exc}")
            return item

    async def _run_providers(self, item: ZoteroItem) -> list[SyncResult]:
        results: list[SyncResult] = []
        for provider in self._providers:
            try:
                result = await provider.upload(item)
                results.append(result)
            except Exception as exc:
                logger.error(f"Provider '{provider.name}' failed for {item.item_key}: {exc}")
                results.append(SyncResult(item=item, success=False, error=str(exc)))
        return results

    # ------------------------------------------------------------------
    # State management
    # ------------------------------------------------------------------

    def load_state(self) -> SyncState:
        path = self._settings.state_file_path
        if path.exists():
            try:
                return SyncState.model_validate_json(path.read_text(encoding="utf-8"))
            except Exception as exc:
                logger.warning(f"Could not parse state file ({exc}); starting fresh")
        return SyncState()

    def save_state(self, state: SyncState) -> None:
        path = self._settings.state_file_path
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_suffix(".tmp")
        tmp_path.write_text(state.model_dump_json(indent=2), encoding="utf-8")
        os.replace(tmp_path, path)  # atomic on all platforms
