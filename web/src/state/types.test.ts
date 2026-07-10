import { describe, expect, it } from 'vitest';
import { ApiError } from '../api/client';
import { formatError } from './types';

describe('formatError', () => {
  it('turns auth and private asset failures into actionable session messages', () => {
    expect(formatError(new ApiError('Authentication required', 401))).toBe(
      'Phiên đăng nhập đã hết hạn. Hãy đăng nhập lại.',
    );
    expect(formatError(new ApiError('Invalid asset path', 403))).toBe(
      'Bạn không có quyền truy cập tài nguyên này. Hãy đăng nhập lại nếu vừa đổi phiên.',
    );
  });

  it('turns oversized upload failures into readable upload guidance', () => {
    expect(formatError(new ApiError('Failed to import source file (413): Raw text upload is too large. Maximum allowed size is 100.0 MB.', 413))).toBe(
      'File quá lớn. Giới hạn upload hiện tại là 100.0 MB.',
    );
  });

  it('turns provider and restart failures into retry guidance', () => {
    expect(formatError(new ApiError('Failed to start translate job (503 Service Unavailable): provider offline', 503))).toBe(
      'Provider dịch đang lỗi hoặc quá tải. Kiểm tra API key, quota, hoặc thử provider khác.',
    );
    expect(formatError(new Error('Server restarted during job'))).toBe(
      'Server đã restart khi job đang chạy. Hãy chạy lại job.',
    );
    expect(formatError(new Error('Job interrupted before completion'))).toBe(
      'Job bị gián đoạn trước khi hoàn tất. Hãy chạy lại job.',
    );
  });

  it('turns failed fetch into API offline guidance', () => {
    expect(formatError(new TypeError('Failed to fetch'))).toBe(
      'Không kết nối được API. Kiểm tra server local, Cloudflare Tunnel, hoặc mạng.',
    );
  });
});
