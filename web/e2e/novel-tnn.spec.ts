import { expect, type Page, type Route, test } from '@playwright/test';

const API_ORIGIN = 'http://127.0.0.1:7860';
const RAW_TEXT = '第10章 螟是苑\n\n天逐渐转凉，刚柔却安而常生，动乎险中，水墨飞。';
const VI_TEXT = 'Chương mười, Minh Thị Uyển.\n\nTrời dần trở lạnh, khí tức trong núi lặng đi.';

type MockState = {
  imported: boolean;
  translated: boolean;
  translateRequests: unknown[];
};

const book = {
  id: 42,
  title: 'Audit Book',
  author: 'Audit Author',
  source: 'manual',
  source_url: '',
  created_at: '2026-06-30T00:00:00Z',
  updated_at: '2026-06-30T00:00:00Z',
};

const rawChapter = {
  id: 4201,
  book_id: 42,
  chapter_number: 10,
  title: '第10章 螟是苑',
  status: 'cleaned',
  source_url: 'https://www.69shuba.com/book/1/10',
  raw_text_path: null,
  cleaned_text_path: '/tmp/audit-cleaned.txt',
  translated_text_path: null,
  content_html_path: null,
  audio_path: null,
  translated_at: null,
  audio_created_at: null,
};

const translatedChapter = {
  ...rawChapter,
  status: 'translated',
  translated_text_path: '/tmp/audit-translated.txt',
  translated_at: '2026-06-30T00:00:00Z',
};

const importedChapter = {
  ...rawChapter,
  id: 4202,
  chapter_number: 11,
  title: 'Imported Chapter',
  source_url: '',
};

const provider = {
  id: 'gemini',
  label: 'Gemini',
  base_url: 'https://generativelanguage.googleapis.com/v1beta/openai',
  model: 'gemini-live',
  api_key_env: 'GEMINI_API_KEY',
  api_key_set: true,
  temperature: 0.2,
  timeout_seconds: 60,
  supports_streaming: 1,
  supports_batch: 0,
  cost_input_per_1m: 0.1,
  cost_output_per_1m: 0.4,
  enabled: 1,
  notes: 'Mocked by Playwright',
};

const styleProfile = {
  id: 'tien_hiep',
  label: 'Tiên hiệp',
  pronoun_rules: 'ta/ngươi',
  han_viet_level: 'high',
  preferred_terms: 'tu luyện, cảnh giới',
  banned_modern_terms: 'tôi, bạn',
  prompt_rules: 'Văn phong cổ trang.',
  is_default: 1,
};

function json(route: Route, body: unknown, status = 200, headers: Record<string, string> = {}) {
  return route.fulfill({
    status,
    contentType: 'application/json',
    headers,
    body: JSON.stringify(body),
  });
}

function text(route: Route, body: string, contentType = 'text/plain; charset=utf-8', headers: Record<string, string> = {}) {
  return route.fulfill({
    status: 200,
    contentType,
    headers: {
      'access-control-expose-headers': 'content-disposition',
      ...headers,
    },
    body,
  });
}

function eventStream(route: Route, events: unknown[]) {
  return route.fulfill({
    status: 200,
    contentType: 'text/event-stream',
    body: events.map((event) => `data: ${JSON.stringify(event)}\n\n`).join(''),
  });
}

function chaptersFor(state: MockState) {
  const chapters = [state.translated ? translatedChapter : rawChapter];
  if (state.imported) chapters.push(importedChapter);
  return chapters;
}

function translatedBooksFor(state: MockState) {
  if (!state.translated) {
    return { books: [] };
  }
  return {
    books: [
      {
        id: book.id,
        title: book.title,
        author: book.author,
        source: book.source,
        source_url: book.source_url,
        total_chapters: 1,
        translated_chapters: 1,
        audio_chapters: 0,
        failed_chapters: 0,
        qa_low_chapters: 0,
        first_translated_chapter_id: translatedChapter.id,
        latest_translated_chapter_id: translatedChapter.id,
        latest_chapter_number: translatedChapter.chapter_number,
        latest_chapter_title: translatedChapter.title,
        last_activity: book.updated_at,
        cover_url: '',
      },
    ],
  };
}

async function installApiMock(page: Page, state: MockState) {
  await page.route(`${API_ORIGIN}/api/**`, async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;

    if (path === '/api/auth/login' && request.method() === 'POST') {
      return json(route, { access_token: 'access-token', refresh_token: 'refresh-token', token_type: 'bearer' }, 200, {
        'set-cookie': 'novel_asset_access=asset-token; HttpOnly; Secure; SameSite=Lax; Path=/',
      });
    }

    if (path === '/api/auth/logout' && request.method() === 'POST') return json(route, { ok: true });
    if (path === '/api/providers') return json(route, { providers: [provider] });
    if (path === '/api/providers/usage') {
      return json(route, {
        usage: {
          total_prompt_tokens: 0,
          total_completion_tokens: 0,
          total_tokens: 0,
          total_estimated_cost_usd: 0,
        },
      });
    }
    if (path === '/api/providers/estimate') {
      return json(route, {
        provider_id: 'gemini',
        model: 'gemini-live',
        chapter_count: 1,
        estimated_input_tokens: 1000,
        estimated_output_tokens: 1200,
        estimated_cost_usd: 0.001,
        within_budget: true,
      });
    }
    if (path === '/api/style-profiles') return json(route, { profiles: [styleProfile] });
    if (path === '/api/books') return json(route, [book]);
    if (path === `/api/books/${book.id}/chapters`) return json(route, chaptersFor(state));
    if (path === '/api/library/books') return json(route, translatedBooksFor(state));
    if (path === '/api/import/ebook/history') return json(route, { runs: [] });
    if (path === '/api/import/ebook/inbox') return json(route, { directory: 'inbox/ebooks', files: [] });
    if (path === '/api/import/paste' && request.method() === 'POST') {
      state.imported = true;
      return json(route, {
        book_id: book.id,
        chapter_id: importedChapter.id,
        title: book.title,
        chapter_number: importedChapter.chapter_number,
        chapter_title: importedChapter.title,
        message: 'Imported',
      });
    }
    if (path === '/api/import/wizard/text' && request.method() === 'POST') {
      state.imported = true;
      return json(route, {
        book_id: book.id,
        title: book.title,
        content_kind: 'raw',
        chapter_count: 1,
        imported_chapters: 1,
        skipped_chapters: 0,
        overwritten_chapters: 0,
        chapter_ids: [importedChapter.id],
        warnings: [],
        message: 'Imported reviewed text',
      });
    }
    if (path === `/api/books/${book.id}/chapters/${rawChapter.id}/source`) {
      return json(route, { chapter_id: rawChapter.id, text: RAW_TEXT });
    }
    if (path === `/api/books/${book.id}/chapters/${importedChapter.id}/source`) {
      return json(route, { chapter_id: importedChapter.id, text: 'Imported source text' });
    }
    if (path === `/api/books/${book.id}/chapters/${rawChapter.id}/translation`) {
      return state.translated
        ? json(route, { chapter_id: rawChapter.id, text: VI_TEXT })
        : json(route, { detail: 'Not found' }, 404);
    }
    if (path === `/api/books/${book.id}/chapters/${importedChapter.id}/translation`) {
      return json(route, { detail: 'Not found' }, 404);
    }
    if (path === `/api/books/${book.id}/chapters/${rawChapter.id}/content`) {
      return json(route, { detail: 'Not found' }, 404);
    }
    if (path === `/api/books/${book.id}/chapters/${rawChapter.id}/qa`) {
      return json(route, { detail: 'No QA report yet' }, 404);
    }
    if (path === `/api/glossary`) return json(route, { items: [] });
    if (path === '/api/jobs/translate' && request.method() === 'POST') {
      state.translateRequests.push(JSON.parse(request.postData() ?? '{}'));
      state.translated = true;
      return json(route, { job_id: 'job-translate', status: 'pending', message: 'Translation job started' });
    }
    if (path === '/api/jobs/job-translate/events') {
      return eventStream(route, [
        { job_id: 'job-translate', status: 'running', progress: 0, total: 1, message: 'Translating' },
        { job_id: 'job-translate', status: 'completed', progress: 1, total: 1, message: 'Done' },
      ]);
    }
    if (path === '/api/jobs/job-translate/attempts') return json(route, { attempts: [] });
    if (path === '/api/jobs') return json(route, { jobs: [] });
    if (path === `/api/books/${book.id}/reader/state`) return json(route, { progress: null, annotations: [] });
    if (path === `/api/books/${book.id}/reader/sync`) {
      return json(route, { progress: null, annotations: [], conflicts: [], server_time: '2026-06-30T00:00:00Z' });
    }
    if (path === `/api/books/${book.id}/audio/playlist`) return json(route, { book_id: book.id, book_title: book.title, chapters: [] });
    if (path === `/api/books/${book.id}/dictionary/pack`) {
      return json(route, { book_id: book.id, chapter_id: null, entries: [], source_count: 0, generated_at: '2026-06-30T00:00:00Z' });
    }
    if (path === `/api/books/${book.id}/reader/xray`) {
      return json(route, { book_id: book.id, chapter_id: rawChapter.id, entities: [], relationships: [], timeline: [] });
    }
    if (path === '/api/reader/dictionaries') return json(route, { dictionaries: [] });
    if (path === `/api/books/${book.id}/exports` && request.method() === 'POST') {
      return json(route, {
        book_id: book.id,
        book_title: book.title,
        format: 'txt',
        filename: 'Audit_Book.txt',
        path: '',
        media_type: 'text/plain',
        size_bytes: 42,
        chapter_count: 1,
      });
    }
    if (path === `/api/books/${book.id}/exports/txt/download`) {
      return text(route, VI_TEXT, 'text/plain; charset=utf-8', {
        'content-disposition': "attachment; filename*=UTF-8''Audit_Book.txt",
      });
    }

    return json(route, { detail: `Unhandled mock route: ${request.method()} ${path}` }, 501);
  });
}

async function signIn(page: Page, state: MockState) {
  await installApiMock(page, state);
  await page.goto('/');
  await page.getByLabel('Password').fill('correct horse battery staple');
  await expect(page.getByRole('button', { name: 'Login' })).toHaveCSS('min-height', '48px');
  await page.getByRole('button', { name: 'Login' }).click();
  await expect(page.getByRole('navigation', { name: 'Quy trình' })).toBeVisible();
}

async function authenticatedPage(page: Page, state: MockState) {
  await installApiMock(page, state);
  await page.addInitScript(() => {
    localStorage.setItem('novel-operator-token', 'access-token');
  });
  await page.goto('/');
  const viewport = page.viewportSize();
  const navigationName = viewport && viewport.width < 900
    ? 'Điều hướng chính trên di động'
    : 'Quy trình';
  await expect(page.getByRole('navigation', { name: navigationName })).toBeVisible();
}

test('login works and protected shell is blocked without a token', async ({ page }) => {
  const state: MockState = { imported: false, translated: true, translateRequests: [] };
  await installApiMock(page, state);

  await page.goto('/');
  await expect(page.getByRole('heading', { name: 'Novel-TNN Translator' })).toBeVisible();
  await expect(page.getByRole('navigation', { name: 'Quy trình' })).toHaveCount(0);

  await page.getByLabel('Password').fill('correct horse battery staple');
  await page.getByRole('button', { name: 'Login' }).click();

  await expect(page.getByRole('navigation', { name: 'Quy trình' })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Chưa chọn chương' })).toBeVisible();
});

test('desktop provider table keeps the compact reference sizing', async ({ page }) => {
  const state: MockState = { imported: false, translated: true, translateRequests: [] };
  await authenticatedPage(page, state);

  await page.getByRole('navigation', { name: 'Quy trình' }).getByRole('button', { name: 'Model API' }).click();
  const providerTable = page.getByRole('table');
  await expect(providerTable).toBeVisible();
  await expect(providerTable).toHaveCSS('min-width', '660px');
  await expect(providerTable).toHaveCSS('font-size', '11.5px');
});

test('import wizard loads the current paste flow with mocked backend data', async ({ page }) => {
  const state: MockState = { imported: false, translated: true, translateRequests: [] };
  await signIn(page, state);

  await page.getByRole('navigation', { name: 'Quy trình' }).getByRole('button', { name: 'Nhập chương' }).click();
  await expect(page.getByRole('heading', { name: 'Dán chương nguồn' })).toBeVisible();
  const wizardSteps = page.getByRole('list', { name: 'Các bước nhập' });
  await expect(wizardSteps).toContainText('Chọn nguồn');
  await expect(wizardSteps.locator('li').first()).toHaveCSS('display', 'grid');
  await expect(wizardSteps.locator('li').first().locator('strong')).toHaveCSS('display', 'block');
  const importMode = page.getByLabel('Chế độ nhập');
  await expect(importMode.getByRole('button', { name: 'Dán văn bản', exact: true })).toBeVisible();
  await expect(importMode.getByRole('button', { name: 'Tải file', exact: true })).toBeVisible();
  await expect(importMode.getByRole('button', { name: 'Ebook bản dịch', exact: true })).toBeVisible();
  await expect(importMode.getByRole('button', { name: 'URL', exact: true })).toBeVisible();
  await expect(importMode.getByRole('button', { name: 'Kho nguồn', exact: true })).toBeVisible();

  await page.getByLabel('Book title').fill(book.title);
  await page.getByLabel('Chapter number').fill('11');
  await page.getByLabel('Chapter title').fill(importedChapter.title);
  await page.getByLabel('Source text').fill('第11章 Imported Chapter\n\n少年跟着大叔入镇。');
  await expect(page.getByRole('region', { name: 'Wizard structure preview' })).toBeVisible();
  await expect(page.getByText('Step 3 · Làm sạch & preview')).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Đích import và hành động' })).toBeVisible();
  await expect(page.getByLabel('Content mode')).toHaveValue('raw');
  await expect(page.getByRole('button', { name: 'Import chapter' })).toBeEnabled();
});

test('starts a translation job from a raw chapter', async ({ page }) => {
  const state: MockState = { imported: false, translated: false, translateRequests: [] };
  await authenticatedPage(page, state);

  await page.getByRole('navigation', { name: 'Quy trình' }).getByRole('button', { name: 'Raw chưa dịch' }).click();
  await expect(page.getByRole('heading', { name: 'Raw chưa dịch' })).toBeVisible();
  await page.getByRole('button', { name: /Mở bàn dịch\s+Audit Book\s+chương\s+10/ }).click();
  await expect(page.getByRole('heading', { name: rawChapter.title })).toBeVisible();
  await expect(page.getByText(RAW_TEXT.split('\n\n')[1])).toBeVisible();

  await page.getByRole('button', { name: 'Dịch', exact: true }).click();

  await expect(page.getByText('Done')).toBeVisible();
  await expect.poll(() => state.translateRequests.length).toBe(1);
  expect(state.translateRequests[0]).toMatchObject({
    book_id: book.id,
    chapter_ids: [rawChapter.id],
    params: { preset_id: 'balanced', style_profile_id: 'tien_hiep' },
  });
});

test('reader shows Vietnamese text and workbench exposes raw/Vietnamese controls', async ({ page }) => {
  const state: MockState = { imported: false, translated: true, translateRequests: [] };
  await authenticatedPage(page, state);

  await page.getByRole('navigation', { name: 'Quy trình' }).getByRole('button', { name: 'Thư viện' }).click();
  await expect(page.getByRole('heading', { name: 'Thư viện' })).toBeVisible();
  await page.getByRole('button', { name: `Đọc tiếp ${book.title}` }).click();
  await expect(page.getByText('Trời dần trở lạnh')).toBeVisible();

  await page.getByRole('button', { name: 'Thêm tùy chọn' }).click();
  await page.getByRole('button', { name: 'Mở bàn dịch' }).click();
  await expect(page.getByText('Bản gốc tiếng Trung')).toBeVisible();
  await expect(page.getByLabel('Bản dịch tiếng Việt')).toHaveValue(VI_TEXT);
  await page.getByRole('button', { name: 'Ẩn bản dịch' }).click();
  await expect(page.getByLabel('Bản dịch tiếng Việt')).toHaveCount(0);
});

test('mobile shell and Reader follow the approved handoff at 390px and 360px', async ({ page }) => {
  const state: MockState = { imported: false, translated: true, translateRequests: [] };
  await page.setViewportSize({ width: 390, height: 844 });
  await authenticatedPage(page, state);

  const mobileNav = page.getByRole('navigation', { name: 'Điều hướng chính trên di động' });
  await expect(mobileNav).toBeVisible();
  await expect(mobileNav.getByRole('button')).toHaveCount(5);
  await expect(mobileNav.getByRole('button', { name: 'Thêm' })).toBeVisible();
  await mobileNav.getByRole('button', { name: 'Thêm' }).click();
  const moreSheet = page.getByRole('dialog', { name: 'Thêm' });
  await expect(moreSheet).toContainText('Quản lý');
  await expect(moreSheet).toContainText('Hệ thống');
  await expect(moreSheet).toContainText('Tài khoản');
  await moreSheet.getByRole('button', { name: 'Đóng menu Thêm' }).click();

  await mobileNav.getByRole('button', { name: 'Thư viện' }).click();
  await expect(page.getByRole('heading', { name: 'Thư viện' })).toBeVisible();
  await page.getByRole('button', { name: `Đọc tiếp ${book.title}` }).click();

  await expect(page.getByRole('button', { name: 'Quay lại thư viện' })).toContainText('Thư viện');
  await expect(mobileNav).toBeHidden();
  await expect(page.getByRole('button', { name: 'Chương trước' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Mục lục' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Chương sau' })).toBeVisible();
  const undersizedReaderButtons = await page.locator('button:visible').evaluateAll((buttons) => (
    buttons
      .map((button) => {
        const rect = button.getBoundingClientRect();
        return { label: button.getAttribute('aria-label') || button.textContent?.trim(), width: rect.width, height: rect.height };
      })
      .filter(({ width, height }) => width < 44 || height < 44)
  ));
  expect(undersizedReaderButtons).toEqual([]);

  await page.getByRole('button', { name: 'Mục lục' }).click();
  const toc = page.getByRole('dialog', { name: 'Mục lục' });
  await expect(toc.getByRole('button', { name: 'Đầu → cuối' })).toBeVisible();
  await expect(toc.getByRole('button', { name: 'Cuối → đầu' })).toBeVisible();
  await toc.getByRole('button', { name: 'Cuối → đầu' }).click();
  await toc.getByRole('button', { name: 'Đóng mục lục' }).click();

  await page.getByRole('button', { name: 'Cài đặt chữ' }).click();
  await expect(page.getByRole('dialog', { name: 'Cài đặt đọc' })).toContainText('Tùy chỉnh đọc');
  await page.getByRole('button', { name: 'Đóng cài đặt đọc' }).click();

  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.setViewportSize({ width: 360, height: 740 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);

  await page.getByRole('button', { name: 'Quay lại thư viện' }).click();
  await expect(page.getByRole('heading', { name: 'Thư viện' })).toBeVisible();
});

test('exports a translated book as TXT without calling a live API', async ({ page }) => {
  const state: MockState = { imported: false, translated: true, translateRequests: [] };
  await authenticatedPage(page, state);

  await page.getByRole('navigation', { name: 'Quy trình' }).getByRole('button', { name: 'Xuất file' }).click();
  await expect(page.getByRole('heading', { name: 'Xuất file' })).toBeVisible();

  const downloadPromise = page.waitForEvent('download');
  await page.getByRole('button', { name: 'Bắt đầu xuất' }).click();
  const download = await downloadPromise;

  expect(download.suggestedFilename()).toBe('Audit_Book.txt');
  await expect(page.getByText('Audit_Book.txt')).toBeVisible();
});
