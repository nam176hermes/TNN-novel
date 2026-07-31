import { X } from 'lucide-react';
import ReaderAudioBar from './ReaderAudioBar';
import type { useReaderAudio } from './useReaderAudio';

export type ReaderAudioFeatureProps = {
  audio: ReturnType<typeof useReaderAudio>;
};

export default function ReaderAudioFeature({ audio }: ReaderAudioFeatureProps) {
  const { actions, playback, state } = audio;

  return (
    <>
      {state.bulkConfirmOpen ? (
        <div className="modal-backdrop">
          <section
            aria-label="Xác nhận tạo audiobook"
            className="dialog confirm-dialog reader-audio-confirm-dialog"
            role="dialog"
          >
            <div className="dialog-header">
              <div>
                <p className="section-label">Audiobook</p>
                <h2>Xác nhận tạo audiobook</h2>
              </div>
              <button
                aria-label="Đóng xác nhận tạo audiobook"
                className="reader-icon-button"
                onClick={actions.closeBulkConfirm}
                type="button"
              >
                <X aria-hidden="true" size={18} />
              </button>
            </div>
            <p>
              Job sẽ dùng pipeline TTS hiện có và bỏ qua chương đã có audio, trừ khi bạn tạo lại audio từng chương trong Advanced.
            </p>
            <div className="reader-audio-confirm-grid">
              <span>
                <strong>{state.translatedChapterCount.toLocaleString('vi-VN')} chương đã dịch</strong>
                <small>Sẵn sàng đưa vào job audio</small>
              </span>
              <span>
                <strong>{state.translatedAudioChapterCount.toLocaleString('vi-VN')} chương đã có audio</strong>
                <small>Sẽ được backend bỏ qua nếu không cần tạo lại</small>
              </span>
              <span>
                <strong>{state.missingTranslationChapterCount.toLocaleString('vi-VN')} chương thiếu bản dịch</strong>
                <small>Không thể tạo TTS cho các chương này</small>
              </span>
              <span>
                <strong>{state.missingAudioTranslatedChapterCount.toLocaleString('vi-VN')} chương cần tạo audio</strong>
                <small>Ước lượng theo playlist/audio metadata hiện có</small>
              </span>
            </div>
            <div className="dialog-actions">
              <button className="secondary-action" onClick={actions.closeBulkConfirm} type="button">
                Hủy
              </button>
              <button
                className="primary-action"
                disabled={!state.canStartBookJob}
                onClick={() => { void actions.confirmBookJob(); }}
                type="button"
              >
                Tạo audiobook
              </button>
            </div>
          </section>
        </div>
      ) : null}

      <ReaderAudioBar
        autoNext={state.autoNext}
        chapterTitle={playback.chapterTitle}
        downloadUrl={playback.downloadUrl}
        hasNextChapter={playback.hasNextChapter}
        open={state.open && Boolean(playback.url)}
        resumeOnSourceChange={playback.resumeOnSourceChange}
        streamUrl={playback.url}
        onAutoNextChange={actions.setAutoNext}
        onClose={actions.close}
        onNextChapter={actions.playNextChapter}
      />
    </>
  );
}
