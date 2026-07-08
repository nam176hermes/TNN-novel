import { type FormEvent, useState } from 'react';
import { Eye, LockKeyhole, LogIn, ShieldCheck, UserRound } from 'lucide-react';
import brandLogin from '../assets/reference-ui/brand-login.png';

type Props = {
  error: string;
  onLogin: (username: string, password: string) => Promise<void>;
};

export default function LoginPanel({ error, onLogin }: Props) {
  const [username, setUsername] = useState('admin');
  const [password, setPassword] = useState('');
  const [loading, setLoading] = useState(false);
  const [showPasswordHelp, setShowPasswordHelp] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    setLoading(true);
    try {
      await onLogin(username, password);
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="login-screen">
      <form className="login-panel" onSubmit={submit}>
        <div className="login-brand-row">
          <img alt="" aria-hidden="true" className="login-brand-mark login-brand-mark-image" src={brandLogin} />
          <div>
            <strong>Novel-TNN</strong>
            <span>Dịch truyện CN → VN</span>
          </div>
        </div>

        <div className="login-heading">
          <p>Welcome back</p>
          <h1>Novel-TNN Translator</h1>
        </div>

        <label>
          Username
          <span className="login-input-shell">
            <UserRound aria-hidden="true" size={17} />
            <input autoComplete="username" onChange={(event) => setUsername(event.target.value)} value={username} />
          </span>
        </label>

        <label>
          Password
          <span className="login-input-shell">
            <LockKeyhole aria-hidden="true" size={17} />
            <input
              autoComplete="current-password"
              onChange={(event) => setPassword(event.target.value)}
              type="password"
              value={password}
            />
            <Eye aria-hidden="true" size={17} />
          </span>
        </label>

        {error ? <p className="form-error">{error}</p> : null}

        <button className="primary-action" disabled={loading} type="submit">
          <LogIn aria-hidden="true" size={17} />
          {loading ? 'Logging in' : 'Login'}
        </button>

        <div className="login-divider" aria-hidden="true">
          <span />
          <em>or</em>
          <span />
        </div>

        <button
          aria-expanded={showPasswordHelp}
          className="secondary-action login-forgot"
          onClick={() => setShowPasswordHelp((current) => !current)}
          type="button"
        >
          <LockKeyhole aria-hidden="true" size={16} />
          Forgot password?
        </button>
        {showPasswordHelp ? (
          <p className="login-help" role="status">
            Mật khẩu admin được quản lý bằng biến môi trường. Dừng server, đổi MOBILE_API_ADMIN_PASSWORD,
            khởi động lại rồi dùng logout-all để thu hồi session cũ.
          </p>
        ) : null}

        <p className="login-security">
          <ShieldCheck aria-hidden="true" size={16} />
          Secure login protected by Novel-TNN
        </p>
      </form>
      <p className="login-copyright">© 2026 Novel-TNN Translator. All rights reserved.</p>
    </main>
  );
}
