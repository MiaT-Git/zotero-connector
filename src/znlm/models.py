from datetime import datetime
from pathlib import Path
from typing import Optional

from pydantic import BaseModel


class ZoteroItem(BaseModel):
    item_key: str
    title: str
    authors: list[str] = []
    year: Optional[int] = None
    abstract: Optional[str] = None
    doi: Optional[str] = None
    url: Optional[str] = None
    tags: list[str] = []
    collections: list[str] = []         # collection keys
    collection_names: list[str] = []    # human-readable names
    pdf_path: Optional[Path] = None     # local cached PDF path
    date_added: datetime
    date_modified: datetime


class SyncState(BaseModel):
    last_sync: Optional[datetime] = None
    synced_items: dict[str, datetime] = {}  # item_key → last synced


class SyncResult(BaseModel):
    item: ZoteroItem
    drive_file_id: Optional[str] = None
    success: bool
    error: Optional[str] = None
