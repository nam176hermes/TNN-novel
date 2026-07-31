import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { SourceAdapterCandidateList, SourceCatalogList } from '../api/types';
import SourcesView from './SourcesView';

const sources = [
  {
    source_id: '69shuba',
    label: '69shuba',
    domains: ['69shuba.com', '69shuba.cx', '69shux.com'],
    adapter_id: '69shuba',
    adapter_label: '69shuba',
    extraction: 'selector',
    direct_import: true,
    delay_seconds: 8,
    max_concurrency: 1,
    retry_limit: 2,
    notes: 'Parser rieng cho layout hien tai.',
  },
  {
    source_id: '22biqu',
    label: '22biqu',
    domains: ['22biqu.com'],
    adapter_id: 'biquge',
    adapter_label: 'Biquge',
    extraction: 'selector',
    direct_import: true,
    delay_seconds: 10,
    max_concurrency: 1,
    retry_limit: 2,
    notes: 'Parser rieng cho layout hien tai.',
  },
];

const catalog: SourceCatalogList = {
  items: [
    {
      id: 'catalog-supported',
      external_id: '100',
      catalog_source: 'yckceo',
      name: '69 Catalog',
      url: 'https://www.69shuba.com/book/1',
      domain: 'www.69shuba.com',
      author: 'Catalog Author',
      downloads: 120,
      version: '1',
      raw_tags: '搜',
      tags: ['search'],
      unknown_tags: [],
      supported: true,
      supported_status: 'supported',
      supported_source_id: '69shuba',
      invalid_reason: '',
      updated_label: '2026-07-07',
      created_at: '',
      updated_at: '',
      last_check_status: '',
      last_check_at: '',
      last_check_error: '',
      last_check_http_status: null,
      last_check_final_url: '',
      managed_source_id: '',
      managed_status: '',
      managed_trust_level: '',
      managed_last_test_status: '',
      managed_last_tested_at: '',
      managed_last_successful_fetch_at: '',
      managed_last_error: '',
      managed_rate_limit_requests_per_minute: 0,
      managed_rate_limit_delay_ms: 0,
      managed_max_concurrent_requests: 0,
      managed_cooldown_after_error_seconds: 0,
      managed_notes: '',
      managed_parser_type: '',
      managed_language: '',
      can_use_in_jobs: false,
    },
    {
      id: 'catalog-unsupported',
      external_id: '200',
      catalog_source: 'yckceo',
      name: 'Unsupported Catalog',
      url: 'https://unsupported.example/source',
      domain: 'unsupported.example',
      author: '',
      downloads: 4,
      version: '',
      raw_tags: '图',
      tags: ['manga'],
      unknown_tags: [],
      supported: false,
      supported_status: 'unsupported',
      supported_source_id: '',
      invalid_reason: '',
      updated_label: '',
      created_at: '',
      updated_at: '',
      last_check_status: '',
      last_check_at: '',
      last_check_error: '',
      last_check_http_status: null,
      last_check_final_url: '',
      managed_source_id: 'src-unsupported',
      managed_status: 'BLOCKED',
      managed_trust_level: 'MANUAL_ONLY',
      managed_last_test_status: '',
      managed_last_tested_at: '',
      managed_last_successful_fetch_at: '',
      managed_last_error: 'blocked',
      managed_rate_limit_requests_per_minute: 6,
      managed_rate_limit_delay_ms: 10000,
      managed_max_concurrent_requests: 1,
      managed_cooldown_after_error_seconds: 300,
      managed_notes: '',
      managed_parser_type: 'generic_html',
      managed_language: 'zh-CN',
      can_use_in_jobs: false,
    },
  ],
  entries: [],
  total: 2,
  page: 1,
  per_page: 25,
  page_size: 25,
};

const candidates: SourceAdapterCandidateList = {
  items: [
    {
      id: 'cand-1',
      catalog_entry_id: 'catalog-supported',
      domain: 'www.69shuba.com',
      sample_url: 'https://www.69shuba.com/book/1',
      detected_title: '69 Candidate Novel',
      detected_chapter_list: [{ title: 'Chapter 1', url: 'https://www.69shuba.com/book/1/c1' }],
      parser_confidence: 'medium',
      failure_reason: '',
      status: 'needs_review',
      created_at: '2026-07-07T00:00:00+00:00',
      updated_at: '2026-07-07T00:00:00+00:00',
      reviewed_at: '',
      reviewed_by: '',
    },
  ],
  total: 1,
  page: 1,
  page_size: 50,
};

describe('SourcesView', () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it('renders backend source domains as real external links', () => {
    render(<SourcesView error="" onRefresh={() => undefined} sources={sources} state="ready" />);

    expect(screen.getByRole('heading', { name: 'Nguồn truyện' })).toBeInTheDocument();

    const firstRow = screen.getByRole('row', { name: /69shuba 69shuba\.com/i });
    expect(within(firstRow).getByRole('link', { name: '69shuba.com' })).toHaveAttribute('href', 'https://69shuba.com');
    expect(within(firstRow).getByRole('link', { name: '69shuba.cx' })).toHaveAttribute('href', 'https://69shuba.cx');

    const secondRow = screen.getByRole('row', { name: /22biqu 22biqu\.com/i });
    expect(within(secondRow).getByRole('link', { name: '22biqu.com' })).toHaveAttribute('href', 'https://22biqu.com');
    expect(within(secondRow).getByText('10s delay · 1 concurrent · 2 retries')).toBeInTheDocument();
  });

  it('refreshes source capabilities on demand', async () => {
    const onRefresh = vi.fn();
    render(<SourcesView error="" onRefresh={onRefresh} sources={[]} state="empty" />);

    await userEvent.click(screen.getByRole('button', { name: 'Làm mới' }));

    expect(onRefresh).toHaveBeenCalledOnce();
  });

  it('opens the primary source domain from the row action', async () => {
    const openSpy = vi.spyOn(window, 'open').mockImplementation(() => null);
    render(<SourcesView error="" onRefresh={() => undefined} sources={sources} state="ready" />);

    await userEvent.click(screen.getByRole('button', { name: 'Mở domain chính 69shuba' }));

    expect(openSpy).toHaveBeenCalledWith('https://69shuba.com', '_blank', 'noopener,noreferrer');
  });

  it('renders mobile card layouts for supported sources and catalog entries', async () => {
    const originalMatchMedia = window.matchMedia;
    Object.defineProperty(window, 'matchMedia', {
      configurable: true,
      value: vi.fn().mockImplementation((query: string) => ({
        addEventListener: vi.fn(),
        addListener: vi.fn(),
        dispatchEvent: vi.fn(),
        matches: query === '(max-width: 760px)',
        media: query,
        onchange: null,
        removeEventListener: vi.fn(),
        removeListener: vi.fn(),
      })),
    });
    try {
      const loadCatalog = vi.fn().mockResolvedValue(catalog);
      const { container } = render(
        <SourcesView
          error=""
          loadCatalog={loadCatalog}
          onRefresh={() => undefined}
          sources={sources}
          state="ready"
        />,
      );

      await waitFor(() => {
        expect(container.querySelectorAll('.source-support-card').length).toBe(sources.length);
      });

      await userEvent.click(screen.getByRole('button', { name: 'Kho nguồn' }));
      await screen.findByRole('row', { name: /69 Catalog/i });

      expect(container.querySelectorAll('.source-catalog-card').length).toBe(catalog.items.length);
    } finally {
      Object.defineProperty(window, 'matchMedia', {
        configurable: true,
        value: originalMatchMedia,
      });
    }
  });

  it('shows loading and error states honestly', () => {
    render(<SourcesView error="Failed to load" onRefresh={() => undefined} sources={[]} state="error" />);

    expect(screen.getByRole('alert')).toHaveTextContent('Failed to load');
  });

  it('renders source catalog rows with supported and unsupported badges', async () => {
    const loadCatalog = vi.fn().mockResolvedValue(catalog);
    render(<SourcesView error="" importCatalogSources={vi.fn()} loadCatalog={loadCatalog} onRefresh={() => undefined} sources={sources} state="ready" />);

    await userEvent.click(screen.getByRole('button', { name: 'Kho nguồn' }));

    await waitFor(() => expect(loadCatalog).toHaveBeenCalledWith(expect.objectContaining({ page: 1, page_size: 25 })));
    const supportedRow = await screen.findByRole('row', { name: /69 Catalog/i });
    const unsupportedRow = screen.getByRole('row', { name: /Unsupported Catalog/i });

    expect(within(supportedRow).getByText('supported')).toBeInTheDocument();
    expect(within(supportedRow).getByText('UNMANAGED')).toBeInTheDocument();
    expect(within(supportedRow).getByText('search')).toBeInTheDocument();
    expect(within(unsupportedRow).getByText('unsupported')).toBeInTheDocument();
    expect(within(unsupportedRow).getByText('BLOCKED')).toBeInTheDocument();
    expect(within(supportedRow).getByRole('button', { name: 'Import source metadata 69 Catalog' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /bulk import|nhập hàng loạt/i })).not.toBeInTheDocument();
  });

  it('calls the catalog API when search and filter controls change', async () => {
    const loadCatalog = vi.fn().mockResolvedValue(catalog);
    render(<SourcesView error="" loadCatalog={loadCatalog} onRefresh={() => undefined} sources={sources} state="ready" />);

    await userEvent.click(screen.getByRole('button', { name: 'Kho nguồn' }));
    await userEvent.type(screen.getByLabelText('Tìm nguồn'), '69 source');
    await userEvent.selectOptions(screen.getByLabelText('Tag'), 'search');
    await userEvent.selectOptions(screen.getByLabelText('Hỗ trợ'), 'true');

    await waitFor(() =>
      expect(loadCatalog).toHaveBeenLastCalledWith(
        expect.objectContaining({
          query: '69 source',
          tag: 'search',
          supported: 'true',
          page: 1,
          page_size: 25,
        }),
      ),
    );
  });

  it('supports multi-select copy actions without adding bulk import', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, 'clipboard', {
      configurable: true,
      value: { writeText },
    });
    const loadCatalog = vi.fn().mockResolvedValue(catalog);
    render(<SourcesView error="" loadCatalog={loadCatalog} onRefresh={() => undefined} sources={sources} state="ready" />);

    await userEvent.click(screen.getByRole('button', { name: 'Kho nguồn' }));
    await screen.findByRole('row', { name: /69 Catalog/i });
    await userEvent.click(screen.getByRole('checkbox', { name: 'Chọn nguồn 69 Catalog' }));

    await userEvent.click(screen.getByRole('button', { name: 'Sao chép URL đã chọn' }));

    expect(writeText).toHaveBeenCalledWith('https://www.69shuba.com/book/1');
    expect(screen.getByText('Đã sao chép URL đã chọn.')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /bulk import|nhập hàng loạt/i })).not.toBeInTheDocument();
  });

  it('imports selected catalog metadata and verifies a managed source', async () => {
    const loadCatalog = vi.fn().mockResolvedValue(catalog);
    const importCatalogSources = vi.fn().mockResolvedValue({
      selected: 1,
      inserted: 1,
      duplicates: 0,
      invalid: 0,
      skipped: 0,
      items: [
        {
          id: 'src-verified',
          catalog_entry_id: 'catalog-supported',
          name: '69 Catalog',
          base_url: 'https://www.69shuba.com/book/1',
          domain: 'www.69shuba.com',
          language: 'zh-CN',
          parser_type: 'policy_supported',
          parser_config: {},
          status: 'NEEDS_REVIEW',
          trust_level: 'MANUAL_ONLY',
          supported_source_id: '69shuba',
          last_test_status: '',
          last_tested_at: '',
          last_successful_fetch_at: '',
          last_error: '',
          rate_limit_requests_per_minute: 7,
          rate_limit_delay_ms: 8000,
          max_concurrent_requests: 1,
          cooldown_after_error_seconds: 300,
          notes: '',
          created_at: '',
          updated_at: '',
          can_use_in_jobs: false,
        },
      ],
    });
    const verifyManagedSource = vi.fn().mockResolvedValue({
      id: 'src-verified',
      catalog_entry_id: 'catalog-supported',
      name: '69 Catalog',
      base_url: 'https://www.69shuba.com/book/1',
      domain: 'www.69shuba.com',
      language: 'zh-CN',
      parser_type: 'policy_supported',
      parser_config: {},
      status: 'VERIFIED',
      trust_level: 'HIGH',
      supported_source_id: '69shuba',
      last_test_status: 'success',
      last_tested_at: '2026-07-09T00:00:00+00:00',
      last_successful_fetch_at: '2026-07-09T00:00:00+00:00',
      last_error: '',
      rate_limit_requests_per_minute: 7,
      rate_limit_delay_ms: 8000,
      max_concurrent_requests: 1,
      cooldown_after_error_seconds: 300,
      notes: '',
      created_at: '',
      updated_at: '',
      can_use_in_jobs: true,
    });
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true);
    render(
      <SourcesView
        error=""
        importCatalogSources={importCatalogSources}
        loadCatalog={loadCatalog}
        onRefresh={() => undefined}
        sources={sources}
        state="ready"
        verifyManagedSource={verifyManagedSource}
      />,
    );

    await userEvent.click(screen.getByRole('button', { name: 'Kho nguồn' }));
    const row = await screen.findByRole('row', { name: /69 Catalog/i });
    await userEvent.click(within(row).getByRole('button', { name: 'Import source metadata 69 Catalog' }));

    await waitFor(() => expect(importCatalogSources).toHaveBeenCalledWith(['catalog-supported']));
    expect(confirmSpy).toHaveBeenCalled();
    expect(await within(row).findByText('NEEDS_REVIEW')).toBeInTheDocument();

    await userEvent.click(within(row).getByRole('button', { name: 'Verify managed source 69 Catalog' }));
    await waitFor(() => expect(verifyManagedSource).toHaveBeenCalledWith('src-verified'));
    expect(await within(row).findByText('VERIFIED')).toBeInTheDocument();
    expect(within(row).getByText(/Jobs: enabled/i)).toBeInTheDocument();
  });

  it('checks one catalog source and renders friendly health status', async () => {
    const loadCatalog = vi.fn().mockResolvedValue(catalog);
    const checkCatalogSource = vi.fn().mockResolvedValue({
      catalog_entry_id: 'catalog-supported',
      domain: 'www.69shuba.com',
      status: 'reachable',
      reason: 'ok',
      checked_at: '2026-07-07T00:00:00+00:00',
      final_url: 'https://www.69shuba.com/book/1',
      http_status: 200,
    });
    render(
      <SourcesView
        checkCatalogSource={checkCatalogSource}
        error=""
        loadCatalog={loadCatalog}
        onRefresh={() => undefined}
        sources={sources}
        state="ready"
      />,
    );

    await userEvent.click(screen.getByRole('button', { name: 'Kho nguồn' }));
    const row = await screen.findByRole('row', { name: /69 Catalog/i });

    await userEvent.click(within(row).getByRole('button', { name: 'Check source 69 Catalog' }));

    expect(checkCatalogSource).toHaveBeenCalledWith('catalog-supported');
    expect(await screen.findByText('reachable')).toBeInTheDocument();
    expect(screen.getByText(/Last checked:/)).toHaveTextContent('2026-07-07');
  });

  it('renders parser candidates tab with review warning', async () => {
    const loadParserCandidates = vi.fn().mockResolvedValue(candidates);
    render(
      <SourcesView
        error=""
        loadParserCandidates={loadParserCandidates}
        onRefresh={() => undefined}
        sources={sources}
        state="ready"
      />,
    );

    await userEvent.click(screen.getByRole('button', { name: 'Ứng viên parser' }));

    await waitFor(() => expect(loadParserCandidates).toHaveBeenCalledOnce());
    expect(await screen.findByText('69 Candidate Novel')).toBeInTheDocument();
    expect(screen.getByText('needs_review')).toBeInTheDocument();
    expect(screen.getByText(/Ứng viên parser chưa phải nguồn được hỗ trợ/i)).toBeInTheDocument();
  });

  it('creates a parser candidate from a catalog row without showing import action', async () => {
    const loadCatalog = vi.fn().mockResolvedValue(catalog);
    const createParserCandidate = vi.fn().mockResolvedValue(candidates.items[0]);
    render(
      <SourcesView
        createParserCandidate={createParserCandidate}
        error=""
        loadCatalog={loadCatalog}
        onRefresh={() => undefined}
        sources={sources}
        state="ready"
      />,
    );

    await userEvent.click(screen.getByRole('button', { name: 'Kho nguồn' }));
    const row = await screen.findByRole('row', { name: /69 Catalog/i });
    await userEvent.click(within(row).getByRole('button', { name: 'Create parser candidate 69 Catalog' }));

    expect(createParserCandidate).toHaveBeenCalledWith('catalog-supported');
    expect(await screen.findByText(/Đã tạo parser candidate/)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /import using existing supported flow/i })).not.toBeInTheDocument();
  });
});
