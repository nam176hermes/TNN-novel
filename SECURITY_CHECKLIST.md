# Security Checklist — Remote Access

## Current State
- [x] **JWT auth on all endpoints** — `/api/auth/login` returns access/refresh tokens; all other routes require `Authorization: Bearer <token>`
- [x] **HTTPS via Cloudflare** — TLS 1.3, Universal SSL certificate valid
- [x] **Cloudflare Tunnel** — `novel-tnn.tradingcompanydirect.com` → `http://127.0.0.1:7860`
- [x] **Browser-safe auth boundary** — protected `/api/*` routes require bearer auth; shared API keys are not sent from the dashboard

## Recommended Hardening

### 1. Cloudflare Access (Zero Trust) — Stronger
Cloudflare Access adds identity-aware proxy before request reaches your tunnel.

Setup:
1. Go to Cloudflare Dashboard → Zero Trust → Access → Applications
2. Add Application → Self-hosted
   - Domain: `novel-tnn.tradingcompanydirect.com`
   - Policy: Require email OTP / Google / GitHub / One-time PIN
3. Configure `cloudflared` to enforce Access:
   ```yaml
   # In tunnel config, add:
   - hostname: novel-tnn.tradingcompanydirect.com
     service: http://127.0.0.1:7860
     originRequest:
       noTLSVerify: true
   ```
4. Cloudflare will intercept unauthenticated requests at edge, serve login page, then forward with `CF-Access-JWT-Assertion` header.

### 2. Rate Limiting
Add to `app.mobile_api/main.py`:
```python
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Apply to sensitive endpoints
@router.post("/api/auth/login", ...)
@limiter.limit("5/minute")
async def login(...):
```

### 3. CORS Lockdown
Keep `MOBILE_API_CORS_ORIGINS` restricted to local development origins and the
public Cloudflare hostname. Do not use `*` with credentials enabled.

### 4. Security Headers
```python
from fastapi.middleware.trustedhost import TrustedHostMiddleware
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["novel-tnn.tradingcompanydirect.com"])
```

### 5. Secrets Management
- Never commit `.env` or `credentials-file` JSON
- Use `openssl rand -hex 32` for JWT secrets
- Keep provider keys (`GEMINI_API_KEY`, `DEEPSEEK_API_KEY`, `OPENROUTER_API_KEY`) only in `.env`
- Store provider keys with `python scripts/ops.py set-provider-key <KEY_NAME> --stdin` so values are not printed or saved in shell history
- Rotate JWT secret quarterly

### 6. Audit Log
All requests logged by FastAPI + Cloudflare. Cloudflare Analytics shows:
- Request volume, errors, latency
- Attack mitigation (WAF, DDoS)

## Verification
```bash
# 1. Health endpoint (no auth)
curl https://novel-tnn.tradingcompanydirect.com/api/health

# 2. Protected endpoint with JWT
curl -H "Authorization: Bearer <token>" https://novel-tnn.tradingcompanydirect.com/api/books

# 3. TLS check
curl -v https://novel-tnn.tradingcompanydirect.com/api/health | grep "SSL certificate verify ok"
```

## Emergency
If tunnel compromised:
1. `cloudflared tunnel delete trading-agent`
2. Regenerate Cloudflare API token
3. Re-create tunnel with new credentials
4. Update DNS
