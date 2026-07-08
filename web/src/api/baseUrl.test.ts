import { describe, expect, it } from 'vitest';
import { resolveApiBaseUrl } from './baseUrl';

describe('resolveApiBaseUrl', () => {
  it('uses an explicit Vite API base when provided', () => {
    expect(resolveApiBaseUrl('https://api.example.invalid', new URL('https://novel.example.invalid/'))).toBe(
      'https://api.example.invalid',
    );
  });

  it('uses the public same-origin URL outside local development', () => {
    expect(resolveApiBaseUrl(undefined, new URL('https://novel-tnn.tradingcompanydirect.com/'))).toBe(
      'https://novel-tnn.tradingcompanydirect.com',
    );
  });

  it('keeps the local API fallback for Vite dev hosts', () => {
    expect(resolveApiBaseUrl(undefined, new URL('http://127.0.0.1:5174/'))).toBe('http://127.0.0.1:7860');
  });

  it('uses same-origin when FastAPI serves the built app locally', () => {
    expect(resolveApiBaseUrl(undefined, new URL('http://127.0.0.1:7860/'))).toBe('http://127.0.0.1:7860');
  });
});
