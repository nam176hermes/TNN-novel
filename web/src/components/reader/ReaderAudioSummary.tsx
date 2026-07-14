import { Download, Volume2 } from 'lucide-react';
import type { useReaderAudio } from './useReaderAudio';

export type ReaderAudioSummaryProps = {
  audio: ReturnType<typeof useReaderAudio>;
  visible: boolean;
};

export default function ReaderAudioSummary({ audio, visible }: ReaderAudioSummaryProps) {
  const { actions, playback, state } = audio;
  const hasJobStatus = Boolean(state.jobId || state.status || state.error);
  const readinessWarning = state.missingAudioTranslatedChapterCount > 0
    ? `M4B chưa sẵn: còn ${state.missingAudioTranslatedChapterCount.toLocaleString('vi-VN')} chương đã dịch chưa có audio.`
    : '';

  return (
    <section aria-label="Audio và TTS chương" className="reader-audio-panel" data-visible={visible}>
      <div className="reader-audio-panel-main">
        <div>
          <span className={state.canPlay ? 'reader-audio-state is-ready' : 'reader-audio-state'}>
            {state.canPlay ? 'Audio có sẵn' : 'Chưa có audio'}
          </span>
          <strong>{playback.chapterTitle.split(' · ')[0]}</strong>
          <small>
            {state.canPlay
              ? 'Có thể nghe hoặc tải MP3 qua route được bảo vệ.'
              : 'Tạo audio từ bản dịch tiếng Việt của chương hiện tại.'}
          </small>
        </div>
        <div className="reader-audio-panel-actions">
          {state.canPlay ? (
            <>
              <button className="reader-menu-action" onClick={actions.open} type="button">
                <Volume2 aria-hidden="true" size={16} />
                Nghe audio
              </button>
              <a className="reader-menu-action" href={playback.downloadUrl}>
                <Download aria-hidden="true" size={16} />
                Tải MP3
              </a>
            </>
          ) : (
            <button
              className="reader-menu-action"
              disabled={!state.canStartChapterJob}
              onClick={() => { void actions.startChapterJob(); }}
              type="button"
            >
              <Volume2 aria-hidden="true" size={16} />
              {state.jobLoading ? 'Đang tạo...' : 'Tạo audio chương'}
            </button>
          )}
        </div>
      </div>
      {state.readinessWarnings.length > 0 ? (
        <ul className="reader-audio-warning-list">
          {state.readinessWarnings.map((warning) => <li key={warning}>{warning}</li>)}
        </ul>
      ) : null}
      {state.canPlay ? (
        <details className="reader-audio-advanced">
          <summary>Advanced</summary>
          <button
            className="reader-menu-action"
            disabled={!state.canStartChapterJob}
            onClick={() => { void actions.startChapterJob(); }}
            type="button"
          >
            <Volume2 aria-hidden="true" size={16} />
            {state.jobLoading ? 'Đang tạo lại...' : 'Tạo lại audio chương'}
          </button>
        </details>
      ) : null}
      {hasJobStatus ? (
        <section aria-label="Trạng thái audio" className="reader-audio-job-status" role="status">
          <div className="reader-audio-job-header">
            <strong>{state.jobId ? `Job ${state.jobKind} ${state.jobId.slice(0, 8)}` : 'Audio job'}</strong>
            {state.statusValue ? <span>{state.statusValue}</span> : null}
          </div>
          {state.progressPercent !== null ? (
            <div className="reader-audio-job-progress">
              <progress aria-label="Tiến độ job audio" max="100" value={state.progressPercent} />
              <span>{state.progressPercent}%</span>
            </div>
          ) : null}
          {state.jobSnapshot?.provider || state.jobSnapshot?.model ? (
            <div className="reader-audio-job-meta">
              {state.jobSnapshot.provider ? <span>{state.jobSnapshot.provider}</span> : null}
              {state.jobSnapshot.model ? <span>{state.jobSnapshot.model}</span> : null}
            </div>
          ) : null}
          {state.status ? <p className="reader-export-status">{state.status}</p> : null}
          {state.totalChunks > 0 || state.failedChunks > 0 ? (
            <div className="reader-audio-job-meta">
              {state.totalChunks > 0 ? <span>{state.completedChunks}/{state.totalChunks} chunks</span> : null}
              {state.failedChunks > 0 ? <span>{state.failedChunks} chunk lỗi</span> : null}
            </div>
          ) : null}
          {state.operationalWarnings.length > 0 ? (
            <ul className="reader-audio-warning-list">
              {state.operationalWarnings.map((warning) => <li key={warning}>{warning}</li>)}
            </ul>
          ) : null}
          {state.failureMessage ? <p className="reader-export-status status-error">{state.failureMessage}</p> : null}
          {state.jobId ? (
            <div className="reader-audio-job-actions">
              <button
                className="reader-menu-action"
                disabled={state.jobRefreshing}
                onClick={() => { void actions.refreshJob(); }}
                type="button"
              >
                {state.jobRefreshing ? 'Đang làm mới...' : 'Làm mới audio job'}
              </button>
              {state.canCancelJob ? (
                <button
                  className="reader-menu-action"
                  disabled={state.jobLoading}
                  onClick={() => { void actions.cancelJob(); }}
                  type="button"
                >
                  Hủy job audio
                </button>
              ) : null}
              {state.canRetryChunks ? (
                <button
                  className="reader-menu-action"
                  disabled={state.jobLoading}
                  onClick={() => { void actions.retryChunks(); }}
                  type="button"
                >
                  Chạy lại chunk lỗi
                </button>
              ) : null}
            </div>
          ) : null}
        </section>
      ) : null}
      {state.playlistError ? <p className="reader-export-status status-error">{state.playlistError}</p> : null}
      {readinessWarning ? <p className="reader-export-status">{readinessWarning}</p> : null}
    </section>
  );
}
