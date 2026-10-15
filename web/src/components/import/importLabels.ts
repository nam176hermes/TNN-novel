export function formatBytes(value: number): string {
  if (value >= 1024 * 1024) return `${(value / 1024 / 1024).toFixed(1)} MB`;
  if (value >= 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${value.toLocaleString()} bytes`;
}

export function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

