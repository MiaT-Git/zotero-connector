from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # Zotero
    zotero_api_key: str
    zotero_library_id: str
    zotero_library_type: str = "user"

    # Google Drive
    google_credentials_path: Path = Path("credentials.json")
    google_drive_root_folder: str = "Zotero-Connector"

    # Sync
    sync_interval_minutes: int = 30
    state_file_path: Path = Path("state/sync_state.json")
    log_level: str = "INFO"


def get_settings() -> Settings:
    return Settings()
