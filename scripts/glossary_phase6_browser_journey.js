async (page) => {
  const ensure = (condition, message) => {
    if (!condition) throw new Error(message);
  };
  const viewport = page.viewportSize();
  ensure(Boolean(viewport), 'viewport_not_configured');
  const viewportName = viewport.width === 1440 && viewport.height === 900
    ? 'desktop'
    : viewport.width === 390 && viewport.height === 844
      ? 'mobile'
      : '';
  ensure(Boolean(viewportName), `unexpected_viewport:${JSON.stringify(viewport)}`);

  const createdSource = `phase6-browser-created-${viewportName}`;
  const createdInitialTarget = `Browser Created ${viewportName}`;
  const createdEditedTarget = `Browser Edited ${viewportName}`;
  const importedSource = `phase6-browser-imported-${viewportName}`;
  const importedTarget = `Browser Imported ${viewportName}`;

  const exactText = async (text) => {
    await page.getByText(text, { exact: true }).waitFor({ state: 'visible' });
  };
  const rowFor = async (source) => {
    const header = page.locator('tbody th[scope="row"]').filter({
      has: page.getByText(source, { exact: true }),
    });
    await header.waitFor({ state: 'visible' });
    return header.locator('..');
  };
  const assertTarget = async (source, target) => {
    const row = await rowFor(source);
    const value = await row.getByRole('textbox', { name: `Bản dịch cho ${source}` }).inputValue();
    ensure(value === target, `unexpected_target:${source}:${value}`);
    return row;
  };
  const selectStatusFilter = async (name) => {
    const filterGroup = page.getByRole('group', { name: 'Trạng thái thuật ngữ' });
    const button = filterGroup.getByRole('button', { name, exact: true });
    await button.click();
    await page.waitForFunction(
      (label) => Array.from(document.querySelectorAll(
        '[role="group"][aria-label="Trạng thái thuật ngữ"] button',
      )).some(
        (candidate) => candidate.textContent?.trim() === label
          && candidate.getAttribute('aria-pressed') === 'true',
      ),
      name,
    );
  };
  const searchFor = async (search, statusFilter, source, target = null, rangeText = '1–1 / 1') => {
    await selectStatusFilter(statusFilter);
    await search.fill(source);
    await exactText(rangeText);
    return target === null ? rowFor(source) : assertTarget(source, target);
  };
  const overflowSnapshot = async (label) => {
    const snapshot = await page.evaluate(() => ({
      bodyScrollWidth: document.body.scrollWidth,
      innerWidth: window.innerWidth,
      rootScrollWidth: document.documentElement.scrollWidth,
    }));
    ensure(
      Math.max(snapshot.bodyScrollWidth, snapshot.rootScrollWidth) <= snapshot.innerWidth,
      `${label}_horizontal_overflow:${JSON.stringify(snapshot)}`,
    );
    return { ...snapshot, noHorizontalOverflow: true };
  };
  const parseDownload = async (download) => {
    const stream = await download.createReadStream();
    ensure(Boolean(stream), 'export_stream_missing');
    let contents = '';
    for await (const chunk of stream) contents += chunk.toString('utf8');
    return JSON.parse(contents);
  };
  const openWorkflowView = async (name) => {
    if (viewportName === 'desktop') {
      const navigation = page.getByRole('navigation', { name: 'Quy trình' });
      await navigation.getByRole('button', { name, exact: true }).click();
      return;
    }
    const mobileNavigation = page.getByRole('navigation', {
      name: 'Điều hướng chính trên di động',
    });
    await mobileNavigation.getByRole('button', { name: 'Thêm', exact: true }).click();
    const moreSheet = page.getByRole('dialog', { name: 'Thêm' });
    await moreSheet.getByRole('button', { name, exact: true }).click();
  };

  // The orchestrator always opens a new, unauthenticated browser session.
  await page.getByLabel('Username').fill('phase6_operator');
  await page.getByLabel('Password').fill('Phase6-Disposable-Only!2026');
  await page.getByRole('button', { name: 'Login', exact: true }).click();
  await page.getByRole('navigation', {
    name: viewportName === 'desktop' ? 'Quy trình' : 'Điều hướng chính trên di động',
  }).waitFor({ state: 'visible' });

  const failures = [];
  const onResponse = (response) => {
    if (response.status() >= 400) {
      const url = new URL(response.url());
      failures.push(`${response.status()} ${url.pathname}`);
    }
  };
  page.on('response', onResponse);

  try {
    const initialOverflow = await overflowSnapshot(`${viewportName}_initial`);
    await openWorkflowView('Raw chưa dịch');
    await page.getByRole('heading', { name: 'Raw chưa dịch', exact: true }).waitFor();
    await page.getByRole('button', {
      name: /Mở bàn dịch Synthetic Phase 6 operator journey chương 1/,
    }).click();
    await openWorkflowView('Thuật ngữ & Văn phong');

    // Queue, page, and search each prove their resulting data, not merely navigation.
    await exactText('1–4 / 4');
    for (const source of [
      'synthetic-source-00000',
      'synthetic-source-00001',
      'Ｐｈａｓｅ６ Conflict',
      'phase6 conflict',
    ]) {
      await rowFor(source);
    }
    await selectStatusFilter('Tất cả');
    await exactText('Trang 1 / 200');
    const pageOneSources = await page.locator('tbody th[scope="row"]').allTextContents();
    ensure(pageOneSources.length === 50, `page_one_row_count:${pageOneSources.length}`);
    await page.getByRole('button', { name: 'Trang sau' }).click();
    await exactText('Trang 2 / 200');
    const pageTwoSources = await page.locator('tbody th[scope="row"]').allTextContents();
    ensure(pageTwoSources.length === 50, `page_two_row_count:${pageTwoSources.length}`);
    ensure(
      JSON.stringify(pageOneSources) !== JSON.stringify(pageTwoSources),
      'pagination_did_not_change_rows',
    );
    const search = page.getByRole('searchbox', { name: 'Tìm thuật ngữ' });
    await search.fill('synthetic-source-09999');
    await exactText('1–1 / 1');
    await assertTarget('synthetic-source-09999', 'synthetic-target-09999');

    // Create, edit/approve, and lock, with status-specific queue assertions.
    await search.fill('');
    await selectStatusFilter('Cần duyệt');
    await exactText('1–4 / 4');
    await page.getByText('Tạo thuật ngữ', { exact: true }).click();
    await page.getByRole('textbox', { name: 'Thuật ngữ gốc mới' }).fill(createdSource);
    await page.getByRole('textbox', { name: 'Bản dịch mới' }).fill(createdInitialTarget);
    await page.getByRole('button', { name: 'Tạo thuật ngữ mới' }).click();
    await assertTarget(createdSource, createdInitialTarget);
    const target = page.getByRole('textbox', { name: `Bản dịch cho ${createdSource}` });
    await target.fill(createdEditedTarget);
    await page.getByRole('button', { name: `Lưu + Duyệt ${createdSource}` }).click();
    await page.getByRole('rowheader', { name: createdSource, exact: true }).waitFor({ state: 'hidden' });
    let createdRow = await searchFor(search, 'Đã duyệt', createdSource, createdEditedTarget);
    await createdRow.getByText('Đã duyệt', { exact: true }).waitFor({ state: 'visible' });
    await page.getByRole('button', { name: `Khóa thuật ngữ ${createdSource}` }).click();
    await page.getByRole('rowheader', { name: createdSource, exact: true }).waitFor({ state: 'hidden' });
    createdRow = await searchFor(search, 'Đã khóa', createdSource, createdEditedTarget);
    await createdRow.getByText('Đã khóa', { exact: true }).waitFor({ state: 'visible' });

    // Both selected rows must leave pending and become queryable as approved.
    await search.fill('');
    await selectStatusFilter('Cần duyệt');
    await page.getByRole('checkbox', { name: 'Chọn synthetic-source-00000' }).click();
    await page.getByRole('checkbox', { name: 'Chọn synthetic-source-00001' }).click();
    await page.getByRole('button', { name: 'Duyệt đã chọn' }).click();
    for (const source of ['synthetic-source-00000', 'synthetic-source-00001']) {
      await page.getByRole('rowheader', { name: source, exact: true }).waitFor({ state: 'hidden' });
      const approvedRow = await searchFor(
        search,
        'Đã duyệt',
        source,
        source.replace('source', 'target'),
      );
      await approvedRow.getByText('Đã duyệt', { exact: true }).waitFor({ state: 'visible' });
    }

    // Merge leaves the canonical active, archives the duplicate, and removes the group.
    const clearedQueueResponse = page.waitForResponse((response) => {
      const responseUrl = response.url();
      return responseUrl.includes('/api/glossary?')
        && !/[?&]q=/.test(responseUrl)
        && responseUrl.includes('review_status=APPROVED')
        && response.status() === 200;
    });
    await search.fill('');
    await clearedQueueResponse;
    await page.getByText('Đang tải hàng chờ…', { exact: true }).waitFor({ state: 'hidden' });
    await page.getByText('Xung đột & hợp nhất', { exact: true }).click();
    await page.getByRole('button', { name: 'Tải xung đột' }).click();
    await page.getByRole('radio', { name: 'Chọn canonical Ｐｈａｓｅ６ Conflict' }).click();
    await page.getByRole('button', { name: 'Xem trước hợp nhất' }).click();
    const mergeStatus = page.getByRole('status').filter({ hasText: /bằng chứng sẽ chuyển/ });
    await mergeStatus.waitFor({ state: 'visible' });
    const applyMerge = page.getByRole('button', { name: 'Áp dụng hợp nhất' });
    await applyMerge.evaluate((element) => element.scrollIntoView({ block: 'center' }));
    await applyMerge.click();
    await exactText('Không có xung đột.');
    const canonicalRow = await searchFor(search, 'Cần duyệt', 'Ｐｈａｓｅ６ Conflict', 'Canonical');
    await canonicalRow.getByText('Xung đột', { exact: true }).waitFor({ state: 'visible' });
    const archivedConflictRow = await searchFor(
      search,
      'Đã lưu trữ',
      'phase6 conflict',
      'Duplicate',
    );
    await archivedConflictRow.getByRole('button', { name: 'Khôi phục phase6 conflict' }).waitFor();

    // Import preview and apply must materialize the imported row before export.
    await page.getByText('Nhập & xuất', { exact: true }).click();
    await page.getByRole('textbox', { name: 'Dữ liệu nhập JSON hoặc CSV' }).fill(JSON.stringify([{
      approved: 0,
      book_id: 1,
      locked: 0,
      review_status: 'NEEDS_REVIEW',
      source_term: importedSource,
      target_term: importedTarget,
    }]));
    await page.getByRole('button', { name: 'Xem trước nhập' }).click();
    await exactText('Thêm 1 · Cập nhật 0 · Bỏ qua 0');
    await page.getByRole('button', { name: 'Áp dụng nhập' }).click();
    await page.getByRole('button', { name: 'Áp dụng nhập' }).waitFor({ state: 'hidden' });
    const importedRow = await searchFor(search, 'Cần duyệt', importedSource, importedTarget);
    await importedRow.getByText('Chờ duyệt', { exact: true }).waitFor({ state: 'visible' });

    const downloadPromise = page.waitForEvent('download');
    await page.getByRole('button', { name: 'Xuất JSON' }).click();
    const download = await downloadPromise;
    ensure(download.suggestedFilename() === 'glossary.json', `export_filename:${download.suggestedFilename()}`);
    const exportPayload = await parseDownload(download);
    ensure(exportPayload.schema_version === 1, 'export_schema_version');
    ensure(exportPayload.scope?.type === 'book' && exportPayload.scope?.book_id === 1, 'export_scope');
    ensure(exportPayload.total === exportPayload.terms?.length, 'export_total_mismatch');
    ensure(exportPayload.total >= 10002, `export_total:${exportPayload.total}`);
    const exportedBySource = new Map(exportPayload.terms.map((term) => [term.source_term, term]));
    const exportedCreated = exportedBySource.get(createdSource);
    const exportedImported = exportedBySource.get(importedSource);
    const exportedConflict = exportedBySource.get('phase6 conflict');
    ensure(
      exportedCreated?.target_term === createdEditedTarget
        && exportedCreated?.review_status === 'LOCKED'
        && exportedCreated?.locked === 1,
      'export_created_content',
    );
    ensure(
      exportedImported?.target_term === importedTarget
        && exportedImported?.review_status === 'NEEDS_REVIEW',
      'export_imported_content',
    );
    ensure(exportedConflict?.archived === true, 'export_merged_archive_content');
    ensure(exportedBySource.has('synthetic-source-09999'), 'export_fixture_tail_missing');

    // Archive then restore the created locked row, proving both intermediate/final queues.
    createdRow = await searchFor(search, 'Đã khóa', createdSource, createdEditedTarget);
    await page.getByRole('button', { name: `Lưu trữ ${createdSource}` }).click();
    await page.getByRole('rowheader', { name: createdSource, exact: true }).waitFor({ state: 'hidden' });
    createdRow = await searchFor(search, 'Đã lưu trữ', createdSource, createdEditedTarget);
    await createdRow.getByRole('button', { name: `Khôi phục ${createdSource}` }).click();
    await page.getByRole('rowheader', { name: createdSource, exact: true }).waitFor({ state: 'hidden' });
    createdRow = await searchFor(search, 'Đã khóa', createdSource, createdEditedTarget);
    await createdRow.getByText('Đã khóa', { exact: true }).waitFor({ state: 'visible' });

    // Re-extraction must report and expose deterministic output; keyboard-only activation follows.
    await page.getByText('Trích xuất thuật ngữ', { exact: true }).click();
    const reextract = page.getByRole('button', { name: 'Trích xuất lại chương' });
    await reextract.waitFor({ state: 'visible' });
    await page.waitForFunction(
      () => !Array.from(document.querySelectorAll('button')).find(
        (button) => button.textContent?.trim() === 'Trích xuất lại chương',
      )?.disabled,
    );
    await reextract.click();
    const extractionStatusText = '5 thuật ngữ mới · 0 cập nhật · 0 cảnh báo';
    await exactText(extractionStatusText);

    await page.keyboard.press('Tab');
    const keyboardFocus = await page.evaluate(() => ({
      focusVisible: Boolean(document.activeElement?.matches(':focus-visible')),
      tag: document.activeElement?.tagName || '',
      text: document.activeElement?.textContent?.trim() || '',
    }));
    ensure(keyboardFocus.focusVisible, 'keyboard_focus_not_visible');
    ensure(keyboardFocus.tag === 'SUMMARY', 'keyboard_focus_not_on_summary');
    ensure(keyboardFocus.text === 'Profile văn phong (phụ)', 'keyboard_focus_wrong_summary');
    await page.keyboard.press('Enter');
    const keyboardActivated = await page.evaluate(
      () => document.activeElement?.parentElement?.open === true,
    );
    ensure(keyboardActivated, 'keyboard_activation_failed');

    const postExtractionDownloadPromise = page.waitForEvent('download');
    await page.getByRole('button', { name: 'Xuất JSON' }).click();
    const postExtractionDownload = await postExtractionDownloadPromise;
    ensure(
      postExtractionDownload.suggestedFilename() === 'glossary.json',
      `post_extraction_export_filename:${postExtractionDownload.suggestedFilename()}`,
    );
    const postExtractionPayload = await parseDownload(postExtractionDownload);
    ensure(postExtractionPayload.total === 10007, `post_extraction_total:${postExtractionPayload.total}`);
    const postExtractionBySource = new Map(
      postExtractionPayload.terms.map((term) => [term.source_term, term]),
    );
    const extractedSources = [
      '云宗青',
      '玄天圣典',
      '玄天圣典玄天圣典',
      '青云宗',
      '青云宗青云宗',
    ];
    for (const source of extractedSources) {
      const extracted = postExtractionBySource.get(source);
      ensure(
        extracted?.review_status === 'NEEDS_REVIEW'
          && extracted?.first_seen_chapter_id === 1
          && extracted?.first_seen_chapter_number === 1,
        `post_extraction_content:${source}`,
      );
    }
    const finalOverflow = await overflowSnapshot(`${viewportName}_final`);
    ensure(failures.length === 0, `http_failures:${failures.join(',')}`);
    await page.screenshot({
      fullPage: true,
      path: `phase6-${viewportName}-final.png`,
    });

    return {
      actions: {
        archiveRestore: 'locked-restored',
        bulk: ['synthetic-source-00000', 'synthetic-source-00001'],
        conflict: { archived: 'phase6 conflict', canonical: 'Ｐｈａｓｅ６ Conflict' },
        createEditApproveLock: { source: createdSource, target: createdEditedTarget },
        import: { source: importedSource, target: importedTarget },
        page: { pageOneRows: pageOneSources.length, pageTwoRows: pageTwoSources.length },
        reextract: { created: 5, exportedSources: extractedSources },
        search: 'synthetic-source-09999',
      },
      datasetRows: 10000,
      export: {
        filename: download.suggestedFilename(),
        parsed: true,
        total: exportPayload.total,
      },
      extractionStatus: extractionStatusText,
      httpFailures: failures,
      keyboard: { ...keyboardFocus, activated: keyboardActivated },
      overflow: { final: finalOverflow, initial: initialOverflow },
      viewport: { ...viewport, name: viewportName },
    };
  } finally {
    page.off('response', onResponse);
  }
}
