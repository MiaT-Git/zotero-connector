from __future__ import annotations

import asyncio
from typing import Optional

import typer
from loguru import logger
from rich.console import Console
from rich.table import Table

from znlm.config import get_settings
from znlm.core.engine import SyncEngine
from znlm.core.zotero_client import ZoteroClient
from znlm.providers.google_drive import GoogleDriveProvider

app = typer.Typer(help="Zotero → Google Drive connector for NotebookLM")
console = Console()


def _build_engine(settings) -> SyncEngine:
    providers = [GoogleDriveProvider(settings)]
    return SyncEngine(settings, providers)


@app.command()
def sync(
    collection: Optional[str] = typer.Option(None, help="Sync specific collection only"),
    full: bool = typer.Option(False, "--full", help="Force full sync, ignoring saved state"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview items without writing"),
) -> None:
    """Run a one-time sync of new/modified Zotero items to Google Drive."""
    settings = get_settings()
    engine = _build_engine(settings)

    results = asyncio.run(
        engine.sync(collection_filter=collection, full=full, dry_run=dry_run)
    )

    ok = sum(1 for r in results if r.success)
    fail = sum(1 for r in results if not r.success)

    if dry_run:
        console.print(f"[blue]dry-run:[/blue] {len(results)} items would be processed")
        for r in results:
            console.print(f"  {r.item.item_key}  {r.item.title[:60]}")
    else:
        console.print(f"[green]✓ {ok} succeeded[/green]  [red]✗ {fail} failed[/red]")
        for r in results:
            if not r.success:
                console.print(f"  [red]FAILED[/red] {r.item.item_key}: {r.error}")


@app.command()
def watch(
    interval: int = typer.Option(30, help="Poll interval in minutes"),
) -> None:
    """Continuously watch for new Zotero items and sync them."""
    settings = get_settings()
    engine = _build_engine(settings)

    async def _loop() -> None:
        console.print(
            f"[blue]Watching — polling every {interval} minute(s). Ctrl+C to stop.[/blue]"
        )
        while True:
            console.print("[dim]Running sync...[/dim]")
            try:
                results = await engine.sync()
                ok = sum(1 for r in results if r.success)
                fail = sum(1 for r in results if not r.success)
                console.print(
                    f"[green]✓ {ok} synced[/green]  [red]✗ {fail} failed[/red]"
                )
            except Exception as exc:
                logger.error(f"Sync error: {exc}")
            await asyncio.sleep(interval * 60)

    try:
        asyncio.run(_loop())
    except KeyboardInterrupt:
        console.print("\n[yellow]Watch stopped.[/yellow]")


@app.command("list-collections")
def list_collections() -> None:
    """List all Zotero collections."""
    settings = get_settings()
    client = ZoteroClient(settings)
    collections = asyncio.run(client.get_collections())

    table = Table(title="Zotero Collections")
    table.add_column("Key", style="dim")
    table.add_column("Name")
    for key, name in sorted(collections.items(), key=lambda x: x[1].lower()):
        table.add_row(key, name)
    console.print(table)


@app.command()
def status() -> None:
    """Show last sync time and tracked item count."""
    settings = get_settings()
    engine = _build_engine(settings)
    state = engine.load_state()

    console.print(f"Last sync:      [bold]{state.last_sync or 'never'}[/bold]")
    console.print(f"Tracked items:  [bold]{len(state.synced_items)}[/bold]")
    console.print(f"State file:     [dim]{settings.state_file_path}[/dim]")


@app.command()
def auth() -> None:
    """Run the Google OAuth flow and cache credentials."""
    settings = get_settings()
    provider = GoogleDriveProvider(settings)
    console.print("[blue]Starting Google OAuth flow...[/blue]")
    try:
        provider._get_service()
        console.print("[green]✓ Authentication successful. Token saved.[/green]")
    except Exception as exc:
        console.print(f"[red]✗ Authentication failed: {exc}[/red]")
        raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
