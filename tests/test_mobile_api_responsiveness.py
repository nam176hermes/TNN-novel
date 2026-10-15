"""Slow synchronous work must not stop unrelated requests on the API loop."""
import asyncio
import threading
from types import SimpleNamespace

import httpx
import pytest

from app.mobile_api import main as main_mod
from app.mobile_api.routers import books, exports, import_routes, qa


@pytest.mark.asyncio
@pytest.mark.parametrize("dependency,method,url,payload,service_method,result", [
    (books.get_pipeline, "GET", "/api/books/1/dictionary/lookup?q=word", None,
     "lookup_reader_dictionary", {"sources": []}),
    (books.get_pipeline, "PATCH", "/api/books/1/reader/progress", {"chapter_id": 1},
     "save_reader_progress", {"chapter_id": 1}),
    (books.get_pipeline, "GET", "/api/books/1/search?q=word", None,
     "search_reader_book", []),
    (qa.get_qa_service, "POST", "/api/books/1/chapters/1/qa/run", None,
     "run_qa_check", {"overall_status": "PASS"}),
    (import_routes.get_pipeline, "POST", "/api/import/paste", {"title": "Book", "text": "Synthetic text"},
     "import_from_text", {"book_id": 1, "chapter_id": 1}),
    (exports.get_export_service, "POST", "/api/books/1/exports", {"format": "txt"},
     "export_book", {"book_id": 1, "book_title": "Book", "filename": "book.txt", "format": "txt",
                     "media_type": "text/plain", "size_bytes": 10, "chapter_count": 1}),
])
async def test_health_completes_while_sync_service_is_waiting(
    monkeypatch, dependency, method, url, payload, service_method, result,
):
    started, release, finished = threading.Event(), threading.Event(), threading.Event()

    def slow_work(*args, **kwargs):
        started.set()
        release.wait(timeout=1)
        finished.set()
        return result

    service = SimpleNamespace(**{service_method: slow_work})
    monkeypatch.setattr(main_mod.mobile_settings, "disable_auth", True)
    app = main_mod.create_app()
    app.dependency_overrides[dependency] = lambda: service
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            request = asyncio.create_task(client.request(method, url, json=payload))
            try:
                assert await asyncio.to_thread(started.wait, 2)
                health = await asyncio.wait_for(client.get("/api/health"), timeout=.5)
                assert health.status_code == 200
                assert not finished.is_set(), "The route blocked the API loop until synchronous work finished"
            finally:
                release.set()
                response = await request
            assert response.status_code == 200
    finally:
        app.dependency_overrides.pop(dependency, None)
