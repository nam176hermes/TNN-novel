import { useEffect, useState } from 'react';
import { WifiOff } from 'lucide-react';

function browserOnline(): boolean {
  if (typeof navigator === 'undefined' || typeof navigator.onLine !== 'boolean') return true;
  return navigator.onLine;
}

export default function PwaNetworkStatus() {
  const [online, setOnline] = useState(browserOnline);

  useEffect(() => {
    function updateStatus(): void {
      setOnline(browserOnline());
    }

    window.addEventListener('online', updateStatus);
    window.addEventListener('offline', updateStatus);
    return () => {
      window.removeEventListener('online', updateStatus);
      window.removeEventListener('offline', updateStatus);
    };
  }, []);

  if (online) return null;

  return (
    <section aria-label="Trạng thái offline" className="pwa-network-status" role="status">
      <WifiOff aria-hidden="true" size={18} />
      <div>
        <strong>Bạn đang offline</strong>
        <span>App shell và nội dung đã cache thủ công vẫn có thể đọc. Import, dịch, TTS và export cần kết nối.</span>
      </div>
      <button className="secondary-action" onClick={() => window.location.reload()} type="button">
        Thử lại
      </button>
    </section>
  );
}
