async (page) => {
  const failures = [];
  const onResponse = (response) => {
    if (response.status() >= 400) {
      const url = new URL(response.url());
      failures.push(`${response.status()} ${url.pathname}`);
    }
  };
  page.on('response', onResponse);

  const exactText = async (text) => {
    await page.getByText(text, { exact: true }).waitFor({ state: 'visible' });
  };
  const ensure = (condition, message) => {
    if (!condition) throw new Error(message);
  };

  try {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.getByRole('button', { name: 'Raw chưa dịch' }).click();
    await page.getByRole('button', {
      name: /Mở bàn dịch Synthetic Phase 6 operator journey chương 1/,
    }).click();
    await page.getByRole('button', { name: 'Thuật ngữ & Văn phong' }).click();

    await exactText('1–4 / 4');
    await page.getByRole('tab', { name: 'Tất cả' }).click();
    await exactText('Trang 1 / 200');
    await page.getByRole('button', { name: 'Trang sau' }).click();
    await exactText('Trang 2 / 200');
    const search = page.getByRole('searchbox', { name: 'Tìm thuật ngữ' });
    await search.fill('synthetic-source-09999');
    await exactText('1–1 / 1');
    await page.getByRole('rowheader', { name: 'synthetic-source-09999' }).waitFor();
    await search.fill('');
    await page.getByRole('tab', { name: 'Cần duyệt' }).click();
    await exactText('1–4 / 4');

    await page.getByText('Tạo thuật ngữ', { exact: true }).click();
    await page.getByRole('textbox', { name: 'Thuật ngữ gốc mới' }).fill('phase6-browser-created');
    await page.getByRole('textbox', { name: 'Bản dịch mới' }).fill('Browser Created');
    await page.getByRole('button', { name: 'Tạo thuật ngữ mới' }).click();
    await page.getByRole('rowheader', { name: 'phase6-browser-created' }).waitFor();
    const target = page.getByRole('textbox', { name: 'Bản dịch cho phase6-browser-created' });
    await target.fill('Browser Edited');
    await page.getByRole('button', { name: 'Lưu + Duyệt phase6-browser-created' }).click();
    await page.getByRole('tab', { name: 'Đã duyệt' }).click();
    await search.fill('phase6-browser-created');
    await page.getByRole('rowheader', { name: 'phase6-browser-created' }).waitFor();
    await page.getByRole('button', { name: 'Khóa thuật ngữ phase6-browser-created' }).click();

    await search.fill('');
    await page.getByRole('tab', { name: 'Cần duyệt' }).click();
    await page.getByRole('checkbox', { name: 'Chọn synthetic-source-00000' }).click();
    await page.getByRole('checkbox', { name: 'Chọn synthetic-source-00001' }).click();
    await page.getByRole('button', { name: 'Duyệt đã chọn' }).click();

    await page.getByText('Xung đột & hợp nhất', { exact: true }).click();
    await page.getByRole('button', { name: 'Tải xung đột' }).click();
    await page.getByRole('radio', { name: 'Chọn canonical Ｐｈａｓｅ６ Conflict' }).click();
    await page.getByRole('button', { name: 'Xem trước hợp nhất' }).click();
    await page.getByRole('button', { name: 'Áp dụng hợp nhất' }).click();
    await exactText('Không có xung đột.');

    await page.getByText('Nhập & xuất', { exact: true }).click();
    await page.getByRole('textbox', { name: 'Dữ liệu nhập JSON hoặc CSV' }).fill(JSON.stringify([{
      approved: 0,
      book_id: 1,
      locked: 0,
      review_status: 'NEEDS_REVIEW',
      source_term: 'phase6-browser-imported',
      target_term: 'Browser Imported',
    }]));
    await page.getByRole('button', { name: 'Xem trước nhập' }).click();
    await exactText('Thêm 1 · Cập nhật 0 · Bỏ qua 0');
    await page.getByRole('button', { name: 'Áp dụng nhập' }).click();
    const downloadPromise = page.waitForEvent('download');
    await page.getByRole('button', { name: 'Xuất JSON' }).click();
    const download = await downloadPromise;

    await page.getByRole('tab', { name: 'Đã khóa' }).click();
    await search.fill('phase6-browser-created');
    await page.getByRole('button', { name: 'Lưu trữ phase6-browser-created' }).click();
    await page.getByRole('tab', { name: 'Đã lưu trữ' }).click();
    await page.getByRole('button', { name: 'Khôi phục phase6-browser-created' }).click();

    await page.getByText('Trích xuất thuật ngữ', { exact: true }).click();
    const reextract = page.getByRole('button', { name: 'Trích xuất lại chương' });
    await reextract.click();
    const extractionStatus = await page.getByRole('status').filter({
      hasText: /thuật ngữ mới .* cập nhật .* cảnh báo/,
    }).textContent();

    await page.setViewportSize({ width: 390, height: 844 });
    const mobile = await page.evaluate(() => ({
      bodyScrollWidth: document.body.scrollWidth,
      innerWidth: window.innerWidth,
      rootScrollWidth: document.documentElement.scrollWidth,
    }));
    ensure(
      Math.max(mobile.bodyScrollWidth, mobile.rootScrollWidth) <= mobile.innerWidth,
      'mobile_horizontal_overflow',
    );

    await page.keyboard.press('Tab');
    const keyboardFocus = await page.evaluate(() => ({
      focusVisible: Boolean(document.activeElement?.matches(':focus-visible')),
      tag: document.activeElement?.tagName || '',
      text: document.activeElement?.textContent?.trim() || '',
    }));
    ensure(keyboardFocus.focusVisible, 'keyboard_focus_not_visible');
    ensure(keyboardFocus.tag === 'SUMMARY', 'keyboard_focus_not_on_summary');
    await page.keyboard.press('Enter');
    const keyboardActivated = await page.evaluate(
      () => document.activeElement?.parentElement?.open === true,
    );
    ensure(keyboardActivated, 'keyboard_activation_failed');

    await page.setViewportSize({ width: 1440, height: 900 });
    const desktopOverflow = await page.evaluate(
      () => document.documentElement.scrollWidth > window.innerWidth,
    );
    ensure(!desktopOverflow, 'desktop_horizontal_overflow');
    ensure(failures.length === 0, `http_failures:${failures.join(',')}`);

    return {
      datasetRows: 10000,
      desktop: { height: 900, noHorizontalOverflow: true, width: 1440 },
      download: download.suggestedFilename(),
      extractionStatus: extractionStatus?.trim() || '',
      httpFailures: failures,
      keyboard: { ...keyboardFocus, activated: keyboardActivated },
      mobile: { ...mobile, noHorizontalOverflow: true },
    };
  } finally {
    page.off('response', onResponse);
  }
}
