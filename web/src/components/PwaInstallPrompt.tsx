import { useEffect, useState } from 'react';
import { Download, Smartphone, X } from 'lucide-react';

export const PWA_INSTALL_DISMISSED_STORAGE_KEY = 'novel-pwa-install-dismissed-v1';
const MANUAL_INSTALL_HINT_DELAY_MS = 600;

type BeforeInstallPromptEvent = Event & {
  prompt(): Promise<void>;
  userChoice: Promise<{ outcome: string; platform: string }>;
};

function browserStorage(): Storage | null {
  try {
    return window.localStorage;
  } catch {
    return null;
  }
}

function isStandaloneDisplay(): boolean {
  const navigatorWithStandalone = navigator as Navigator & { standalone?: boolean };
  return Boolean(
    window.matchMedia?.('(display-mode: standalone)').matches
    || navigatorWithStandalone.standalone,
  );
}

function installWasDismissed(): boolean {
  return browserStorage()?.getItem(PWA_INSTALL_DISMISSED_STORAGE_KEY) === '1';
}

function rememberInstallDismissal(): void {
  browserStorage()?.setItem(PWA_INSTALL_DISMISSED_STORAGE_KEY, '1');
}

export default function PwaInstallPrompt() {
  const [installPrompt, setInstallPrompt] = useState<BeforeInstallPromptEvent | null>(null);
  const [hidden, setHidden] = useState(() => installWasDismissed() || isStandaloneDisplay());
  const [showManualInstructions, setShowManualInstructions] = useState(false);

  useEffect(() => {
    if (hidden) return undefined;

    function handleBeforeInstallPrompt(event: Event): void {
      event.preventDefault();
      setShowManualInstructions(false);
      setInstallPrompt(event as BeforeInstallPromptEvent);
    }

    window.addEventListener('beforeinstallprompt', handleBeforeInstallPrompt);
    return () => window.removeEventListener('beforeinstallprompt', handleBeforeInstallPrompt);
  }, [hidden]);

  useEffect(() => {
    if (hidden || installPrompt) return undefined;
    const timer = window.setTimeout(() => setShowManualInstructions(true), MANUAL_INSTALL_HINT_DELAY_MS);
    return () => window.clearTimeout(timer);
  }, [hidden, installPrompt]);

  if (hidden || (!installPrompt && !showManualInstructions)) return null;

  async function installApp(): Promise<void> {
    if (!installPrompt) return;
    await installPrompt.prompt();
    const choice = await installPrompt.userChoice.catch(() => ({ outcome: 'dismissed', platform: 'web' }));
    if (choice.outcome === 'accepted') {
      setHidden(true);
      setInstallPrompt(null);
    }
  }

  function dismissInstallPrompt(): void {
    rememberInstallDismissal();
    setHidden(true);
    setInstallPrompt(null);
  }

  return (
    <section aria-label="Cài đặt Novel-TNN như app" className="pwa-install-prompt">
      <div className="pwa-install-icon">
        <Smartphone aria-hidden="true" size={20} />
      </div>
      <div>
        <strong>Cài Novel-TNN</strong>
        <p>
          {installPrompt
            ? 'Cài Novel-TNN lên Android Chrome hoặc desktop để mở dạng standalone. Import, dịch, TTS và export vẫn cần backend.'
            : 'Nếu trình duyệt không hiện nút cài, mở menu trình duyệt rồi chọn Add to Home screen hoặc Install app. Import, dịch, TTS và export vẫn cần backend.'}
        </p>
      </div>
      <div className="pwa-install-actions">
        <button className="secondary-action" onClick={dismissInstallPrompt} type="button">
          <X aria-hidden="true" size={15} />
          Để sau
        </button>
        {installPrompt ? (
          <button className="primary-action" onClick={() => void installApp()} type="button">
            <Download aria-hidden="true" size={15} />
            Cài app
          </button>
        ) : null}
      </div>
    </section>
  );
}
