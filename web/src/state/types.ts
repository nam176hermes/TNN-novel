export type LoadState = 'idle' | 'loading' | 'ready' | 'empty' | 'error';

export type AsyncState<T> = {
  data: T;
  error: string;
  state: LoadState;
};

function messageFromError(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

export function formatError(error: unknown): string {
  const message = messageFromError(error);
  const normalized = message.toLowerCase();
  const status = typeof error === 'object' && error !== null && 'status' in error
    ? Number((error as { status?: unknown }).status)
    : 0;

  if (status === 401 || normalized.includes('authentication required') || normalized.includes('invalid token')) {
    return 'Phiên đăng nhập đã hết hạn. Hãy đăng nhập lại.';
  }

  if (status === 403 || normalized.includes('invalid asset path')) {
    return 'Bạn không có quyền truy cập tài nguyên này. Hãy đăng nhập lại nếu vừa đổi phiên.';
  }

  if (status === 413 || normalized.includes('too large')) {
    const limitMatch = message.match(/Maximum allowed size is ([0-9.]+ (?:MB|KB|bytes))/i);
    return limitMatch
      ? `File quá lớn. Giới hạn upload hiện tại là ${limitMatch[1]}.`
      : 'File quá lớn. Hãy chọn file nhỏ hơn hoặc tăng giới hạn upload trên server.';
  }

  if (normalized.includes('server restarted during job')) {
    return 'Server đã restart khi job đang chạy. Hãy chạy lại job.';
  }

  if (normalized.includes('job interrupted before completion')) {
    return 'Job bị gián đoạn trước khi hoàn tất. Hãy chạy lại job.';
  }

  if (
    normalized.includes('provider temporarily unavailable')
    || normalized.includes('provider offline')
    || normalized.includes('provider failed')
    || normalized.includes('quota')
    || normalized.includes('rate limit')
  ) {
    return 'Provider dịch đang lỗi hoặc quá tải. Kiểm tra API key, quota, hoặc thử provider khác.';
  }

  if (status === 409 && normalized.includes('revision')) {
    return 'Chương đã được sửa ở nơi khác. Tải lại bản mới trước khi lưu.';
  }
  if (status === 502 || status === 503) {
    return 'API đang tạm thời không phản hồi. Hãy thử tải lại khi kết nối ổn định.';
  }

  if (
    normalized.includes('failed to fetch')
    || normalized.includes('networkerror')
    || normalized.includes('load failed')
  ) {
    return 'Không kết nối được API. Kiểm tra server local, Cloudflare Tunnel, hoặc mạng.';
  }

  return message;
}
