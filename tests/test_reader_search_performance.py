import pytest

from app.database.db import add_book, get_connection, init_db
from app.mobile_api.services.pipeline_service import PipelineService
from scripts.benchmark_database_library import _trace_call


def test_book_search_reuses_chapter_rows_and_reads_current_content(temp_db_path, tmp_path):
    init_db(temp_db_path)
    book_id = add_book(temp_db_path, "Search book")
    content_dir = tmp_path / "translated"
    content_dir.mkdir()
    paths = []
    with get_connection(temp_db_path) as conn:
        for number in range(1, 51):
            path = content_dir / f"{number}.txt"
            path.write_text("Một đoạn.\n\nLinh thạch sáng lên." if number % 2 else "Không có từ cần tìm.")
            paths.append(path)
            conn.execute("INSERT INTO chapters (book_id, chapter_number, title, translated_text_path) VALUES (?, ?, ?, ?)",
                         (book_id, number, f"Chapter {number}", str(path)))
    pipeline = object.__new__(PipelineService)
    pipeline.db_path, pipeline.data_dir, pipeline.legacy_artifact_root = temp_db_path, tmp_path, None
    search = lambda: pipeline.search_reader_book(book_id, query="linh thạch", scopes={"translation"}, whole_word=True)
    results, connections, queries = _trace_call(temp_db_path, search)
    assert [r["chapter_number"] for r in results] == list(range(1, 51, 2))
    assert all(r["paragraph_index"] == 1 and r["char_start"] == 0 and r["char_end"] == 10 for r in results)
    assert connections == 2 and len(queries) == 2
    paths[0].write_text("Nội dung đã sửa.")
    assert len(search()) == 24  # no stale text cache
    assert len(pipeline.search_reader_book(book_id, query="Linh.*sáng", scopes={"translation"}, regex=True)) == 24
    with pytest.raises(ValueError, match="Invalid search regex"):
        pipeline.search_reader_book(book_id, query="[", scopes={"translation"}, regex=True)
