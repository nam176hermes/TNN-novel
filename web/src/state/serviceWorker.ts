export const READER_OFFLINE_SERVICE_WORKER_URL = '/reader-offline-sw.js?v=20260724-ws1';
const VERIFY_APP_SHELL_MESSAGE = 'VERIFY_READER_OFFLINE_APP_SHELL';

export type ReaderServiceWorkerNavigator = {
  serviceWorker?: {
    addEventListener?(type: 'controllerchange', listener: EventListener): void;
    controller?: ServiceWorker | null;
    ready?: Promise<ServiceWorkerRegistration>;
    register(scriptURL: string, options?: RegistrationOptions): Promise<ServiceWorkerRegistration>;
    removeEventListener?(type: 'controllerchange', listener: EventListener): void;
  };
};

export type VerifyReaderOfflineAppShellOptions = {
  assetUrls?: string[];
  messageChannelFactory?: () => MessageChannel;
  navigator?: ReaderServiceWorkerNavigator;
  timeoutMs?: number;
};

export type RegisterReaderOfflineServiceWorkerOptions = {
  enabled?: boolean;
  navigator?: ReaderServiceWorkerNavigator;
};

function browserNavigator(): ReaderServiceWorkerNavigator | undefined {
  if (typeof navigator === 'undefined') return undefined;
  return navigator;
}

function currentAppShellAssetUrls(): string[] {
  if (typeof document === 'undefined' || typeof location === 'undefined') return [];
  return Array.from(document.querySelectorAll<HTMLScriptElement | HTMLLinkElement>('script[src], link[href]'))
    .map((element) => element instanceof HTMLScriptElement ? element.src : element.href)
    .filter((url) => {
      try {
        const parsed = new URL(url, location.origin);
        return parsed.origin === location.origin && parsed.pathname.startsWith('/assets/');
      } catch {
        return false;
      }
    });
}

function withTimeout<T>(promise: Promise<T>, timeoutMs: number, message: string): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    const timeout = globalThis.setTimeout(() => reject(new Error(message)), timeoutMs);
    promise.then(
      (value) => {
        globalThis.clearTimeout(timeout);
        resolve(value);
      },
      (error: unknown) => {
        globalThis.clearTimeout(timeout);
        reject(error);
      },
    );
  });
}

async function controlledWorker(
  serviceWorker: NonNullable<ReaderServiceWorkerNavigator['serviceWorker']>,
  timeoutMs: number,
): Promise<ServiceWorker> {
  if (serviceWorker.controller) return serviceWorker.controller;
  if (!serviceWorker.addEventListener || !serviceWorker.removeEventListener) {
    throw new Error('Offline app shell is not controlling this page');
  }

  return new Promise<ServiceWorker>((resolve, reject) => {
    const cleanup = (): void => {
      globalThis.clearTimeout(timeout);
      serviceWorker.removeEventListener?.('controllerchange', handleControllerChange);
    };
    const handleControllerChange: EventListener = () => {
      if (!serviceWorker.controller) return;
      const controller = serviceWorker.controller;
      cleanup();
      resolve(controller);
    };
    const timeout = globalThis.setTimeout(() => {
      cleanup();
      reject(new Error('Offline app shell control timed out'));
    }, timeoutMs);
    serviceWorker.addEventListener?.('controllerchange', handleControllerChange);
  });
}

export async function registerReaderOfflineServiceWorker(
  options: RegisterReaderOfflineServiceWorkerOptions = {},
): Promise<ServiceWorkerRegistration | null> {
  const enabled = options.enabled ?? import.meta.env.PROD;
  if (!enabled) return null;

  const targetNavigator = options.navigator ?? browserNavigator();
  if (!targetNavigator?.serviceWorker) return null;

  try {
    return await targetNavigator.serviceWorker.register(
      READER_OFFLINE_SERVICE_WORKER_URL,
      { scope: '/' },
    );
  } catch {
    return null;
  }
}

export async function verifyReaderOfflineAppShellReady(
  options: VerifyReaderOfflineAppShellOptions = {},
): Promise<void> {
  const targetNavigator = options.navigator ?? browserNavigator();
  const serviceWorker = targetNavigator?.serviceWorker;
  if (!serviceWorker?.ready) throw new Error('Offline app shell is not available');

  const timeoutMs = options.timeoutMs ?? 10_000;
  await withTimeout(
    serviceWorker.ready,
    timeoutMs,
    'Offline app shell readiness timed out',
  );
  const worker = await controlledWorker(serviceWorker, timeoutMs);

  const channel = (options.messageChannelFactory ?? (() => new MessageChannel()))();
  await new Promise<void>((resolve, reject) => {
    const timeout = globalThis.setTimeout(() => {
      channel.port1.close();
      channel.port2.close();
      reject(new Error('Offline app shell readiness timed out'));
    }, timeoutMs);
    channel.port1.onmessage = (event: MessageEvent<{ ready?: boolean }>) => {
      globalThis.clearTimeout(timeout);
      channel.port1.close();
      channel.port2.close();
      if (event.data?.ready) resolve();
      else reject(new Error('Offline app shell is not ready'));
    };
    worker.postMessage({
      assetUrls: options.assetUrls ?? currentAppShellAssetUrls(),
      type: VERIFY_APP_SHELL_MESSAGE,
    }, [channel.port2]);
  });
}
