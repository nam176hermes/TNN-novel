import pytest
from pathlib import Path

from app.database.db import add_book, add_chapter, get_qa_report, get_chapter_by_id, get_connection, init_db, update_chapter_paths
from app.main import daily_cmd, retry_cmd, tts_cmd
from app.mobile_api.services.job_service import JobService
from app.mobile_api.services.pipeline_service import PipelineService


@pytest.mark.parametrize('command,status', [(daily_cmd, 'cleaned'), (retry_cmd, 'failed')])
def test_legacy_cli_publication_failure_preserves_current_translation(tmp_path, monkeypatch, command, status):
    db = tmp_path / 'pipeline.db'
    init_db(db)
    book = add_book(db, 'Fixture')
    source = tmp_path / 'raw.txt'
    source.write_text('源文本。')
    old = tmp_path / 'translated/Fixture/chapter_0001.txt'
    old.parent.mkdir(parents=True)
    old.write_text('Bản dịch đã lưu.')
    chapter = add_chapter(db, book, 1, 'Chapter', raw_text_path=source)
    update_chapter_paths(db, chapter, cleaned_text_path=source, translated_text_path=old, status=status)
    monkeypatch.setattr('app.main._ensure_data_dir', lambda: tmp_path)
    monkeypatch.setattr('app.main.translate_chapter', lambda **_: 'Bản dịch mới.')
    monkeypatch.setattr('app.main.run_qa_check', lambda *_args, **_kwargs: {'quality_score': 9})
    def reject(*_args, **_kwargs):
        raise RuntimeError('publication rejected')
    monkeypatch.setattr('app.storage.chapter_content.update_chapter_paths', reject)
    with pytest.raises(RuntimeError, match='publication rejected'):
        if command is daily_cmd:
            command(book='Fixture', limit=1, model=None, host=None)
        else:
            command(book='Fixture', chapter=1, model=None, host=None)
    assert old.read_text() == 'Bản dịch đã lưu.'


@pytest.mark.asyncio
async def test_background_qa_cannot_publish_a_report_after_an_edit(tmp_path, monkeypatch):
    db = tmp_path / 'pipeline.db'
    init_db(db)
    book = add_book(db, 'Fixture')
    chapter = add_chapter(db, book, 1, 'Chapter')
    pipeline = object.__new__(PipelineService)
    pipeline.db_path, pipeline.data_dir, pipeline.legacy_artifact_root = db, tmp_path, None
    pipeline.update_chapter_translation(chapter, 'Bản dịch đầu tiên.')
    def concurrent_edit(*_args, **_kwargs):
        pipeline.update_chapter_translation(chapter, 'Bản dịch sau khi chỉnh sửa.')
        return {'verdict': 'PASS', 'quality_score': 9, 'qa_complete': True}
    monkeypatch.setattr(pipeline, 'run_qa_check', concurrent_edit)
    service = JobService(pipeline)
    job = service.tracker.create_job('qa', [chapter], 1)
    await service._run_qa_job(job.job_id, [chapter], None, None, None, None)
    assert service.get_job_status(job.job_id)['status'] == 'failed'
    assert get_qa_report(db, book, chapter) is None


@pytest.mark.asyncio
async def test_background_failure_does_not_log_provider_content(tmp_path, caplog):
    from app.mobile_api.services.job_service import JobTracker
    db = tmp_path / 'pipeline.db'
    init_db(db)
    tracker = JobTracker(db_path=db)
    job = tracker.create_job('fixture', [], 1)
    async def fail():
        raise RuntimeError('PRIVATE_PROVIDER_PAYLOAD /private/source.txt')
    with caplog.at_level('ERROR'):
        task = tracker.start_background_task(job.job_id, fail())
        if task is not None:
            await task
        else:
            import asyncio
            for _ in range(30):
                if tracker.get_job(job.job_id).status == 'failed':
                    break
                await asyncio.sleep(.01)
    assert tracker.get_job(job.job_id).status == 'failed'
    assert 'PRIVATE_PROVIDER_PAYLOAD' not in caplog.text
    assert '/private/source.txt' not in caplog.text


def test_legacy_cli_audio_uses_versioned_publication_without_gpu_fallback(tmp_path, monkeypatch):
    from app.services.tts.tts_pipeline import TTSPipeline
    db = tmp_path / 'pipeline.db'
    init_db(db)
    book = add_book(db, 'Fixture')
    chapter = add_chapter(db, book, 1, 'Chapter')
    translation = tmp_path / 'translation.txt'
    translation.write_text('Bản dịch kiểm tra.')
    old = tmp_path / 'audio/Fixture/chapter_0001.mp3'
    old.parent.mkdir(parents=True)
    old.write_bytes(b'old audio')
    update_chapter_paths(db, chapter, translated_text_path=translation, audio_path=old)
    class Engine:
        def synthesize_chunk(self, _text, destination, **_options):
            destination.write_bytes(b'chunk fixture')
            return destination
    def merge(_paths, destination, **_options):
        destination.write_bytes(b'new audio fixture')
        return destination
    monkeypatch.setattr('app.main._ensure_data_dir', lambda: tmp_path)
    monkeypatch.setattr('app.services.tts.tts_pipeline.settings.tts_enable_qa', False)
    monkeypatch.setattr(TTSPipeline, '_build_engine', lambda *_: Engine())
    monkeypatch.setattr('app.services.tts.tts_pipeline.merge_chapter_audio', merge)
    tts_cmd(book='Fixture', chapter=1, voice=None, rate='-5%')
    current = get_chapter_by_id(db, chapter)
    assert Path(current['audio_path']) != old
    assert Path(current['audio_path']).read_bytes() == b'new audio fixture'
    assert current['audio_status'] == 'ready'
    with get_connection(db) as conn:
        assert conn.execute('SELECT provider FROM tts_jobs').fetchone()[0] == 'edge_tts'
        assert conn.execute('SELECT qa_status FROM tts_chunks').fetchone()[0] == 'skipped'


def test_repeated_legacy_import_keeps_the_current_raw_file(tmp_path, monkeypatch):
    from app.ingestion import importers
    db = tmp_path / 'pipeline.db'
    init_db(db)
    monkeypatch.setattr(importers, '_data_dir', lambda: tmp_path)
    first = importers._save_raw('Original source.', 'Fixture', 1, '../unsafe/title', 'file')
    with pytest.raises(ValueError, match='Duplicate'):
        importers._save_raw('Replacement source.', 'Fixture', 1, '../unsafe/title', 'file')
    assert first.read_text() == 'Original source.'
    assert list((tmp_path / 'raw').glob('*.txt')) == [first]


def test_repeated_url_note_does_not_replace_existing_source(tmp_path, monkeypatch):
    db = tmp_path / 'pipeline.db'
    init_db(db)
    book = add_book(db, 'Fixture')
    pipeline = object.__new__(PipelineService)
    pipeline.db_path, pipeline.data_dir = db, tmp_path
    monkeypatch.setattr('app.mobile_api.services.pipeline_service.time.time', lambda: 123)
    pipeline.add_url_note('Fixture', 'https://example.test', 'First note.')
    chapter = pipeline.list_chapters(book)[0]
    raw = Path(chapter['raw_text_path'])
    with pytest.raises(ValueError, match='Duplicate'):
        pipeline.add_url_note('Fixture', 'https://example.test', 'Different note.')
    assert 'First note.' in raw.read_text()
    assert list((tmp_path / 'raw').glob('*.txt')) == [raw]
