export type PageDiagnostics = {
  consoleErrors: string[];
  httpFailures: string[];
  pageErrors: string[];
  requestFailures: string[];
};

export function hasOnlyOptionalQaMiss(diagnostics: PageDiagnostics, qaUrl: string): boolean {
  if (diagnostics.pageErrors.length > 0 || diagnostics.requestFailures.length > 0) return false;
  if (diagnostics.consoleErrors.length === 0 && diagnostics.httpFailures.length === 0) return true;

  return (
    diagnostics.consoleErrors.length === 1
    && diagnostics.consoleErrors[0]
      === `${qaUrl} Failed to load resource: the server responded with a status of 404 (Not Found)`
    && diagnostics.httpFailures.length === 1
    && diagnostics.httpFailures[0] === `404 GET ${qaUrl}`
  );
}
