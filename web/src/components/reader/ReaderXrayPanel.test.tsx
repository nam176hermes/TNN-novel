import { cleanup, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { ReaderXrayResponse } from '../../api/types';
import ReaderXrayPanel from './ReaderXrayPanel';

const noSpoilerData: ReaderXrayResponse = {
  book_id: 42,
  current_chapter_number: 2,
  spoiler_mode: 'no_spoiler',
  entities: [
    {
      id: 1,
      book_id: 42,
      type: 'character',
      name: 'Hàn Lập',
      aliases: ['韓立'],
      description: 'Nhân vật chính.',
      first_chapter_number: 1,
      importance: 100,
      metadata: {},
      mention_count: 1,
      mentions: [
        {
          id: 10,
          chapter_id: 101,
          chapter_number: 1,
          paragraph_index: 0,
          mention_text: 'Hàn Lập',
          context: 'Hàn Lập rời thôn.',
          spoiler_level: 0,
        },
      ],
    },
    {
      id: 2,
      book_id: 42,
      type: 'realm',
      name: 'Trúc Cơ',
      aliases: ['筑基'],
      description: 'Cảnh giới tu luyện.',
      first_chapter_number: 2,
      importance: 70,
      metadata: {},
      mention_count: 1,
      mentions: [],
    },
    {
      id: 3,
      book_id: 42,
      type: 'faction',
      name: 'Thất Huyền Môn',
      aliases: [],
      description: 'Tông môn thu nhận đệ tử ngoại viện.',
      first_chapter_number: 1,
      importance: 85,
      metadata: {},
      mention_count: 1,
      mentions: [],
    },
  ],
  relationships: [
    {
      source: 'Hàn Lập',
      target: 'Trúc Cơ',
      relation: 'cảnh giới hiện tại',
      evidence: 'Hàn Lập được trưởng lão nhắc tới ngưỡng Trúc Cơ.',
      chapter_number: 2,
      strength: 0.9,
      source_type: 'metadata',
    },
  ],
  faction_tree: [
    {
      name: 'Thất Huyền Môn',
      description: 'Tông môn thu nhận đệ tử ngoại viện.',
      parent: 'Việt Quốc tu tiên giới',
      first_chapter_number: 1,
      members: ['Hàn Lập'],
      children: [],
    },
  ],
  power_rankings: [
    {
      name: 'Hàn Lập',
      type: 'character',
      rank: 20,
      label: 'Trúc Cơ sơ kỳ',
      basis: 'Được trưởng lão xác nhận đã chạm ngưỡng Trúc Cơ.',
      chapter_number: 1,
      faction: 'Thất Huyền Môn',
    },
  ],
  timeline: [
    {
      id: 20,
      chapter_id: 101,
      chapter_number: 1,
      event_order: 1,
      title: 'Hàn Lập rời thôn',
      summary: 'Hàn Lập bắt đầu rời Sơn biên tiểu thôn.',
      spoiler_level: 0,
      entities: ['Hàn Lập'],
    },
  ],
};

describe('ReaderXrayPanel', () => {
  afterEach(() => {
    cleanup();
  });

  it('does not render when closed', () => {
    render(
      <ReaderXrayPanel
        data={noSpoilerData}
        error=""
        loading={false}
        open={false}
        spoilerMode="no_spoiler"
        onClose={vi.fn()}
        onRetry={vi.fn()}
        onSpoilerModeChange={vi.fn()}
      />,
    );

    expect(screen.queryByRole('dialog', { name: 'X-Ray truyện' })).not.toBeInTheDocument();
  });

  it('shows guarded entity tabs and timeline', async () => {
    const onSpoilerModeChange = vi.fn();
    render(
      <ReaderXrayPanel
        data={noSpoilerData}
        error=""
        loading={false}
        open
        spoilerMode="no_spoiler"
        onClose={vi.fn()}
        onRetry={vi.fn()}
        onSpoilerModeChange={onSpoilerModeChange}
      />,
    );

    const panel = screen.getByRole('dialog', { name: 'X-Ray truyện' });
    expect(within(panel).getByText('No spoiler · tới Ch. 2')).toBeInTheDocument();
    expect(within(panel).getByText('Hàn Lập')).toBeInTheDocument();
    expect(within(panel).queryByText('Lệ Phi Vũ')).not.toBeInTheDocument();

    await userEvent.click(within(panel).getByRole('tab', { name: /Realms/ }));
    expect(within(panel).getByText('Trúc Cơ')).toBeInTheDocument();

    await userEvent.click(within(panel).getByRole('tab', { name: /Timeline/ }));
    expect(within(panel).getByText('Hàn Lập rời thôn')).toBeInTheDocument();

    await userEvent.click(within(panel).getByRole('button', { name: 'Toàn bộ sách' }));
    expect(onSpoilerModeChange).toHaveBeenCalledWith('allow_spoiler');
  });

  it('shows relationship graph, faction tree, and power rankings', async () => {
    render(
      <ReaderXrayPanel
        data={noSpoilerData}
        error=""
        loading={false}
        open
        spoilerMode="no_spoiler"
        onClose={vi.fn()}
        onRetry={vi.fn()}
        onSpoilerModeChange={vi.fn()}
      />,
    );

    const panel = screen.getByRole('dialog', { name: 'X-Ray truyện' });

    await userEvent.click(within(panel).getByRole('tab', { name: /Relations/ }));
    expect(within(panel).getByText('Hàn Lập -> Trúc Cơ')).toBeInTheDocument();
    expect(within(panel).getByText('cảnh giới hiện tại')).toBeInTheDocument();

    await userEvent.click(within(panel).getByRole('tab', { name: /Factions/ }));
    expect(within(panel).getByText('Thất Huyền Môn')).toBeInTheDocument();
    expect(within(panel).getByText('Việt Quốc tu tiên giới')).toBeInTheDocument();
    expect(within(panel).getByText('Hàn Lập')).toBeInTheDocument();

    await userEvent.click(within(panel).getByRole('tab', { name: /Power/ }));
    expect(within(panel).getByText('#20 · Trúc Cơ sơ kỳ')).toBeInTheDocument();
    expect(within(panel).getByText('Được trưởng lão xác nhận đã chạm ngưỡng Trúc Cơ.')).toBeInTheDocument();
  });

  it('shows AI-enriched item, skill, and realm metadata instead of only generic entity cards', async () => {
    const enrichedData: ReaderXrayResponse = {
      ...noSpoilerData,
      entities: [
        ...noSpoilerData.entities,
        {
          id: 4,
          book_id: 42,
          type: 'item',
          name: 'Thanh Trúc Phong Vân Kiếm',
          aliases: [],
          description: 'Pháp khí kiếm tu.',
          first_chapter_number: 2,
          importance: 75,
          metadata: {
            owner: 'Hàn Lập',
            category: 'pháp khí',
            grade: 'thượng phẩm',
            effect: 'phá trận và ngự kiếm',
          },
          mention_count: 1,
          mentions: [],
        },
        {
          id: 5,
          book_id: 42,
          type: 'skill',
          name: 'Ngự Kiếm Thuật',
          aliases: [],
          description: 'Kiếm quyết dùng để điều khiển phi kiếm.',
          first_chapter_number: 2,
          importance: 70,
          metadata: {
            user: 'Hàn Lập',
            category: 'kiếm quyết',
            realm: 'Luyện Khí',
            effect: 'điều khiển pháp khí từ xa',
          },
          mention_count: 1,
          mentions: [],
        },
        {
          id: 6,
          book_id: 42,
          type: 'realm',
          name: 'Luyện Khí',
          aliases: [],
          description: 'Cảnh giới nhập môn.',
          first_chapter_number: 1,
          importance: 65,
          metadata: {
            order: 1,
            next: 'Trúc Cơ',
            evidence: 'Được nhắc là tầng nhập môn trước Trúc Cơ.',
          },
          mention_count: 1,
          mentions: [],
        },
      ],
    };

    render(
      <ReaderXrayPanel
        data={enrichedData}
        error=""
        loading={false}
        open
        spoilerMode="no_spoiler"
        onClose={vi.fn()}
        onRetry={vi.fn()}
        onSpoilerModeChange={vi.fn()}
      />,
    );

    const panel = screen.getByRole('dialog', { name: 'X-Ray truyện' });

    await userEvent.click(within(panel).getByRole('tab', { name: /Items/ }));
    expect(within(panel).getByText('Thanh Trúc Phong Vân Kiếm')).toBeInTheDocument();
    expect(within(panel).getByText('Chủ sở hữu: Hàn Lập')).toBeInTheDocument();
    expect(within(panel).getByText('Công dụng: phá trận và ngự kiếm')).toBeInTheDocument();
    expect(within(panel).getByText('Cấp bậc: thượng phẩm')).toBeInTheDocument();

    await userEvent.click(within(panel).getByRole('tab', { name: /Realms/ }));
    expect(within(panel).getByText('Ngự Kiếm Thuật')).toBeInTheDocument();
    expect(within(panel).getByText('Người dùng: Hàn Lập')).toBeInTheDocument();
    expect(within(panel).getByText('Yêu cầu/cảnh giới: Luyện Khí')).toBeInTheDocument();
    expect(within(panel).getByText('Luyện Khí')).toBeInTheDocument();
    expect(within(panel).getByText('Thứ tự: 1')).toBeInTheDocument();
    expect(within(panel).getByText('Cảnh giới sau: Trúc Cơ')).toBeInTheDocument();
  });

  it('can trigger chapter AI enrichment from the panel', async () => {
    const onEnrich = vi.fn();
    render(
      <ReaderXrayPanel
        data={noSpoilerData}
        error=""
        loading={false}
        open
        spoilerMode="no_spoiler"
        onClose={vi.fn()}
        onEnrich={onEnrich}
        onRetry={vi.fn()}
        onSpoilerModeChange={vi.fn()}
      />,
    );

    const panel = screen.getByRole('dialog', { name: 'X-Ray truyện' });
    await userEvent.click(within(panel).getByRole('button', { name: 'Làm giàu chương' }));
    expect(onEnrich).toHaveBeenCalledTimes(1);
  });

  it('can trigger whole-book AI enrichment from the panel', async () => {
    const onEnrichBook = vi.fn();
    render(
      <ReaderXrayPanel
        data={noSpoilerData}
        error=""
        loading={false}
        open
        spoilerMode="no_spoiler"
        onClose={vi.fn()}
        onEnrich={vi.fn()}
        onEnrichBook={onEnrichBook}
        onRetry={vi.fn()}
        onSpoilerModeChange={vi.fn()}
      />,
    );

    const panel = screen.getByRole('dialog', { name: 'X-Ray truyện' });
    await userEvent.click(within(panel).getByRole('button', { name: 'Làm giàu toàn sách' }));
    expect(onEnrichBook).toHaveBeenCalledTimes(1);
  });

  it('disables manual AI enrichment while it is running', () => {
    render(
      <ReaderXrayPanel
        data={noSpoilerData}
        enriching
        error=""
        loading={false}
        open
        spoilerMode="no_spoiler"
        onClose={vi.fn()}
        onEnrich={vi.fn()}
        onRetry={vi.fn()}
        onSpoilerModeChange={vi.fn()}
      />,
    );

    expect(screen.getByRole('button', { name: 'Đang làm giàu chương...' })).toBeDisabled();
  });

  it('shows loading and retry on error', async () => {
    const onRetry = vi.fn();
    const { rerender } = render(
      <ReaderXrayPanel
        data={null}
        error=""
        loading
        open
        spoilerMode="no_spoiler"
        onClose={vi.fn()}
        onRetry={onRetry}
        onSpoilerModeChange={vi.fn()}
      />,
    );
    expect(screen.getByText('Đang tải X-Ray...')).toBeInTheDocument();

    rerender(
      <ReaderXrayPanel
        data={null}
        error="Failed to load reader X-Ray"
        loading={false}
        open
        spoilerMode="no_spoiler"
        onClose={vi.fn()}
        onRetry={onRetry}
        onSpoilerModeChange={vi.fn()}
      />,
    );
    await userEvent.click(screen.getByRole('button', { name: 'Thử lại' }));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });
});
