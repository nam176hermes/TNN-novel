const LOCAL_API_BASE_URL = 'http://127.0.0.1:7860';

function isLoopbackHost(hostname: string): boolean {
  return hostname === 'localhost' || hostname === '127.0.0.1' || hostname === '[::1]' || hostname === '::1';
}

export function resolveApiBaseUrl(envBaseUrl?: string, location: Location | URL = window.location): string {
  if (envBaseUrl && envBaseUrl.trim()) return envBaseUrl.trim().replace(/\/+$/, '');

  const { hostname, origin, port, protocol } = location;
  if ((protocol === 'http:' || protocol === 'https:') && (!isLoopbackHost(hostname) || port === '7860')) {
    return origin.replace(/\/+$/, '');
  }

  return LOCAL_API_BASE_URL;
}
