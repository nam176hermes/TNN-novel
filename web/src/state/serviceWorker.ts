export const READER_OFFLINE_SERVICE_WORKER_URL = '/reader-offline-sw.js?v=20260723-ws2';

export type ReaderServiceWorkerNavigator = {
  serviceWorker?: {
    register(scriptURL: string, options?: RegistrationOptions): Promise<ServiceWorkerRegistration>;
  };
};

export type RegisterReaderOfflineServiceWorkerOptions = {
  enabled?: boolean;
  navigator?: ReaderServiceWorkerNavigator;
};

function browserNavigator(): ReaderServiceWorkerNavigator | undefined {
  if (typeof navigator === 'undefined') return undefined;
  return navigator;
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
