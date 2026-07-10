"""FastAPI web dashboard for the novel translation pipeline."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import uvicorn
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse

from app.config import settings
from app.utils.rate_limiter import limiter
from app.database.db import (
    get_book_by_title,
    get_book_by_id,
    get_chapter_by_id,
    list_books,
    list_chapters,
    update_chapter_paths,
    add_translation_suggestion,
)
from app.translation.ollama_client import translate_chapter
from app.translation.cache import get_cache_stats, clear_translation_cache
from app.scheduler.daily_queue import (
    get_pending_chapters,
    get_failed_chapters,
    generate_daily_report,
    save_daily_report,
    get_pending_glossary,
    approve_glossary_term,
    reject_glossary_term,
)
from app.audio.edge_tts_engine import text_to_speech_file

app = FastAPI(title="Novel Translation Pipeline Dashboard")


@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    """Rate limit by IP — adapted from LibreTranslate flood.py."""
    client_ip = request.client.host if request.client else "unknown"
    # Skip rate limiting for read-only GETs on root/docs
    if request.method == "GET" and request.url.path in ("/", "/docs", "/openapi.json"):
        return await call_next(request)
    if not limiter.is_allowed(client_ip):
        return JSONResponse(
            status_code=429,
            content={"error": "Too many requests. Slow down.", "remaining": 0},
        )
    response = await call_next(request)
    response.headers["X-RateLimit-Remaining"] = str(limiter.remaining(client_ip))
    return response

# Helper functions
def _ensure_data_dir() -> Path:
    data_dir = settings.resolved_data_dir
    for sub in ("raw", "cleaned", "translated", "audio", "exports", "glossary", "logs"):
        (data_dir / sub).mkdir(parents=True, exist_ok=True)
    return data_dir


# API Endpoints

@app.get("/", response_class=HTMLResponse)
async def root():
    """Dashboard landing page with LibreTranslate-inspired UX."""
    return """
    <html>
        <head>
            <title>Novel Translation Pipeline</title>
            <style>
                :root {
                    --bg: #fafafa;
                    --fg: #18181b;
                    --card: #ffffff;
                    --muted: #71717a;
                    --accent: #4f46e5;
                    --border: #e4e4e7;
                }
                @media (prefers-color-scheme: dark) {
                    :root {
                        --bg: #09090b;
                        --fg: #f4f4f5;
                        --card: #18181b;
                        --muted: #a1a1aa;
                        --accent: #818cf8;
                        --border: #27272a;
                    }
                }
                body { font-family: system-ui, sans-serif; background: var(--bg); color: var(--fg); margin: 0; padding: 32px; }
                .wrap { max-width: 880px; margin: auto; }
                .card { background: var(--card); border: 1px solid var(--border); border-radius: 16px; padding: 24px; margin: 18px 0; }
                h1 { letter-spacing: -0.03em; }
                a { color: var(--accent); text-decoration: none; }
                .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 12px; }
                .pill { display: block; border: 1px solid var(--border); border-radius: 12px; padding: 14px; }
                .muted { color: var(--muted); }
                button { background: var(--accent); color: white; border: 0; border-radius: 10px; padding: 10px 14px; cursor: pointer; }
                textarea,input { width: 100%; background: var(--bg); color: var(--fg); border: 1px solid var(--border); border-radius: 10px; padding: 10px; margin: 6px 0; }
                .progress { height: 3px; background: var(--border); overflow: hidden; display: none; }
                .progress div { width: 35%; height: 100%; background: var(--accent); animation: slide 1s infinite; }
                @keyframes slide { from { transform: translateX(-100%); } to { transform: translateX(300%); } }
                #toast { position: fixed; right: 20px; bottom: 20px; background: var(--card); border: 1px solid var(--border); padding: 14px 18px; border-radius: 12px; display: none; }
            </style>
        </head>
        <body>
            <div class="wrap">
                <h1>Novel Translation Pipeline</h1>
                <p class="muted">Chinese → Vietnamese translation, glossary memory, cache, audio export.</p>

                <div class="card">
                    <h2>Endpoints</h2>
                    <div class="grid">
                        <a class="pill" href="/docs">API docs</a>
                        <a class="pill" href="/books">Books</a>
                        <a class="pill" href="/chapters">Chapters</a>
                        <a class="pill" href="/queue">Queue</a>
                        <a class="pill" href="/glossary">Glossary</a>
                        <a class="pill" href="/cache/stats">Cache stats</a>
                    </div>
                </div>

                <div class="card">
                    <h2>Suggest correction</h2>
                    <p class="muted">Submit original text + corrected translation. This feeds glossary review.</p>
                    <label>Original source</label>
                    <textarea id="q" rows="3"></textarea>
                    <label>Corrected translation</label>
                    <textarea id="s" rows="3"></textarea>
                    <button onclick="sendSuggestion()">Send suggestion</button>
                    <div class="progress" id="prog"><div></div></div>
                </div>
            </div>
            <div id="toast"></div>
            <script>
                function toast(msg) {
                    const el = document.getElementById('toast');
                    el.textContent = msg; el.style.display = 'block';
                    setTimeout(() => el.style.display = 'none', 2500);
                }
                async function sendSuggestion() {
                    const q = document.getElementById('q').value;
                    const s = document.getElementById('s').value;
                    const prog = document.getElementById('prog');
                    prog.style.display = 'block';
                    try {
                        const params = new URLSearchParams({q, s, source_lang:'zh', target_lang:'vi'});
                        const res = await fetch('/suggest?' + params.toString(), {method:'POST'});
                        if (!res.ok) throw new Error(await res.text());
                        toast('Suggestion saved. Thanks.');
                    } catch (e) { toast('Error: ' + e.message); }
                    finally { prog.style.display = 'none'; }
                }
            </script>
        </body>
    </html>
    """


@app.get("/books")
async def list_books_endpoint():
    """List all books."""
    data_dir = _ensure_data_dir()
    db_path = data_dir / "pipeline.db"
    books = list_books(db_path)
    return JSONResponse(content=books)


@app.get("/chapters")
async def list_chapters_endpoint(book: Optional[str] = None):
    """List chapters, optionally filtered by book title."""
    data_dir = _ensure_data_dir()
    db_path = data_dir / "pipeline.db"

    book_id = None
    if book:
        book_row = get_book_by_title(db_path, book)
        if not book_row:
            raise HTTPException(status_code=404, detail=f"Book '{book}' not found")
        book_id = book_row["id"]

    chapters = list_chapters(db_path, book_id=book_id)
    # Enrich with book title
    books = {b["id"]: b["title"] for b in list_books(db_path)}
    for ch in chapters:
        ch["book_title"] = books.get(ch["book_id"], "Unknown")
    return JSONResponse(content=chapters)


@app.get("/queue")
async def get_queue(status: str = Query("cleaned", pattern="^(cleaned|failed)$")):
    """Get translation queue (pending or failed chapters)."""
    data_dir = _ensure_data_dir()
    db_path = data_dir / "pipeline.db"
    if status == "cleaned":
        items = get_pending_chapters(db_path)
    else:
        items = get_failed_chapters(db_path)
    books = {b["id"]: b["title"] for b in list_books(db_path)}
    for it in items:
        it["book_title"] = books.get(it["book_id"], "Unknown")
    return JSONResponse(content=items)


@app.post("/translate/{chapter_id}")
async def translate_chapter_endpoint(chapter_id: int):
    """Translate a specific chapter by ID."""
    data_dir = _ensure_data_dir()
    db_path = data_dir / "pipeline.db"
    ch = get_chapter_by_id(db_path, chapter_id)
    if not ch:
        raise HTTPException(status_code=404, detail=f"Chapter {chapter_id} not found")
    book_row = get_book_by_id(db_path, ch["book_id"])
    if not book_row:
        raise HTTPException(status_code=404, detail=f"Book for chapter {chapter_id} not found")
    book_title = book_row["title"]

    # Determine source text
    if ch.get("cleaned_text_path") and Path(ch["cleaned_text_path"]).exists():
        source_path = Path(ch["cleaned_text_path"])
    elif ch.get("raw_text_path") and Path(ch["raw_text_path"]).exists():
        source_path = Path(ch["raw_text_path"])
    else:
        raise HTTPException(status_code=400, detail="No source text available")

    source_text = source_path.read_text(encoding="utf-8")
    translated = translate_chapter(
        text=source_text,
        book_title=book_title,
        chapter_title=ch["title"],
        chapter_number=ch["chapter_number"],
    )

    safe_book = "".join(c if c.isalnum() or c in "._-" else "_" for c in book_title)
    trans_path = data_dir / "translated" / safe_book / f"chapter_{ch['chapter_number']:04d}.txt"
    trans_path.parent.mkdir(parents=True, exist_ok=True)
    trans_path.write_text(translated, encoding="utf-8")

    update_chapter_paths(db_path, ch["id"], translated_text_path=trans_path, status="translated")

    return JSONResponse(
        content={
            "message": f"Translated chapter {chapter_id}",
            "translated_path": str(trans_path),
        }
    )


@app.post("/tts/{chapter_id}")
async def tts_chapter_endpoint(chapter_id: int, voice: Optional[str] = None, rate: str = "-5%"):
    """Generate audio for a specific chapter by ID."""
    data_dir = _ensure_data_dir()
    db_path = data_dir / "pipeline.db"
    ch = get_chapter_by_id(db_path, chapter_id)
    if not ch:
        raise HTTPException(status_code=404, detail=f"Chapter {chapter_id} not found")
    book_row = get_book_by_id(db_path, ch["book_id"])
    if not book_row:
        raise HTTPException(status_code=404, detail=f"Book for chapter {chapter_id} not found")
    book_title = book_row["title"]

    if not ch.get("translated_text_path") or not Path(ch["translated_text_path"]).exists():
        raise HTTPException(status_code=400, detail="No translated text available. Translate first.")

    translated_text = Path(ch["translated_text_path"]).read_text(encoding="utf-8")
    safe_book = "".join(c if c.isalnum() or c in "._-" else "_" for c in book_title)
    audio_dir = data_dir / "audio" / safe_book
    audio_dir.mkdir(parents=True, exist_ok=True)
    audio_path = audio_dir / f"chapter_{ch['chapter_number']:04d}.mp3"

    text_to_speech_file(
        text=translated_text,
        output_path=audio_path,
        book_title=book_title,
        chapter_number=ch["chapter_number"],
        chapter_title=ch["title"],
        voice=voice,
        rate=rate,
    )

    update_chapter_paths(db_path, ch["id"], audio_path=audio_path, status="audio_done")

    return JSONResponse(
        content={
            "message": f"Generated audio for chapter {chapter_id}",
            "audio_path": str(audio_path),
        }
    )


@app.get("/glossary")
async def get_pending_glossary_endpoint(book: Optional[str] = None):
    """Get pending glossary terms."""
    data_dir = _ensure_data_dir()
    db_path = data_dir / "pipeline.db"
    book_id = None
    if book:
        book_row = get_book_by_title(db_path, book)
        if not book_row:
            raise HTTPException(status_code=404, detail=f"Book '{book}' not found")
        book_id = book_row["id"]
    terms = get_pending_glossary(db_path, book_id or 0)
    return JSONResponse(content=terms)


@app.post("/glossary/approve/{term_id}")
async def approve_glossary_term_endpoint(term_id: int):
    """Approve a pending glossary term."""
    data_dir = _ensure_data_dir()
    db_path = data_dir / "pipeline.db"
    approve_glossary_term(db_path, term_id)
    return JSONResponse(content={"message": f"Approved term {term_id}"})


@app.post("/glossary/reject/{term_id}")
async def reject_glossary_term_endpoint(term_id: int):
    """Reject a pending glossary term."""
    data_dir = _ensure_data_dir()
    db_path = data_dir / "pipeline.db"
    reject_glossary_term(db_path, term_id)
    return JSONResponse(content={"message": f"Rejected term {term_id}"})


@app.get("/daily-report")
async def get_daily_report_endpoint(book: Optional[str] = None):
    """Get the latest daily report."""
    data_dir = _ensure_data_dir()
    db_path = data_dir / "pipeline.db"
    book_id = None
    if book:
        book_row = get_book_by_title(db_path, book)
        if not book_row:
            raise HTTPException(status_code=404, detail=f"Book '{book}' not found")
        book_id = book_row["id"]
    report = generate_daily_report(db_path, book_id=book_id)
    save_daily_report(db_path, report)
    return JSONResponse(content=report)


@app.post("/suggest")
async def suggest_translation(
    q: str = Query(..., description="Original source text"),
    s: str = Query(..., description="Suggested corrected translation"),
    source_lang: str = Query("zh", description="Source language code"),
    target_lang: str = Query("vi", description="Target language code"),
    book_id: int = Query(0, description="Book ID"),
    chapter_number: Optional[int] = Query(None, description="Chapter number"),
):
    """Submit a translation correction suggestion (like LibreTranslate /suggest).

    User submits original text (q) and corrected translation (s).
    Stored for review and glossary improvement.
    """
    if not q.strip() or not s.strip():
        raise HTTPException(status_code=400, detail="Both 'q' and 's' must be non-empty")
    data_dir = _ensure_data_dir()
    db_path = data_dir / "pipeline.db"
    add_translation_suggestion(db_path, q, s, source_lang, target_lang, book_id, chapter_number)
    return JSONResponse(content={"success": True})


@app.get("/cache/stats")
async def cache_stats_endpoint():
    """Get translation cache statistics."""
    data_dir = _ensure_data_dir()
    db_path = data_dir / "pipeline.db"
    stats = get_cache_stats(db_path)
    return JSONResponse(content=stats)


@app.post("/cache/clear")
async def cache_clear_endpoint():
    """Clear all cached translations."""
    data_dir = _ensure_data_dir()
    db_path = data_dir / "pipeline.db"
    count = clear_translation_cache(db_path)
    return JSONResponse(content={"cleared": count})


# Run the server
def start_server(host: str = "127.0.0.1", port: int = 8000):
    uvicorn.run(app, host=host, port=port)
