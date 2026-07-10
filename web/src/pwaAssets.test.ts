import { describe, expect, it } from 'vitest';
import indexHtml from '../index.html?raw';
import manifestSource from '../public/manifest.webmanifest?raw';
import offlineHtml from '../public/offline.html?raw';
import icon192Url from '../public/pwa-icon-192.png?url';
import icon512Url from '../public/pwa-icon-512.png?url';
import maskableIconUrl from '../public/pwa-maskable-512.png?url';

describe('PWA public assets', () => {
  it('links a web app manifest from index.html', () => {
    expect(indexHtml).toContain('rel="manifest"');
    expect(indexHtml).toContain('/manifest.webmanifest');
    expect(indexHtml).toContain('name="theme-color"');
  });

  it('ships an installable manifest with standalone display and icons', () => {
    const manifest = JSON.parse(manifestSource) as {
      background_color?: string;
      display?: string;
      icons?: Array<{ purpose?: string; sizes?: string; src?: string; type?: string }>;
      id?: string;
      lang?: string;
      name?: string;
      orientation?: string;
      short_name?: string;
      start_url?: string;
      theme_color?: string;
    };

    expect(manifest.name).toBe('Novel-TNN Translator');
    expect(manifest.short_name).toBe('Novel-TNN');
    expect(manifest.id).toBe('/');
    expect(manifest.lang).toBe('vi');
    expect(manifest.display).toBe('standalone');
    expect(manifest.start_url).toBe('/');
    expect(manifest.orientation).toBe('portrait');
    expect(manifest.theme_color).toBe('#031b15');
    expect(manifest.background_color).toBe('#031b15');
    expect(manifest.icons?.some((icon) => icon.sizes === '192x192' && icon.type === 'image/png')).toBe(true);
    expect(manifest.icons?.some((icon) => icon.sizes === '512x512' && icon.type === 'image/png')).toBe(true);
    expect(manifest.icons?.some((icon) => icon.purpose?.includes('maskable'))).toBe(true);
    expect(icon192Url).toContain('pwa-icon-192.png');
    expect(icon512Url).toContain('pwa-icon-512.png');
    expect(maskableIconUrl).toContain('pwa-maskable-512.png');
  });

  it('ships an offline fallback page without pretending private books are available offline', () => {
    expect(offlineHtml).toContain('Novel-TNN');
    expect(offlineHtml).toContain('offline');
    expect(offlineHtml).toContain('Bạn đang offline');
    expect(offlineHtml).toContain('Chỉ chương/audio đã cache thủ công');
    expect(offlineHtml).toContain('Thử kết nối lại');
  });
});
