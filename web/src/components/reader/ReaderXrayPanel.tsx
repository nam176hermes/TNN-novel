import { Gem, GitBranch, Loader2, ScrollText, Shield, Sparkles, Users, X, type LucideIcon } from 'lucide-react';
import { useMemo, useState } from 'react';
import type {
  ReaderXrayEntity,
  ReaderXrayEntityType,
  ReaderXrayFactionNode,
  ReaderXrayPowerRanking,
  ReaderXrayRelationship,
  ReaderXrayResponse,
  ReaderXraySpoilerMode,
  ReaderXrayTimelineEvent,
} from '../../api/types';

type ReaderXrayTab = 'characters' | 'relations' | 'factions' | 'power' | 'realms' | 'items' | 'timeline';

export type ReaderXrayPanelProps = {
  data: ReaderXrayResponse | null;
  enriching?: boolean;
  enrichingScope?: 'chapter' | 'book' | null;
  error: string;
  loading: boolean;
  open: boolean;
  spoilerMode: ReaderXraySpoilerMode;
  onClose(): void;
  onEnrich?(): void;
  onEnrichBook?(): void;
  onRetry(): void;
  onSpoilerModeChange(mode: ReaderXraySpoilerMode): void;
};

const tabs: Array<{ id: ReaderXrayTab; label: string; icon: LucideIcon }> = [
  { id: 'characters', label: 'Characters', icon: Users },
  { id: 'relations', label: 'Relations', icon: GitBranch },
  { id: 'factions', label: 'Factions', icon: Shield },
  { id: 'power', label: 'Power', icon: Shield },
  { id: 'realms', label: 'Realms', icon: GitBranch },
  { id: 'items', label: 'Items', icon: Gem },
  { id: 'timeline', label: 'Timeline', icon: ScrollText },
];

const tabEntityTypes: Record<'characters' | 'realms' | 'items', ReaderXrayEntityType[]> = {
  characters: ['character'],
  realms: ['realm', 'skill'],
  items: ['item', 'location'],
};

function typeLabel(type: ReaderXrayEntityType): string {
  if (type === 'character') return 'Nhân vật';
  if (type === 'faction') return 'Thế lực';
  if (type === 'location') return 'Địa danh';
  if (type === 'item') return 'Vật phẩm';
  if (type === 'realm') return 'Cảnh giới';
  return 'Kỹ năng';
}

function metadataText(value: unknown): string {
  if (value === null || value === undefined) return '';
  if (typeof value === 'string') return value.trim();
  if (typeof value === 'number' || typeof value === 'boolean') return String(value);
  if (Array.isArray(value)) {
    return value
      .map((item) => metadataText(item))
      .filter(Boolean)
      .join(', ');
  }
  if (typeof value === 'object') {
    const record = value as Record<string, unknown>;
    return metadataText(record.name ?? record.label ?? record.title ?? record.value);
  }
  return '';
}

function metadataFirst(metadata: Record<string, unknown>, ...keys: string[]): string {
  for (const key of keys) {
    const text = metadataText(metadata[key]);
    if (text) return text;
  }
  return '';
}

function metadataRows(entity: ReaderXrayEntity): Array<{ label: string; value: string }> {
  const metadata = entity.metadata ?? {};
  const rows: Array<{ label: string; value: string }> = [];

  function add(label: string, ...keys: string[]): void {
    const value = metadataFirst(metadata, ...keys);
    if (value) rows.push({ label, value });
  }

  if (entity.type === 'item') {
    add('Chủ sở hữu', 'owner', 'owners', 'wielder');
    add('Loại', 'category');
    add('Cấp bậc', 'grade', 'rank');
    add('Công dụng', 'effect');
    add('Nguồn gốc', 'origin');
    add('Thế lực', 'faction', 'sect', 'organization');
    return rows;
  }

  if (entity.type === 'skill') {
    add('Người dùng', 'user', 'users', 'owner');
    add('Loại', 'category');
    add('Yêu cầu/cảnh giới', 'realm');
    add('Cấp bậc', 'grade', 'rank');
    add('Công dụng', 'effect');
    add('Thế lực', 'faction', 'sect', 'organization');
    return rows;
  }

  if (entity.type === 'realm') {
    add('Thứ tự', 'order', 'rank');
    add('Cảnh giới trước', 'previous');
    add('Cảnh giới sau', 'next');
    add('Hệ cảnh giới', 'parent', 'category');
    add('Bằng chứng', 'evidence');
    return rows;
  }

  if (entity.type === 'location') {
    add('Khu vực', 'region', 'parent');
    add('Thế lực', 'faction', 'sect', 'organization');
    add('Vai trò', 'category', 'role');
  }

  return rows;
}

function EntityList({ entities }: { entities: ReaderXrayEntity[] }) {
  if (entities.length === 0) return <p className="reader-xray-empty">Chưa có dữ liệu trong phạm vi hiện tại.</p>;

  return (
    <div className="reader-xray-list">
      {entities.map((entity) => {
        const rows = metadataRows(entity);
        return (
          <article className="reader-xray-card" key={entity.id}>
            <header>
              <div>
                <strong>{entity.name}</strong>
                <span>{typeLabel(entity.type)} · {entity.mention_count.toLocaleString('vi-VN')} mention</span>
              </div>
              <small>Ch. {entity.first_chapter_number || '-'}</small>
            </header>
            {entity.aliases.length > 0 ? <p className="reader-xray-aliases">{entity.aliases.join(', ')}</p> : null}
            {entity.description ? <p>{entity.description}</p> : null}
            {rows.length > 0 ? (
              <dl className="reader-xray-metadata">
                {rows.map((row) => (
                  <div key={`${entity.id}-${row.label}`}>
                    <dt>{row.label}</dt>
                    <dd>{row.label}: {row.value}</dd>
                  </div>
                ))}
              </dl>
            ) : null}
            {entity.mentions.length > 0 ? (
              <ul className="reader-xray-mentions">
                {entity.mentions.slice(0, 3).map((mention) => (
                  <li key={mention.id}>
                    <span>Ch. {mention.chapter_number}</span>
                    <p>{mention.context || mention.mention_text}</p>
                  </li>
                ))}
              </ul>
            ) : null}
          </article>
        );
      })}
    </div>
  );
}

function TimelineList({ events }: { events: ReaderXrayTimelineEvent[] }) {
  if (events.length === 0) return <p className="reader-xray-empty">Chưa có timeline trong phạm vi hiện tại.</p>;

  return (
    <div className="reader-xray-list">
      {events.map((event) => (
        <article className="reader-xray-card" key={event.id}>
          <header>
            <div>
              <strong>{event.title}</strong>
              <span>Ch. {event.chapter_number}</span>
            </div>
            <small>#{event.event_order || 1}</small>
          </header>
          {event.summary ? <p>{event.summary}</p> : null}
          {event.entities.length > 0 ? <p className="reader-xray-aliases">{event.entities.join(', ')}</p> : null}
        </article>
      ))}
    </div>
  );
}

function RelationshipList({ relationships }: { relationships: ReaderXrayRelationship[] }) {
  if (relationships.length === 0) return <p className="reader-xray-empty">Chưa có quan hệ trong phạm vi hiện tại.</p>;

  return (
    <div className="reader-xray-list">
      {relationships.map((relationship, index) => (
        <article className="reader-xray-card" key={`${relationship.source}-${relationship.target}-${index}`}>
          <header>
            <div>
              <strong>{relationship.source} -&gt; {relationship.target}</strong>
              <span>{relationship.relation}</span>
            </div>
            <small>Ch. {relationship.chapter_number || '-'}</small>
          </header>
          {relationship.evidence ? <p>{relationship.evidence}</p> : null}
          <p className="reader-xray-aliases">
            {relationship.source_type} · {Math.round(relationship.strength * 100)}%
          </p>
        </article>
      ))}
    </div>
  );
}

function FactionTreeList({ factions }: { factions: ReaderXrayFactionNode[] }) {
  if (factions.length === 0) return <p className="reader-xray-empty">Chưa có cây thế lực trong phạm vi hiện tại.</p>;

  return (
    <div className="reader-xray-list">
      {factions.map((faction) => (
        <article className="reader-xray-card" key={faction.name}>
          <header>
            <div>
              <strong>{faction.name}</strong>
              <span>{faction.parent || 'Không rõ thượng cấp'}</span>
            </div>
            <small>Ch. {faction.first_chapter_number || '-'}</small>
          </header>
          {faction.description ? <p>{faction.description}</p> : null}
          {faction.members.length > 0 ? (
            <ul className="reader-xray-mentions">
              {faction.members.map((member) => (
                <li key={member}>
                  <span>Môn nhân</span>
                  <p>{member}</p>
                </li>
              ))}
            </ul>
          ) : null}
          {faction.children.length > 0 ? (
            <p className="reader-xray-aliases">Chi nhánh: {faction.children.join(', ')}</p>
          ) : null}
        </article>
      ))}
    </div>
  );
}

function PowerRankingList({ rankings }: { rankings: ReaderXrayPowerRanking[] }) {
  if (rankings.length === 0) return <p className="reader-xray-empty">Chưa có bảng thực lực trong phạm vi hiện tại.</p>;

  return (
    <div className="reader-xray-list">
      {rankings.map((ranking) => (
        <article className="reader-xray-card" key={`${ranking.name}-${ranking.rank}`}>
          <header>
            <div>
              <strong>{ranking.name}</strong>
              <span>#{ranking.rank} · {ranking.label || typeLabel(ranking.type as ReaderXrayEntityType)}</span>
            </div>
            <small>Ch. {ranking.chapter_number || '-'}</small>
          </header>
          {ranking.basis ? <p>{ranking.basis}</p> : null}
          {ranking.faction ? <p className="reader-xray-aliases">{ranking.faction}</p> : null}
        </article>
      ))}
    </div>
  );
}

export default function ReaderXrayPanel({
  data,
  enriching = false,
  enrichingScope = null,
  error,
  loading,
  open,
  spoilerMode,
  onClose,
  onEnrich,
  onEnrichBook,
  onRetry,
  onSpoilerModeChange,
}: ReaderXrayPanelProps) {
  const [activeTab, setActiveTab] = useState<ReaderXrayTab>('characters');
  const filteredEntities = useMemo(() => {
    if (!data || !(activeTab in tabEntityTypes)) return [];
    const allowedTypes = tabEntityTypes[activeTab as keyof typeof tabEntityTypes];
    return data.entities.filter((entity) => allowedTypes.includes(entity.type));
  }, [activeTab, data]);

  if (!open) return null;

  return (
    <div className="reader-drawer-backdrop">
      <aside aria-label="X-Ray truyện" className="reader-xray-panel" role="dialog">
        <header className="reader-drawer-header">
          <div>
            <p className="section-label">X-Ray</p>
            <h2>Hồ sơ truyện</h2>
            <span>
              {spoilerMode === 'no_spoiler'
                ? `No spoiler${data?.current_chapter_number ? ` · tới Ch. ${data.current_chapter_number}` : ''}`
                : 'Toàn bộ sách'}
            </span>
          </div>
          <button
            aria-label="Đóng X-Ray"
            className="reader-icon-button"
            onClick={onClose}
            title="Đóng X-Ray"
            type="button"
          >
            <X aria-hidden="true" size={22} />
          </button>
        </header>

        <div aria-label="Chế độ spoiler X-Ray" className="segmented-control reader-xray-spoiler" role="group">
          <button
            aria-pressed={spoilerMode === 'no_spoiler'}
            onClick={() => onSpoilerModeChange('no_spoiler')}
            type="button"
          >
            No spoiler
          </button>
          <button
            aria-pressed={spoilerMode === 'allow_spoiler'}
            onClick={() => onSpoilerModeChange('allow_spoiler')}
            type="button"
          >
            Toàn bộ sách
          </button>
        </div>

        <div className="reader-xray-enrich-actions">
          {onEnrich ? (
            <button
              className="secondary-action"
              disabled={loading || enriching}
              onClick={onEnrich}
              type="button"
            >
              {enriching && enrichingScope !== 'book'
                ? <Loader2 aria-hidden="true" size={15} />
                : <Sparkles aria-hidden="true" size={15} />}
              {enriching && enrichingScope !== 'book' ? 'Đang làm giàu chương...' : 'Làm giàu chương'}
            </button>
          ) : null}
          {onEnrichBook ? (
            <button
              className="secondary-action"
              disabled={loading || enriching}
              onClick={onEnrichBook}
              type="button"
            >
              {enriching && enrichingScope === 'book'
                ? <Loader2 aria-hidden="true" size={15} />
                : <Sparkles aria-hidden="true" size={15} />}
              {enriching && enrichingScope === 'book' ? 'Đang làm giàu toàn sách...' : 'Làm giàu toàn sách'}
            </button>
          ) : null}
        </div>

        <div aria-label="Mục X-Ray" className="reader-xray-tabs" role="tablist">
          {tabs.map((tab) => {
            const Icon = tab.icon;
            return (
              <button
                aria-selected={activeTab === tab.id}
                key={tab.id}
                onClick={() => setActiveTab(tab.id)}
                role="tab"
                type="button"
              >
                <Icon aria-hidden="true" size={15} />
                {tab.label}
              </button>
            );
          })}
        </div>

        <section className="reader-xray-body" aria-label="Nội dung X-Ray">
          {loading ? (
            <p className="reader-xray-loading">
              <Loader2 aria-hidden="true" size={16} />
              Đang tải X-Ray...
            </p>
          ) : null}
          {error ? (
            <div className="reader-ai-error" role="alert">
              <p>{error}</p>
              <button className="secondary-action" onClick={onRetry} type="button">
                Thử lại
              </button>
            </div>
          ) : null}
          {!loading && !error && activeTab === 'timeline' ? (
            <TimelineList events={data?.timeline ?? []} />
          ) : null}
          {!loading && !error && activeTab === 'relations' ? (
            <RelationshipList relationships={data?.relationships ?? []} />
          ) : null}
          {!loading && !error && activeTab === 'factions' ? (
            <FactionTreeList factions={data?.faction_tree ?? []} />
          ) : null}
          {!loading && !error && activeTab === 'power' ? (
            <PowerRankingList rankings={data?.power_rankings ?? []} />
          ) : null}
          {!loading && !error && (activeTab === 'characters' || activeTab === 'realms' || activeTab === 'items') ? (
            <EntityList entities={filteredEntities} />
          ) : null}
        </section>
      </aside>
    </div>
  );
}
