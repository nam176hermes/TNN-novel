import httpx
import pytest

from app.database.db import init_db, get_connection, add_book
from app.mobile_api import main as main_mod
from app.mobile_api.routers.books import get_pipeline
from app.mobile_api.services.pipeline_service import PipelineService


@pytest.mark.asyncio
async def test_raw_backlog_pages_totals_and_batch_ids_exclude_translated_and_deleted(temp_db_path, tmp_path, monkeypatch):
    init_db(temp_db_path)
    first, second, deleted = [add_book(temp_db_path, name) for name in ("One", "Two", "Deleted")]
    with get_connection(temp_db_path) as conn:
        for book_id in (first, second, deleted):
            for number in range(1, 61):
                conn.execute("INSERT INTO chapters (book_id, chapter_number, title, raw_text_path) VALUES (?, ?, ?, ?)",
                             (book_id, number, f"Chapter {number}", str(tmp_path / 'private-source.txt')))
        conn.execute("DELETE FROM books WHERE id=?", (deleted,))
        conn.execute("UPDATE chapters SET translated_text_path='private-translation.txt' WHERE book_id=? AND chapter_number=1", (first,))
        conn.execute("UPDATE chapters SET deleted_at=CURRENT_TIMESTAMP WHERE book_id=? AND chapter_number=2", (first,))
        # Legacy translated statuses without a path are not raw in the existing UI.
        conn.execute("UPDATE chapters SET status='audio_done' WHERE book_id=? AND chapter_number=3", (first,))
    service = object.__new__(PipelineService)
    service.db_path, service.data_dir, service.legacy_artifact_root = temp_db_path, tmp_path, None
    monkeypatch.setattr(main_mod.mobile_settings, 'disable_auth', True)
    app = main_mod.create_app()
    app.dependency_overrides[get_pipeline] = lambda: service
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
            page = await client.get('/api/library/raw?limit=50')
            assert page.status_code == 200
            data = page.json()
            assert data['total_chapters'] == 117 and data['total_books'] == 2
            assert len(data['chapters']) == 50
            assert data['book_counts'][str(first)] == 57
            assert [c['chapter_number'] for c in data['chapters']] == list(range(4, 54))
            assert all(c['raw_text_path'] == 'available' for c in data['chapters'])
            middle = (await client.get('/api/library/raw?limit=50&offset=50')).json()
            assert middle['chapters'][0]['id'] != data['chapters'][0]['id']
            assert middle['first_chapter_ids'][str(first)] == data['chapters'][0]['id']
            last = (await client.get('/api/library/raw?limit=50&offset=100')).json()
            assert len(last['chapters']) == 17
            assert not ({c['id'] for c in data['chapters']} & {c['id'] for c in last['chapters']})
            filtered = (await client.get(f'/api/library/raw?book_id={second}&limit=50')).json()
            assert filtered['total_chapters'] == 60 and filtered['total_books'] == 1
            ids = (await client.get(f'/api/books/{first}/chapters/raw-ids')).json()
            assert len(ids) == 57 and ids[:50] == [c['id'] for c in data['chapters']]
            assert (await client.get('/api/library/raw?limit=500')).status_code == 422
            assert (await client.get(f'/api/books/{deleted}/chapters/raw-ids')).status_code == 404
    finally:
        app.dependency_overrides.pop(get_pipeline, None)
