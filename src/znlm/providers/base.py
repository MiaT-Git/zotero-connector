from abc import ABC, abstractmethod

from znlm.models import SyncResult, ZoteroItem


class BaseProvider(ABC):
    """
    Abstract interface for all sync providers.
    Adding a new connector: subclass this, implement the three methods,
    then register the instance in cli.py's _build_engine().
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Provider identifier e.g. 'google_drive'"""

    @abstractmethod
    async def upload(self, item: ZoteroItem) -> SyncResult:
        """
        Handle a new or updated item.
        Must be idempotent — safe to call multiple times for the same item.
        """

    @abstractmethod
    async def delete(self, item_key: str) -> bool:
        """Remove an item from this provider. Return True on success."""

    @abstractmethod
    async def list_existing(self) -> list[str]:
        """Return list of item_keys already handled by this provider."""
