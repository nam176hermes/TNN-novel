import { Languages, RotateCcw, ShieldCheck, Volume2 } from 'lucide-react';
import type { Chapter } from '../api/types';

type Props = {
  chapters: Chapter[];
  selectedChapterId: number | null;
  onSelectChapter: (chapterId: number) => void;
  onTranslate?: (chapterId: number) => void;
  onRunQa?: (chapterId: number) => void;
  onGenerateTts?: (chapterId: number) => void;
  onRetry?: (chapterId: number) => void;
};

function formatStatus(status: string): string {
  return status
    .split(/[_-]/)
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(' ');
}

function formatQa(score?: number): string {
  return typeof score === 'number' ? `QA ${score}` : 'No QA';
}

export default function ChapterTable({
  chapters,
  selectedChapterId,
  onSelectChapter,
  onTranslate,
  onRunQa,
  onGenerateTts,
  onRetry,
}: Props) {
  return (
    <section aria-labelledby="chapter-table-title" className="chapter-table panel">
      <div className="panel-header">
        <div>
          <p className="section-label">Pipeline</p>
          <h3 id="chapter-table-title">Chapters</h3>
        </div>
      </div>

      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              <th>Chapter</th>
              <th>Status</th>
              <th>QA</th>
              <th>Audio</th>
              <th>Last action</th>
              <th>Provider</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {chapters.map((chapter) => (
              <tr aria-selected={chapter.id === selectedChapterId} key={chapter.id}>
                <th scope="row">
                  <button className="row-button" onClick={() => onSelectChapter(chapter.id)} type="button">
                    <span className="chapter-number">Ch. {chapter.chapter_number}</span>
                    <span>{chapter.title}</span>
                  </button>
                </th>
                <td>
                  <span className={`status-pill status-${chapter.status.toLowerCase().replace(/\s+/g, '-')}`}>
                    {formatStatus(chapter.status)}
                  </span>
                </td>
                <td>{formatQa(chapter.qa_score)}</td>
                <td>{chapter.audio_path ? 'Audio Done' : 'No audio'}</td>
                <td>{chapter.last_action ?? 'Not started'}</td>
                <td>{chapter.latest_provider ? `${chapter.latest_provider} · ${chapter.latest_model ?? 'default'}` : 'Unassigned'}</td>
                <td>
                  <div className="table-actions">
                    <button onClick={() => onTranslate?.(chapter.id)} type="button">
                      <Languages aria-hidden="true" size={15} />
                      Translate
                    </button>
                    <button onClick={() => onRunQa?.(chapter.id)} type="button">
                      <ShieldCheck aria-hidden="true" size={15} />
                      Run QA
                    </button>
                    <button onClick={() => onGenerateTts?.(chapter.id)} type="button">
                      <Volume2 aria-hidden="true" size={15} />
                      Generate TTS
                    </button>
                    {chapter.status === 'failed' ? (
                      <button onClick={() => onRetry?.(chapter.id)} type="button">
                        <RotateCcw aria-hidden="true" size={15} />
                        Retry
                      </button>
                    ) : null}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
