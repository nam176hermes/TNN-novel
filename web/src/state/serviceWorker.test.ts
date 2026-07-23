import { describe, expect, it, vi } from 'vitest';

type ReaderServiceWorkerModule = {
  READER_OFFLINE_SERVICE_WORKER_URL: string;
  registerReaderOfflineServiceWorker(options?: {
    enabled?: boolean;
    navigator?: {
      serviceWorker?: {
        register(scriptURL: string, options?: RegistrationOptions): Promise<ServiceWorkerRegistration>;
      };
    };
  }): Promise<ServiceWorkerRegistration | null>;
};

async function loadServiceWorkerModule(): Promise<ReaderServiceWorkerModule> {
  const modulePath = './serviceWorker';
  return import(modulePath) as Promise<ReaderServiceWorkerModule>;
}

describe('registerReaderOfflineServiceWorker', () => {
  it('registers the reader offline worker with root scope when enabled', async () => {
    const serviceWorkerModule = await loadServiceWorkerModule();
    const registration = { scope: '/' } as ServiceWorkerRegistration;
    const register = vi.fn().mockResolvedValue(registration);

    const result = await serviceWorkerModule.registerReaderOfflineServiceWorker({
      enabled: true,
      navigator: { serviceWorker: { register } },
    });

    expect(result).toBe(registration);
    expect(serviceWorkerModule.READER_OFFLINE_SERVICE_WORKER_URL).toBe('/reader-offline-sw.js?v=20260723-ws2');
    expect(register).toHaveBeenCalledWith(
      serviceWorkerModule.READER_OFFLINE_SERVICE_WORKER_URL,
      { scope: '/' },
    );
  });

  it('does not register in non-production mode unless explicitly enabled', async () => {
    const serviceWorkerModule = await loadServiceWorkerModule();
    const register = vi.fn();

    const result = await serviceWorkerModule.registerReaderOfflineServiceWorker({
      navigator: { serviceWorker: { register } },
    });

    expect(result).toBeNull();
    expect(register).not.toHaveBeenCalled();
  });

  it('keeps app boot safe when service workers are unavailable or registration fails', async () => {
    const serviceWorkerModule = await loadServiceWorkerModule();
    const failingRegister = vi.fn().mockRejectedValue(new Error('registration denied'));

    await expect(serviceWorkerModule.registerReaderOfflineServiceWorker({
      enabled: true,
      navigator: {},
    })).resolves.toBeNull();
    await expect(serviceWorkerModule.registerReaderOfflineServiceWorker({
      enabled: true,
      navigator: { serviceWorker: { register: failingRegister } },
    })).resolves.toBeNull();
  });
});
