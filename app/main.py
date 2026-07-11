"""Main CLI entrypoint - flat commands for Typer 0.12.5 compatibility."""

from __future__ import annotations

import json
import csv
import sqlite3
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from app.config import settings
from app.database.db import (
    get_book_by_title,
    get_book_by_id,
    get_chapter,
    list_books,
    list_chapters,
    update_chapter_paths,
    get_connection,
    glossary_stats,
    get_glossary_pending,
    approve_glossary_term,
    reject_glossary_term,
    set_glossary_term_mode,
    glossary_coverage,
    auto_approve_glossary,
    get_glossary_conflicts,
    get_low_coverage_chapters,
    add_translation_suggestion,
    get_translation_suggestions,
    delete_translation_suggestion,
    init_db,
)
from app.ingestion.chapter_cleaner import clean_chapter
from app.ingestion.importers import import_clipboard, import_file
from app.translation.qa_reviewer import run_qa_check
from app.translation.ollama_client import translate_chapter, TranslationError
from app.translation.cache import get_cache_stats, clear_translation_cache
from app.scheduler.daily_queue import (
    get_pending_chapters,
    get_failed_chapters,
    update_chapter_after_translate,
    save_qa_report,
    generate_daily_report,
    save_daily_report,
    get_pending_glossary,
)
from app.audio.edge_tts_engine import text_to_speech_file
from app.ui.web_dashboard import start_server
from app.export.epub_exporter import export_epub
from app.export.m4b_exporter import export_m4b, export_mp3_playlist
from app.utils import safe_book_name


def _get_book_chapters(db_path: Path, book: str) -> tuple[dict, list[dict]]:
    """Helper: get book row and chapters by title."""
    book_row = get_book_by_title(db_path, book)
    if not book_row:
        raise ValueError(f"Book '{book}' not found")
    chapters = list_chapters(db_path, book_id=book_row["id"])
    return book_row, chapters


# Removed _safe_book_name — use app.utils.safe_book_name instead

app = typer.Typer(help="Chinese → Vietnamese novel translation pipeline.")
console = Console()


def _ensure_data_dir() -> Path:
    data_dir = settings.resolved_data_dir
    for sub in ("raw", "cleaned", "translated", "audio", "exports", "glossary", "logs"):
        (data_dir / sub).mkdir(parents=True, exist_ok=True)
    return data_dir


@app.callback()
def initialize_cli_database(ctx: typer.Context) -> None:
    if not ctx.invoked_subcommand or ctx.invoked_subcommand == "init":
        return
    data_dir = _ensure_data_dir()
    init_db(data_dir / "pipeline.db")


@app.command("init")
def init_cmd(
    force: bool = typer.Option(False, "--force", "-f", help="Re-initialize even if DB exists"),
) -> None:
    """Initialize the project: create folders, database, and starter glossary."""
    data_dir = _ensure_data_dir()
    db_path = data_dir / "pipeline.db"

    if db_path.exists() and not force:
        console.print(f"[yellow]Database already exists: {db_path}[/yellow]")
        console.print("Use --force to re-initialize.")
        raise typer.Exit()

    init_db(db_path)

    console.print(f"[green]✓ Initialized database: {db_path}[/green]")

    glossary_path = data_dir / "glossary" / "default.json"
    if not glossary_path.exists():
        default_glossary = {
            "魔尊": "Ma Tôn", "修炼": "tu luyện", "筑基": "trúc cơ",
            "金丹": "kim đan", "元婴": "nguyên anh", "灵石": "linh thạch",
            "飞剑": "phi kiếm",
        }
        glossary_path.write_text(
            json.dumps(default_glossary, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        console.print(f"[green]✓ Created default glossary: {glossary_path}[/green]")

    console.print("[green]✓ Initialization complete[/green]")


@app.command("import-file")
def import_file_cmd(
    book: str = typer.Option(..., "--book", "-b", help="Book title"),
    chapter: int = typer.Option(..., "--chapter", "-c", help="Chapter number"),
    title: str = typer.Option(..., "--title", "-t", help="Chapter title"),
    path: Path = typer.Option(..., "--path", "-p", help="Path to text file"),
) -> None:
    """Import chapter from a local text file."""
    _ensure_data_dir()
    try:
        raw_path = import_file(book, chapter, title, path)
        console.print(f"[green]✓ Imported to: {raw_path}[/green]")
    except Exception as exc:
        console.print(f"[red]Failed to import: {exc}[/red]")
        raise typer.Exit(1)


@app.command("import-clipboard")
def import_clipboard_cmd(
    book: str = typer.Option(..., "--book", "-b", help="Book title"),
    chapter: int = typer.Option(..., "--chapter", "-c", help="Chapter number"),
    title: str = typer.Option(..., "--title", "-t", help="Chapter title"),
) -> None:
    """Import chapter from system clipboard."""
    _ensure_data_dir()
    try:
        raw_path = import_clipboard(book, chapter, title)
        console.print(f"[green]✓ Imported to: {raw_path}[/green]")
    except Exception as exc:
        console.print(f"[red]Failed to import: {exc}[/red]")
        raise typer.Exit(1)


@app.command("clean")
def clean_cmd(
    book: str = typer.Option(..., "--book", "-b", help="Book title"),
    chapter: int = typer.Option(..., "--chapter", "-c", help="Chapter number"),
) -> None:
    """Clean a raw chapter (remove boilerplate, ads, broken lines)."""
    data_dir = _ensure_data_dir()
    db_path = data_dir / "pipeline.db"

    book_row = get_book_by_title(db_path, book)
    if not book_row:
        console.print(f"[red]Book '{book}' not found.[/red]")
        raise typer.Exit(1)

    ch = get_chapter(db_path, book_row["id"], chapter)
    if not ch:
        console.print(f"[red]Chapter {chapter} not found in '{book}'.[/red]")
        raise typer.Exit(1)

    raw_path = Path(ch["raw_text_path"])
    if not raw_path.exists():
        console.print(f"[red]Raw file missing: {raw_path}[/red]")
        raise typer.Exit(1)

    raw_text = raw_path.read_text(encoding="utf-8")
    cleaned_text = clean_chapter(raw_text)

    safe_book = safe_book_name(book)
    cleaned_path = data_dir / "cleaned" / f"{safe_book}_ch{chapter}_cleaned.txt"
    cleaned_path.write_text(cleaned_text, encoding="utf-8")

    update_chapter_paths(db_path, ch["id"], cleaned_text_path=cleaned_path, status="cleaned")
    console.print(f"[green]✓ Cleaned: {cleaned_path}[/green]")
    console.print(f"  [dim]Chars: {len(raw_text)} → {len(cleaned_text)}[/dim]")


@app.command("translate")
def translate_cmd(
    book: str = typer.Option(..., "--book", "-b", help="Book title"),
    chapter: int = typer.Option(..., "--chapter", "-c", help="Chapter number"),
    model: Optional[str] = typer.Option(None, "--model", "-m", help="Ollama model name"),
    host: Optional[str] = typer.Option(None, "--host", help="Ollama base URL"),
    temperature: Optional[float] = typer.Option(None, "--temperature", "-T", help="Sampling temperature"),
    chunk_size: Optional[int] = typer.Option(None, "--chunk-size", help="Max chars per chunk"),
) -> None:
    """Translate a cleaned chapter using Ollama."""
    data_dir = _ensure_data_dir()
    db_path = data_dir / "pipeline.db"

    book_row = get_book_by_title(db_path, book)
    if not book_row:
        console.print(f"[red]Book '{book}' not found.[/red]")
        raise typer.Exit(1)

    ch = get_chapter(db_path, book_row["id"], chapter)
    if not ch:
        console.print(f"[red]Chapter {chapter} not found in '{book}'.[/red]")
        raise typer.Exit(1)

    if ch.get("cleaned_text_path") and Path(ch["cleaned_text_path"]).exists():
        source_path = Path(ch["cleaned_text_path"])
    elif ch.get("raw_text_path") and Path(ch["raw_text_path"]).exists():
        source_path = Path(ch["raw_text_path"])
        console.print("[yellow]No cleaned version — using raw text.[/yellow]")
    else:
        console.print("[red]Source text not found.[/red]")
        raise typer.Exit(1)

    source_text = source_path.read_text(encoding="utf-8")
    console.print(f"[blue]Translating '{book}' chapter {chapter}...[/blue]")

    try:
        translated_text = translate_chapter(
            text=source_text, book_title=book, chapter_title=ch["title"],
            chapter_number=chapter, model=model, host=host,
            temperature=temperature, chunk_size=chunk_size,
        )
    except TranslationError as exc:
        console.print(f"[red]Translation failed: {exc}[/red]")
        update_chapter_paths(db_path, ch["id"], status="failed")
        raise typer.Exit(1)

    safe_book = safe_book_name(book)
    translated_path = data_dir / "translated" / safe_book / f"chapter_{chapter:04d}.txt"
    translated_path.parent.mkdir(parents=True, exist_ok=True)
    translated_path.write_text(translated_text, encoding="utf-8")

    update_chapter_paths(db_path, ch["id"], translated_text_path=translated_path, status="translated")
    console.print(f"[green]✓ Translated: {translated_path}[/green]")
    console.print(f"  [dim]Output chars: {len(translated_text)}[/dim]")


@app.command("list")
def list_cmd(
    book: Optional[str] = typer.Option(None, "--book", "-b", help="Filter by book title"),
) -> None:
    """List chapters, optionally filtered by book."""
    data_dir = _ensure_data_dir()
    db_path = data_dir / "pipeline.db"

    book_id = None
    if book:
        book_row = get_book_by_title(db_path, book)
        if not book_row:
            console.print(f"[red]Book '{book}' not found.[/red]")
            raise typer.Exit(1)
        book_id = book_row["id"]

    chapters = list_chapters(db_path, book_id=book_id)
    if not chapters:
        console.print("[yellow]No chapters found.[/yellow]")
        return

    all_books = {b["id"]: b["title"] for b in list_books(db_path)}
    tbl = Table(title=f"Chapters ({book})" if book else "All Chapters")
    tbl.add_column("ID"); tbl.add_column("Book"); tbl.add_column("Ch#")
    tbl.add_column("Title"); tbl.add_column("Status")
    for c in chapters:
        tbl.add_row(str(c["id"]), all_books.get(c["book_id"], "?"),
                     str(c["chapter_number"]), c["title"], c["status"])
    console.print(tbl)


# ── daily ──────────────────────────────────────────────────────────────────

@app.command("daily")
def daily_cmd(
    limit: int = typer.Option(15, "--limit", "-n", help="Max chapters to process"),
    book: Optional[str] = typer.Option(None, "--book", "-b", help="Process specific book only"),
    model: Optional[str] = typer.Option(None, "--model", "-m"),
    host: Optional[str] = typer.Option(None, "--host"),
) -> None:
    """Process up to N chapters: clean → translate → QA → report."""
    data_dir = _ensure_data_dir()
    db_path = data_dir / "pipeline.db"

    book_id = None
    if book:
        br = get_book_by_title(db_path, book)
        if not br:
            console.print(f"[red]Book '{book}' not found[/red]")
            raise typer.Exit(1)
        book_id = br["id"]

    # Get pending chapters (already cleaned)
    pending = get_pending_chapters(db_path, book_id=book_id, limit=limit)
    if not pending:
        console.print("[yellow]No cleaned chapters ready for translation.[/yellow]")
        return

    console.print(f"[blue]Processing {len(pending)} chapter(s)...[/blue]")

    for ch in pending:
        # Use provided book filter if available, else get from DB
        if book:
            book_title = book
        else:
            br = get_book_by_id(db_path, ch["book_id"])
            book_title = br["title"] if br else f"book_{ch['book_id']}"

        # Translate
        source_path = Path(ch["cleaned_text_path"])
        if not source_path.exists():
            continue

        source_text = source_path.read_text(encoding="utf-8")
        translated = translate_chapter(
            text=source_text, book_title=book_title,
            chapter_title=ch["title"], chapter_number=ch["chapter_number"],
            model=model, host=host,
        )

        safe_book = safe_book_name(book_title)
        trans_path = data_dir / "translated" / safe_book / f"chapter_{ch['chapter_number']:04d}.txt"
        trans_path.parent.mkdir(parents=True, exist_ok=True)
        trans_path.write_text(translated, encoding="utf-8")

        update_chapter_after_translate(db_path, ch["id"], trans_path)
        console.print(f"[green]✓ Translated ch{ch['chapter_number']}[/green]")

        # QA check
        qa_report = run_qa_check(source_text, translated, model=model, host=host)
        save_qa_report(db_path, ch["id"], qa_report["quality_score"], qa_report)

        if qa_report["quality_score"] < 7.0:
            console.print(f"[yellow]QA score: {qa_report['quality_score']:.1f} - needs review[/yellow]")

    # Generate daily report
    report = generate_daily_report(db_path, book_id=book_id if book else None)
    report_path = save_daily_report(db_path, report)
    console.print(f"[green]✓ Daily report: {report_path}[/green]")


# ── queue ─────────────────────────────────────────────────────────────────

@app.command("queue")
def queue_cmd(
    book: Optional[str] = typer.Option(None, "--book", "-b"),
    status: str = typer.Option("cleaned", "--status", "-s"),
) -> None:
    """Show translation queue."""
    data_dir = _ensure_data_dir()
    db_path = data_dir / "pipeline.db"

    book_id = None
    if book:
        br = get_book_by_title(db_path, book)
        if not br:
            console.print(f"[red]Book '{book}' not found[/red]")
            raise typer.Exit(1)
        book_id = br["id"]

    if status == "cleaned":
        items = get_pending_chapters(db_path, book_id=book_id)
    else:
        items = get_failed_chapters(db_path)

    if not items:
        console.print(f"[yellow]No chapters with status='{status}'[/yellow]")
        return

    all_books = {b["id"]: b["title"] for b in list_books(db_path)}
    tbl = Table(title=f"Queue ({status})")
    tbl.add_column("Ch#"); tbl.add_column("Book"); tbl.add_column("Title")
    for it in items:
        tbl.add_row(str(it["chapter_number"]), all_books.get(it["book_id"], "?"), it["title"])
    console.print(tbl)


# ── retry ─────────────────────────────────────────────────────────────────

@app.command("retry")
def retry_cmd(
    book: Optional[str] = typer.Option(None, "--book", "-b"),
    chapter: Optional[int] = typer.Option(None, "--chapter", "-c"),
    model: Optional[str] = typer.Option(None, "--model", "-m"),
    host: Optional[str] = typer.Option(None, "--host"),
) -> None:
    """Retry failed translations."""
    data_dir = _ensure_data_dir()
    db_path = data_dir / "pipeline.db"

    if chapter:
        br = get_book_by_title(db_path, book) if book else None
        if not br:
            console.print(f"[red]Book '{book}' not found[/red]")
            raise typer.Exit(1)
        ch = get_chapter(db_path, br["id"], chapter)
        if not ch or ch["status"] != "failed":
            console.print(f"[red]Chapter {chapter} not in failed state[/red]")
            raise typer.Exit(1)
        items = [ch]
    else:
        items = get_failed_chapters(db_path)

    for ch in items:
        br = get_book_by_id(db_path, ch["book_id"])
        if not br:
            continue
        book_title = br["title"]
        source_path = Path(ch.get("cleaned_text_path") or ch.get("raw_text_path"))
        if not source_path or not source_path.exists():
            continue

        source_text = source_path.read_text(encoding="utf-8")
        translated = translate_chapter(
            text=source_text, book_title=book_title,
            chapter_title=ch["title"], chapter_number=ch["chapter_number"],
            model=model, host=host,
        )

        safe_book = safe_book_name(book_title)
        trans_path = data_dir / "translated" / safe_book / f"chapter_{ch['chapter_number']:04d}.txt"
        trans_path.parent.mkdir(parents=True, exist_ok=True)
        trans_path.write_text(translated, encoding="utf-8")
        update_chapter_after_translate(db_path, ch["id"], trans_path)
        console.print(f"[green]✓ Retried ch{ch['chapter_number']}[/green]")


# ── glossary-review ────────────────────────────────────────────────────────

@app.command("glossary-review")
def glossary_review(
    approve: Optional[int] = typer.Option(None, "--approve", "-a"),
    reject: Optional[int] = typer.Option(None, "--reject", "-r"),
    book: Optional[str] = typer.Option(None, "--book", "-b"),
) -> None:
    """Review pending glossary terms."""
    data_dir = _ensure_data_dir()
    db_path = data_dir / "pipeline.db"

    book_id = None
    if book:
        br = get_book_by_title(db_path, book)
        if not br:
            console.print(f"[red]Book '{book}' not found[/red]")
            raise typer.Exit(1)
        book_id = br["id"]

    if approve:
        approve_glossary_term(db_path, approve)
        console.print(f"[green]✓ Approved term ID {approve}[/green]")
        return
    if reject:
        reject_glossary_term(db_path, reject)
        console.print(f"[green]✓ Rejected term ID {reject}[/green]")
        return

    terms = get_pending_glossary(db_path, book_id or 0)
    if not terms:
        console.print("[yellow]No pending terms[/yellow]")
        return

    tbl = Table(title="Pending Glossary Terms")
    tbl.add_column("ID"); tbl.add_column("Source"); tbl.add_column("Target"); tbl.add_column("Category")
    for t in terms:
        tbl.add_row(str(t["id"]), t["source_term"], t["target_term"], t["category"])
    console.print(tbl)
    console.print("[blue]Use --approve ID or --reject ID to act on terms[/blue]")


# ── tts ────────────────────────────────────────────────────────────────────

@app.command("tts")
def tts_cmd(
    book: str = typer.Option(..., "--book", "-b", help="Book title"),
    chapter: int = typer.Option(..., "--chapter", "-c", help="Chapter number"),
    voice: Optional[str] = typer.Option(None, "--voice", "-v", help="TTS voice (default: vi-VN-HoaiMyNeural)"),
    rate: str = typer.Option("-5%", "--rate", "-r", help="Speech rate (e.g. -5%, +10%)"),
) -> None:
    """Generate audio (MP3) from a translated chapter using edge-tts."""
    data_dir = _ensure_data_dir()
    db_path = data_dir / "pipeline.db"

    book_row = get_book_by_title(db_path, book)
    if not book_row:
        console.print(f"[red]Book '{book}' not found[/red]")
        raise typer.Exit(1)

    ch = get_chapter(db_path, book_row["id"], chapter)
    if not ch:
        console.print(f"[red]Chapter {chapter} not found in '{book}'[/red]")
        raise typer.Exit(1)

    if not ch.get("translated_text_path") or not Path(ch["translated_text_path"]).exists():
        console.print(f"[red]No translated text for ch{chapter}. Run translate first.[/red]")
        raise typer.Exit(1)

    translated_text = Path(ch["translated_text_path"]).read_text(encoding="utf-8")
    if not translated_text.strip():
        console.print("[red]Translated text is empty[/red]")
        raise typer.Exit(1)

    safe_book = safe_book_name(book)
    audio_dir = data_dir / "audio" / safe_book
    audio_dir.mkdir(parents=True, exist_ok=True)
    audio_path = audio_dir / f"chapter_{chapter:04d}.mp3"

    console.print(f"[blue]Generating audio for '{book}' ch{chapter}...[/blue]")
    console.print(f"  Voice: {voice or settings.edge_tts_voice} | Rate: {rate}")

    try:
        text_to_speech_file(
            text=translated_text,
            output_path=audio_path,
            book_title=book,
            chapter_number=chapter,
            chapter_title=ch["title"],
            voice=voice,
            rate=rate,
        )
    except Exception as e:
        console.print(f"[red]TTS failed: {e}[/red]")
        raise typer.Exit(1)

    # Update DB
    with get_connection(db_path) as conn:
        conn.execute(
            "UPDATE chapters SET audio_path = ?, status = 'audio_done' WHERE id = ?",
            (str(audio_path), ch["id"]),
        )
        conn.commit()

    size_mb = audio_path.stat().st_size / (1024 * 1024)
    console.print(f"[green]✓ Audio: {audio_path}[/green] [dim]({size_mb:.1f} MB)[/dim]")


# ── dashboard ──────────────────────────────────────────────────────────────

@app.command("dashboard")
def dashboard_cmd(
    host: str = typer.Option("127.0.0.1", "--host", "-h", help="Server host"),
    port: int = typer.Option(8000, "--port", "-p", help="Server port"),
) -> None:
    """Start the local web dashboard."""
    console.print(f"[blue]Starting dashboard on http://{host}:{port}[/blue]")
    console.print(f"  API docs: http://{host}:{port}/docs")
    console.print("[dim]Press Ctrl+C to stop.[/dim]")
    start_server(host=host, port=port)


# ── export-epub ────────────────────────────────────────────────────────────

@app.command("export-epub")
def export_epub_cmd(
    book: str = typer.Option(..., "--book", "-b", help="Book title"),
) -> None:
    """Export translated chapters as EPUB ebook."""
    data_dir = _ensure_data_dir()
    db_path = data_dir / "pipeline.db"
    try:
        book_row, chapters = _get_book_chapters(db_path, book)
    except ValueError as e:
        console.print(f"[red]{e}[/red]"); raise typer.Exit(1)

    trans_chapters = [c for c in chapters if c.get("translated_text_path") and Path(c["translated_text_path"]).exists()]
    if not trans_chapters:
        console.print("[red]No translated chapters to export.[/red]"); raise typer.Exit(1)

    safe = safe_book_name(book)
    epub_path = data_dir / "exports" / safe / f"{safe}.epub"
    epub_path.parent.mkdir(parents=True, exist_ok=True)

    export_epub(
        book_title=book,
        author=book_row.get("author", ""),
        chapters=trans_chapters,
        output_path=epub_path,
    )

    size_kb = epub_path.stat().st_size / 1024
    console.print(f"[green]✓ EPUB: {epub_path}[/green] [dim]({size_kb:.0f} KB)[/dim]")


# ── export-m4b ─────────────────────────────────────────────────────────────

@app.command("export-m4b")
def export_m4b_cmd(
    book: str = typer.Option(..., "--book", "-b", help="Book title"),
) -> None:
    """Merge chapter MP3s into single M4B audiobook."""
    data_dir = _ensure_data_dir()
    db_path = data_dir / "pipeline.db"
    try:
        book_row, chapters = _get_book_chapters(db_path, book)
    except ValueError as e:
        console.print(f"[red]{e}[/red]"); raise typer.Exit(1)

    audio_chapters = [c for c in chapters if c.get("audio_path") and Path(c["audio_path"]).exists()]
    if not audio_chapters:
        console.print("[red]No audio chapters to merge. Run TTS first.[/red]"); raise typer.Exit(1)

    safe = safe_book_name(book)
    m4b_path = data_dir / "exports" / safe / f"{safe}.m4b"

    export_m4b(book, book_row.get("author", ""), audio_chapters, m4b_path)

    size_mb = m4b_path.stat().st_size / (1024 * 1024)
    console.print(f"[green]✓ M4B: {m4b_path}[/green] [dim]({size_mb:.1f} MB)[/dim]")

    # Also export a playlist
    playlist_path = data_dir / "exports" / safe / f"{safe}.m3u"
    export_mp3_playlist(book, audio_chapters, playlist_path)
    console.print(f"[green]✓ Playlist: {playlist_path}[/green]")


# Subapp for glossary commands
glossary_app = typer.Typer(help="Glossary management commands.")
app.add_typer(glossary_app, name="glossary")


@glossary_app.callback()
def glossary_callback():
    """Glossary management commands."""
    pass


@glossary_app.command("import")
def glossary_import_cmd(
    csv_path: Path = typer.Option(..., "--csv", "-c", help="Path to glossary CSV"),
    book: Optional[str] = typer.Option(None, "--book", "-b", help="Book title (optional, defaults to global glossary)"),
    mode: Optional[str] = typer.Option(None, "--mode", "-m", help="Filter by mode (translate/context/transliterate), default: translate"),
):
    """Import glossary from CSV into pipeline database."""
    data_dir = _ensure_data_dir()
    db_path = data_dir / "pipeline.db"

    if not csv_path.exists():
        console.print(f"[red]CSV not found: {csv_path}[/red]")
        raise typer.Exit(1)

    book_id = 0
    if book:
        row = get_book_by_title(db_path, book)
        if not row:
            console.print(f"[red]Book not found: {book}[/red]")
            raise typer.Exit(1)
        book_id = row["id"]

    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()

    imported = 0
    skipped = 0
    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            row_mode = row.get("mode", "").strip()
            if mode and row_mode != mode:
                skipped += 1
                continue
            if not mode and row_mode != "translate":
                skipped += 1
                continue
            source = row.get("source_zh", "").strip()
            target = row.get("vi_preferred", "").strip()
            if not source or not target:
                skipped += 1
                continue
            category = row.get("category", "").strip()
            pinyin = row.get("pinyin", "").strip()
            notes = row.get("notes_vi", "").strip()
            variants = row.get("variants", "").strip()
            cur.execute(
                """
                INSERT OR REPLACE INTO glossary_terms (book_id, source_term, target_term, category, approved, mode, pinyin, notes_vi, variants)
                       VALUES (?, ?, ?, ?, 1, ?, ?, ?, ?)
                """,
                (book_id, source, target, category, row_mode, pinyin, notes, variants),
            )
            imported += 1

    conn.commit()
    count = cur.execute("SELECT COUNT(*) FROM glossary_terms WHERE book_id = ? AND approved = 1", (book_id,)).fetchone()[0]
    conn.close()

    if book:
        console.print(f"[green]✓ Imported {imported} terms for book '{book}' (skipped {skipped})[/green]")
    else:
        console.print(f"[green]✓ Imported {imported} global terms (skipped {skipped})[/green]")
    console.print(f"[green]Total approved terms for book_id={book_id}: {count}[/green]")


# ── glossary audit ─────────────────────────────────────────────────────────


@glossary_app.command("audit")
def glossary_audit_cmd(
    book: Optional[str] = typer.Option(None, "--book", "-b", help="Book title (optional, shows global if omitted)"),
):
    """Show glossary library health stats."""
    data_dir = _ensure_data_dir()
    db_path = data_dir / "pipeline.db"
    book_id = None
    if book:
        row = get_book_by_title(db_path, book)
        if not row:
            console.print(f"[red]Book not found: {book}[/red]"); raise typer.Exit(1)
        book_id = row["id"]
    stats = glossary_stats(db_path, book_id)
    label = f"book '{book}'" if book else "global"
    console.print(f"\n[bold]Glossary Audit — {label}[/bold]\n")
    console.print(f"  Total terms:       {stats['total']}")
    console.print(f"  Unique source:     {stats['unique_source']}")
    console.print(f"  Categories:        {stats['categories']}")
    console.print("  ─────────────────────────────────")
    console.print(f"  [green]translate:[/green]      {stats['translate']}")
    console.print(f"  [cyan]transliterate:[/cyan]   {stats['transliterate']}")
    console.print(f"  [yellow]context:[/yellow]        {stats['context']}")
    console.print(f"  [red]no mode:[/red]         {stats['no_mode']}")
    console.print("  ─────────────────────────────────")
    console.print(f"  Approved:          {stats['approved']}")
    console.print(f"  Pending review:    {stats['pending_approval']}")
    console.print("  ─────────────────────────────────")
    console.print(f"  Has pinyin:        {stats['has_pinyin']}")
    console.print(f"  Has notes_vi:      {stats['has_notes']}")
    console.print(f"  Has variants:      {stats['has_variants']}")
    # Health score
    score = 10
    if stats["no_mode"] > 0: score -= 1
    if stats["pending_approval"] > 0: score -= 0.5
    if stats["has_variants"] < stats["total"] * 0.1: score -= 1
    if stats["has_notes"] < stats["total"] * 0.05: score -= 0.5
    score = max(0, min(10, score))
    color = "green" if score >= 8 else "yellow" if score >= 5 else "red"
    console.print(f"\n  [bold]Health score: [{color}]{score}/10[/{color}][/bold]\n")


# ── glossary coverage ─────────────────────────────────────────────────────


@glossary_app.command("coverage")
def glossary_coverage_cmd(
    book: str = typer.Option(..., "--book", "-b", help="Book title"),
    chapter: int = typer.Option(..., "--chapter", "-c", help="Chapter number"),
):
    """Analyze glossary coverage for a specific chapter."""
    data_dir = _ensure_data_dir()
    db_path = data_dir / "pipeline.db"
    book_row = get_book_by_title(db_path, book)
    if not book_row:
        console.print(f"[red]Book not found: {book}[/red]"); raise typer.Exit(1)
    book_id = book_row["id"]
    chapter_row = get_chapter(db_path, book_id, chapter)
    if not chapter_row:
        console.print(f"[red]Chapter {chapter} not found for '{book}'[/red]"); raise typer.Exit(1)
    raw_path = chapter_row.get("raw_text_path")
    if not raw_path or not Path(raw_path).exists():
        console.print(f"[red]Raw text not found: {raw_path}[/red]"); raise typer.Exit(1)
    source_text = Path(raw_path).read_text(encoding="utf-8")
    result = glossary_coverage(db_path, book_id, source_text)
    console.print(f"\n[bold]Glossary Coverage — {book} ch{chapter}[/bold]\n")
    console.print(f"  Source chars:      {result['total_chars']}")
    console.print(f"  Covered chars:     {result['covered_chars']}")
    pct = result['coverage_pct']
    color = "green" if pct >= 60 else "yellow" if pct >= 30 else "red"
    console.print(f"  Coverage:          [{color}]{pct}%[/{color}]")
    console.print(f"  Matched terms:     {result['matched_count']}")
    if result["hits"]:
        console.print("\n  [bold]Matched terms:[/bold]")
        for src, tgt in result["hits"][:30]:
            console.print(f"    {src} → {tgt}")
        if len(result["hits"]) > 30:
            console.print(f"    ... and {len(result['hits']) - 30} more")
    console.print()


# ── glossary review ───────────────────────────────────────────────────────


@glossary_app.command("review")
def glossary_review_cmd(
    book: Optional[str] = typer.Option(None, "--book", "-b", help="Book title (optional)"),
    limit: int = typer.Option(20, "--limit", "-n", help="Max terms to show"),
):
    """Review pending (unapproved) glossary terms."""
    data_dir = _ensure_data_dir()
    db_path = data_dir / "pipeline.db"
    book_id = None
    if book:
        row = get_book_by_title(db_path, book)
        if not row:
            console.print(f"[red]Book not found: {book}[/red]"); raise typer.Exit(1)
        book_id = row["id"]
    pending = get_glossary_pending(db_path, book_id, limit)
    if not pending:
        console.print("[green]No pending glossary terms. All clear.[/green]")
        return
    console.print(f"\n[bold]Pending Glossary Terms ({len(pending)} shown)[/bold]\n")
    table = Table(show_header=True, header_style="bold")
    table.add_column("ID", style="dim", width=5)
    table.add_column("Source", width=15)
    table.add_column("Target", width=25)
    table.add_column("Category", width=15)
    table.add_column("Mode", width=12)
    for t in pending:
        table.add_row(
            str(t["id"]), t["source_term"], t["target_term"],
            t["category"], t["mode"] or "(none)",
        )
    console.print(table)
    console.print("\n[dim]Use: glossary approve <id> | glossary reject <id> | glossary set-mode <id> <mode>[/dim]\n")


# ── glossary approve ──────────────────────────────────────────────────────


@glossary_app.command("approve")
def glossary_approve_cmd(
    term_id: int = typer.Argument(..., help="Glossary term ID to approve"),
):
    """Approve a pending glossary term."""
    data_dir = _ensure_data_dir()
    db_path = data_dir / "pipeline.db"
    ok = approve_glossary_term(db_path, term_id)
    if ok:
        console.print(f"[green]✓ Approved term #{term_id}[/green]")
    else:
        console.print(f"[red]Term #{term_id} not found or already approved[/red]")


# ── glossary reject ───────────────────────────────────────────────────────


@glossary_app.command("reject")
def glossary_reject_cmd(
    term_id: int = typer.Argument(..., help="Glossary term ID to reject"),
):
    """Reject (delete) a pending glossary term."""
    data_dir = _ensure_data_dir()
    db_path = data_dir / "pipeline.db"
    ok = reject_glossary_term(db_path, term_id)
    if ok:
        console.print(f"[green]✓ Rejected term #{term_id}[/green]")
    else:
        console.print(f"[red]Term #{term_id} not found or not pending[/red]")


# ── glossary set-mode ─────────────────────────────────────────────────────


@glossary_app.command("set-mode")
def glossary_set_mode_cmd(
    term_id: int = typer.Argument(..., help="Glossary term ID"),
    mode: str = typer.Argument(..., help="Mode: translate | context | transliterate"),
):
    """Set the mode of a glossary term."""
    data_dir = _ensure_data_dir()
    db_path = data_dir / "pipeline.db"
    try:
        ok = set_glossary_term_mode(db_path, term_id, mode)
    except ValueError as e:
        console.print(f"[red]{e}[/red]"); raise typer.Exit(1)
    if ok:
        console.print(f"[green]✓ Term #{term_id} mode → {mode}[/green]")
    else:
        console.print(f"[red]Term #{term_id} not found[/red]")


# ── glossary auto-approve ───────────────────────────────────────────────────


@glossary_app.command("auto-approve")
def glossary_auto_approve_cmd(
    min_occurrences: int = typer.Option(3, "--min", help="Minimum occurrence count to auto-approve"),
    book: Optional[str] = typer.Option(None, "--book", "-b", help="Book title (optional, all books if omitted)"),
):
    """Auto-approve pending terms that have occurred multiple times."""
    data_dir = _ensure_data_dir()
    db_path = data_dir / "pipeline.db"
    book_id = None
    if book:
        row = get_book_by_title(db_path, book)
        if not row:
            console.print(f"[red]Book not found: {book}[/red]"); raise typer.Exit(1)
        book_id = row["id"]
    count = auto_approve_glossary(db_path, min_occurrences, book_id)
    label = f"book '{book}'" if book else "all books"
    console.print(f"[green]✓ Auto-approved {count} terms in {label}[/green]")


# ── glossary conflicts ──────────────────────────────────────────────────────


@glossary_app.command("conflicts")
def glossary_conflicts_cmd(
    book: Optional[str] = typer.Option(None, "--book", "-b", help="Book title (optional, check all)"),
    limit: int = typer.Option(20, "--limit", "-n", help="Max conflicts to show"),
):
    """Show source terms with conflicting translations."""
    data_dir = _ensure_data_dir()
    db_path = data_dir / "pipeline.db"
    book_id = None
    if book:
        row = get_book_by_title(db_path, book)
        if not row:
            console.print(f"[red]Book not found: {book}[/red]"); raise typer.Exit(1)
        book_id = row["id"]
    conflicts = get_glossary_conflicts(db_path, book_id)[:limit]
    if not conflicts:
        console.print("[green]No glossary conflicts found.[/green]")
        return
    label = f"book '{book}'" if book else "all books"
    console.print(f"\n[bold]Glossary Conflicts ({len(conflicts)} shown) — {label}[/bold]\n")
    for c in conflicts:
        console.print(f"[yellow]{c['source_term']}[/yellow]")
        for t in c["targets"]:
            status = "[dim]" if t["approved"] else "[red]pending[/red]"
            console.print(f"  [{status}]{t['book_id']}: {t['target_term']} (mode={t['mode'] or 'none'})[/{status}]")
        console.print()


# ── glossary low-coverage ───────────────────────────────────────────────────


@glossary_app.command("low-coverage")
def glossary_low_coverage_cmd(
    book: str = typer.Option(..., "--book", "-b", help="Book title"),
    threshold: float = typer.Option(30.0, "--threshold", "-t", help="Coverage % threshold"),
):
    """List chapters with glossary coverage below threshold."""
    data_dir = _ensure_data_dir()
    db_path = data_dir / "pipeline.db"
    book_row = get_book_by_title(db_path, book)
    if not book_row:
        console.print(f"[red]Book not found: {book}[/red]"); raise typer.Exit(1)
    book_id = book_row["id"]
    low_cov = get_low_coverage_chapters(db_path, book_id, threshold)
    if not low_cov:
        console.print(f"[green]All chapters have coverage ≥ {threshold}%[/green]")
        return
    console.print(f"\n[bold]Low Coverage Chapters (≤ {threshold}%) — {book}[/bold]\n")
    table = Table(show_header=True, header_style="bold")
    table.add_column("Ch", style="dim", width=4)
    table.add_column("Title", width=30)
    table.add_column("Coverage", width=10)
    table.add_column("Matched", width=8)
    for c in low_cov:
        color = "red" if c["coverage_pct"] < 20 else "yellow"
        table.add_row(
            str(c["chapter_number"]), c["title"][:28],
            f"[{color}]{c['coverage_pct']}%[/{color}]",
            str(c["matched_count"]),
        )
    console.print(table)


    console.print(table)


# ── cache commands ────────────────────────────────────────────────────────────


cache_app = typer.Typer(help="Translation cache commands.")
app.add_typer(cache_app, name="cache")


@cache_app.command("stats")
def cache_stats_cmd():
    """Show translation cache statistics."""
    data_dir = _ensure_data_dir()
    db_path = data_dir / "pipeline.db"
    stats = get_cache_stats(db_path)
    console.print("\n[bold]Translation Cache Stats[/bold]")
    console.print(f"  Entries:  {stats['count']}")
    console.print(f"  Size:     {stats['total_bytes']:,} bytes ({stats['total_bytes']/1024:.1f} KB)")


@cache_app.command("clear")
def cache_clear_cmd():
    """Clear all cached translations."""
    data_dir = _ensure_data_dir()
    db_path = data_dir / "pipeline.db"
    count = clear_translation_cache(db_path)
    console.print(f"[green]✓ Cleared {count} cache entries[/green]")


# ── suggest commands ──────────────────────────────────────────────────────────


suggest_app = typer.Typer(help="Translation suggestion/correction commands.")
app.add_typer(suggest_app, name="suggest")


@suggest_app.command("add")
def suggest_add_cmd(
    q: str = typer.Argument(..., help="Original source text"),
    s: str = typer.Argument(..., help="Suggested corrected translation"),
    source: str = typer.Option("zh", "--source", help="Source language code"),
    target: str = typer.Option("vi", "--target", help="Target language code"),
    book: Optional[str] = typer.Option(None, "--book", "-b", help="Book title (optional)"),
    chapter: Optional[int] = typer.Option(None, "--chapter", "-c", help="Chapter number"),
):
    """Submit a translation correction (like LibreTranslate /suggest)."""
    data_dir = _ensure_data_dir()
    db_path = data_dir / "pipeline.db"
    book_id = None
    if book:
        row = get_book_by_title(db_path, book)
        if not row:
            console.print(f"[red]Book not found: {book}[/red]"); raise typer.Exit(1)
        book_id = row["id"]
    if not q.strip() or not s.strip():
        console.print("[red]Both q and s must be non-empty[/red]"); raise typer.Exit(1)
    add_translation_suggestion(db_path, q, s, source, target, book_id, chapter)
    console.print("[green]✓ Suggestion added[/green]")


@suggest_app.command("list")
def suggest_list_cmd(
    limit: int = typer.Option(20, "--limit", "-n", help="Max suggestions to show"),
    book: Optional[str] = typer.Option(None, "--book", "-b", help="Book title (optional)"),
):
    """List pending translation suggestions."""
    data_dir = _ensure_data_dir()
    db_path = data_dir / "pipeline.db"
    book_id = None
    if book:
        row = get_book_by_title(db_path, book)
        if not row:
            console.print(f"[red]Book not found: {book}[/red]"); raise typer.Exit(1)
        book_id = row["id"]
    suggestions = get_translation_suggestions(db_path, limit, book_id)
    if not suggestions:
        console.print("[green]No suggestions pending.[/green]")
        return
    label = f"book '{book}'" if book else "all books"
    console.print(f"\n[bold]Translation Suggestions ({len(suggestions)} shown) — {label}[/bold]\n")
    table = Table(show_header=True, header_style="bold")
    table.add_column("ID", style="dim", width=5)
    table.add_column("Original (q)", width=30)
    table.add_column("Suggested (s)", width=30)
    table.add_column("Src→Tgt", width=10)
    table.add_column("Book", width=8)
    table.add_column("Ch", width=5)
    for sug in suggestions:
        table.add_row(
            str(sug["id"]),
            sug["q"][:28] + ("..." if len(sug["q"]) > 28 else ""),
            sug["s"][:28] + ("..." if len(sug["s"]) > 28 else ""),
            f"{sug['source_lang']}→{sug['target_lang']}",
            str(sug["book_id"]),
            str(sug["chapter_number"] or "-"),
        )
    console.print(table)


@suggest_app.command("delete")
def suggest_delete_cmd(
    suggestion_id: int = typer.Argument(..., help="Suggestion ID to delete"),
):
    """Delete a translation suggestion."""
    data_dir = _ensure_data_dir()
    db_path = data_dir / "pipeline.db"
    ok = delete_translation_suggestion(db_path, suggestion_id)
    if ok:
        console.print(f"[green]✓ Deleted suggestion #{suggestion_id}[/green]")
    else:
        console.print(f"[red]Suggestion #{suggestion_id} not found[/red]")


@suggest_app.command("promote")
def suggest_promote_cmd(
    suggestion_id: int = typer.Argument(..., help="Suggestion ID to promote"),
    source_term: str = typer.Option(..., "--source-term", "-s", help="Chinese source term from the original text"),
    target_term: str = typer.Option(..., "--target-term", "-t", help="Vietnamese target term (corrected translation)"),
    category: str = typer.Option("term", "--category", "-c", help="Glossary category"),
    mode: str = typer.Option("translate", "--mode", "-m", help="Glossary mode: translate|context|transliterate"),
    book: Optional[str] = typer.Option(None, "--book", "-b", help="Book title (for book-specific glossary)"),
):
    """Promote a suggestion to glossary term.

    Extracts a specific term pair from a user correction and adds to glossary.
    Example: suggest promote 42 -s \"灵石\" -t \"linh thạch\" -c cultivation
    """
    data_dir = _ensure_data_dir()
    db_path = data_dir / "pipeline.db"

    # Get the suggestion
    suggestions = get_translation_suggestions(db_path, limit=1)
    sug = next((s for s in suggestions if s["id"] == suggestion_id), None)
    if not sug:
        console.print(f"[red]Suggestion #{suggestion_id} not found[/red]"); raise typer.Exit(1)

    # Verify source_term exists in original text
    if source_term not in sug["q"]:
        console.print(f"[yellow]Warning: source term '{source_term}' not found in original text '{sug['q']}'[/yellow]")

    book_id = None
    if book:
        row = get_book_by_title(db_path, book)
        if not row:
            console.print(f"[red]Book not found: {book}[/red]"); raise typer.Exit(1)
        book_id = row["id"]

    # Add to glossary
    from app.database.db import put_glossary_term
    put_glossary_term(db_path, book_id or 0, source_term, target_term, category, mode)

    # Delete the suggestion after promotion
    delete_translation_suggestion(db_path, suggestion_id)

    console.print(f"[green]✓ Promoted suggestion #{suggestion_id} to glossary: {source_term} → {target_term}[/green]")


# ── fix (user correction) ─────────────────────────────────────────────────────

@app.command("fix")
def fix_cmd(
    book: str = typer.Option(..., "--book", "-b", help="Book title"),
    chapter: int = typer.Option(..., "--chapter", "-c", help="Chapter number"),
    original: str = typer.Option(..., "--original", "-o", help="Pipeline output text to correct"),
    fix: str = typer.Option(..., "--fix", "-x", help="Your corrected Vietnamese text"),
    correction_type: str = typer.Option("terminology", "--type", "-t", help="Type: terminology|style|pronoun|name"),
) -> None:
    """Record a user correction — feeds the self-learning loop."""
    from app.translation.self_improve import add_correction
    data_dir = _ensure_data_dir()
    db_path = data_dir / "pipeline.db"

    book_row = get_book_by_title(db_path, book)
    if not book_row:
        console.print(f"[red]Book '{book}' not found[/red]")
        raise typer.Exit(1)

    row_id = add_correction(
        db_path,
        book_id=book_row["id"],
        chapter_number=chapter,
        source_chunk=original,
        pipe_out=original,
        user_fix=fix,
        correction_type=correction_type,
    )
    console.print(f"[green]✓ Correction #{row_id} recorded[/green]")
    console.print(f"  [dim]Original: {original[:80]}[/dim]")
    console.print(f"  [dim]Fix:      {fix[:80]}[/dim]")


# ── self-improve ───────────────────────────────────────────────────────────────

@app.command("self-improve")
def self_improve_cmd(
    book: Optional[str] = typer.Option(None, "--book", "-b", help="Book title (default: all books)"),
    days: int = typer.Option(7, "--days", "-d", help="Look back N days for corrections"),
    min_freq: int = typer.Option(2, "--min-freq", "-f", help="Min occurrences to promote candidate"),
    auto_approve: bool = typer.Option(False, "--auto-approve", help="Auto-approve candidates (skip review)"),
) -> None:
    """Harvest user corrections → extract glossary candidates → queue for review.

    Run weekly (or after batch corrections). Then run:
        glossary-review   → inspect candidates
        glossary auto-approve --min 2  → promote confirmed terms
    """
    from app.translation.self_improve import run_self_improve, get_correction_stats

    data_dir = _ensure_data_dir()
    db_path = data_dir / "pipeline.db"

    book_id = 0
    if book:
        book_row = get_book_by_title(db_path, book)
        if not book_row:
            console.print(f"[red]Book '{book}' not found[/red]")
            raise typer.Exit(1)
        book_id = book_row["id"]

    stats = get_correction_stats(db_path)
    console.print(f"[blue]Corrections in DB: {stats['total_corrections']} total, {stats['last_7_days']} last 7 days[/blue]")

    result = run_self_improve(db_path, book_id=book_id, days=days, min_freq=min_freq)

    if result["status"] == "no_candidates":
        console.print(f"[yellow]No candidates found (need ≥{min_freq} identical corrections in last {days} days)[/yellow]")
        return

    console.print(f"[green]✓ Found {result['candidates_found']} candidates, queued {result['applied']} to glossary[/green]")

    tbl = Table(title="Top Candidates (pending review)")
    tbl.add_column("Old Term"); tbl.add_column("New Term"); tbl.add_column("Freq")
    for c in result["top_candidates"]:
        tbl.add_row(c["old_term"][:40], c["new_term"][:40], str(c["frequency"]))
    console.print(tbl)

    if not auto_approve:
        console.print("\n[dim]Run: python -m app.main glossary-review  →  to review candidates[/dim]")
        console.print("[dim]Run: python -m app.main glossary auto-approve --min 2  →  to promote confirmed[/dim]")


# ── detect language ──────────────────────────────────────────────────────────


@app.command("detect")
def detect_lang_cmd(
    text: Optional[str] = typer.Argument(None, help="Text to detect language for. If omitted, reads from stdin."),
    file: Optional[Path] = typer.Option(None, "--file", "-f", help="Read text from file"),
):
    """Detect language of Chinese/Vietnamese/English text."""
    from app.translation.language_detect import count_leftover_chinese, detect_language

    if file:
        text = file.read_text(encoding="utf-8")
    if not text:
        console.print("[red]Provide text as argument, via --file, or pipe to stdin[/red]")
        raise typer.Exit(1)

    result = detect_language(text)
    console.print("\n[bold]Language Detection[/bold]")
    console.print(f"  Language:    {result['language']}")
    console.print(f"  Confidence:  {result['confidence']}%")
    console.print(f"  CJK chars:   {result['cjk_chars']}")
    console.print(f"  VI chars:    {result['vi_chars']}")
    console.print(f"  Latin chars: {result['latin_chars']}")

    if result["language"] == "vi" or result["cjk_chars"] > 0:
        leftover = count_leftover_chinese(text)
        if leftover > 0:
            console.print(f"  [yellow]⚠ Leftover CJK: {leftover}[/yellow]")


if __name__ == "__main__":
    app()
