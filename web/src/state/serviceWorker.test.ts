import { describe, expect, it, vi } from 'vitest';

type ReaderServiceWorkerModule = {
  READER_OFFLINE_SERVICE_WORKER_URL: string;
  verifyReaderOfflineAppShellReady(options?: Record<string, unknown>): Promise<void>;
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
    expect(serviceWorkerModule.READER_OFFLINE_SERVICE_WORKER_URL).toBe('/reader-offline-sw.js?v=20260724-ws1');
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

  it('reports readiness only after the active worker verifies the app shell', async () => {
    const serviceWorkerModule = await loadServiceWorkerModule();
    const postMessage = vi.fn((_message, ports: MessagePort[]) => {
      ports[0].postMessage({ ready: true });
    });
    const active = { postMessage } as unknown as ServiceWorker;

    await expect(serviceWorkerModule.verifyReaderOfflineAppShellReady({
      messageChannelFactory: () => new MessageChannel(),
      navigator: {
        serviceWorker: {
          controller: active,
          ready: Promise.resolve({ active } as ServiceWorkerRegistration),
          register: vi.fn(),
        },
      },
      timeoutMs: 100,
    })).resolves.toBeUndefined();

    expect(postMessage).toHaveBeenCalledWith(
      { assetUrls: [], type: 'VERIFY_READER_OFFLINE_APP_SHELL' },
      expect.any(Array),
    );
  });

  it('waits for first-session controller claim before reporting app-shell readiness', async () => {
    const serviceWorkerModule = await loadServiceWorkerModule();
    const active = {
      postMessage: (_message: unknown, ports: MessagePort[]) => ports[0].postMessage({ ready: true }),
    } as unknown as ServiceWorker;
    let controller: ServiceWorker | null = null;
    let controllerChange: EventListener | undefined;
    const serviceWorker = {
      addEventListener: vi.fn((_type: string, listener: EventListener) => {
        controllerChange = listener;
      }),
      get controller() {
        return controller;
      },
      ready: Promise.resolve({ active } as ServiceWorkerRegistration),
      register: vi.fn(),
      removeEventListener: vi.fn(),
    };

    const readiness = serviceWorkerModule.verifyReaderOfflineAppShellReady({
      messageChannelFactory: () => new MessageChannel(),
      navigator: { serviceWorker },
      timeoutMs: 100,
    });
    await vi.waitFor(() => {
      expect(serviceWorker.addEventListener).toHaveBeenCalledWith('controllerchange', expect.any(Function));
    });

    controller = active;
    controllerChange?.(new Event('controllerchange'));

    await expect(readiness).resolves.toBeUndefined();
    expect(serviceWorker.removeEventListener).toHaveBeenCalledWith('controllerchange', expect.any(Function));
  });

  it('rejects cache readiness when the worker reports a missing shell asset', async () => {
    const serviceWorkerModule = await loadServiceWorkerModule();
    const active = {
      postMessage: (_message: unknown, ports: MessagePort[]) => {
        ports[0].postMessage({ missing: ['/assets/index.js'], ready: false });
      },
    } as unknown as ServiceWorker;

    await expect(serviceWorkerModule.verifyReaderOfflineAppShellReady({
      messageChannelFactory: () => new MessageChannel(),
      navigator: {
        serviceWorker: {
          controller: active,
          ready: Promise.resolve({ active } as ServiceWorkerRegistration),
          register: vi.fn(),
        },
      },
      timeoutMs: 100,
    })).rejects.toThrow('Offline app shell is not ready');
  });
});
