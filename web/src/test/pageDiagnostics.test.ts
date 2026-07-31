import { describe, expect, it } from 'vitest';
import { hasOnlyOptionalQaMiss, type PageDiagnostics } from './pageDiagnostics';

const qaUrl = 'http://127.0.0.1:7860/api/books/42/chapters/4201/qa';
const cleanDiagnostics: PageDiagnostics = {
  consoleErrors: [],
  httpFailures: [],
  pageErrors: [],
  requestFailures: [],
};

describe('hasOnlyOptionalQaMiss', () => {
  it('accepts clean diagnostics and the paired optional QA 404', () => {
    expect(hasOnlyOptionalQaMiss(cleanDiagnostics, qaUrl)).toBe(true);
    expect(hasOnlyOptionalQaMiss({
      ...cleanDiagnostics,
      consoleErrors: [
        `${qaUrl} Failed to load resource: the server responded with a status of 404 (Not Found)`,
      ],
      httpFailures: [`404 GET ${qaUrl}`],
    }, qaUrl)).toBe(true);
  });

  it('rejects unpaired or unrelated failures and all page/request errors', () => {
    expect(hasOnlyOptionalQaMiss({
      ...cleanDiagnostics,
      httpFailures: [`404 GET ${qaUrl}`],
    }, qaUrl)).toBe(false);
    expect(hasOnlyOptionalQaMiss({
      ...cleanDiagnostics,
      consoleErrors: ['unexpected console error'],
    }, qaUrl)).toBe(false);
    expect(hasOnlyOptionalQaMiss({
      ...cleanDiagnostics,
      pageErrors: ['render failed'],
    }, qaUrl)).toBe(false);
    expect(hasOnlyOptionalQaMiss({
      ...cleanDiagnostics,
      requestFailures: ['GET /api/books net::ERR_FAILED'],
    }, qaUrl)).toBe(false);
  });
});
