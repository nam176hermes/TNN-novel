# Cloudflare Tunnel Setup Guide — novel_pipeline

## Overview
This guide sets up remote HTTPS access to the novel_pipeline mobile API backend
so the Flutter app works outside your home Wi-Fi.

## Public URL
**https://novel-tnn.tradingcompanydirect.com**

## Prerequisites
- Cloudflare domain (`tradingcompanydirect.com`)
- `cloudflared` binary installed (`~/.local/bin/cloudflared`)

## 1. Install cloudflared
```bash
curl -L https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 -o ~/.local/bin/cloudflared
chmod +x ~/.local/bin/cloudflared
```

## 2. Authenticate with Cloudflare
```bash
cloudflared tunnel login
# Opens browser → select domain → downloads cert.pem
```

## 3. Create tunnel
```bash
cloudflared tunnel create trading-agent
# Outputs tunnel UUID and credentials JSON
```

## 4. Route DNS
```bash
cloudflared tunnel route dns trading-agent novel-tnn.tradingcompanydirect.com
```

## 5. Configure ingress (~/.cloudflared/config.yml)
```yaml
tunnel: <TUNNEL_UUID>
credentials-file: /home/thenam176/.cloudflared/<UUID>.json

ingress:
  - hostname: novel-tnn.tradingcompanydirect.com
    service: http://127.0.0.1:7860
  - hostname: 2ndbrain.tradingcompanydirect.com
    service: http://127.0.0.1:3000
  # ... other hostnames
  - service: http_status:404
```

## 6. Run tunnel
```bash
cloudflared tunnel --config ~/.cloudflared/config.yml run trading-agent
```

## 7. Start backend
```bash
cd ~/novel_pipeline
.venv/bin/python -m app.mobile_api
```

## 8. Verify
```bash
curl https://novel-tnn.tradingcompanydirect.com/api/health
# → {"status":"ok","version":"0.1.0"}
```

## 9. Mobile app config
In Flutter app Settings:
- Backend URL: `https://novel-tnn.tradingcompanydirect.com`
- Save → Check → should show "Online"

## Important notes
- Cloudflare Universal SSL covers `*.tradingcompanydirect.com` only (one level).
  Do NOT use `*.sub.tradingcompanydirect.com` (two levels) — TLS handshake will fail.
- Cloudflare terminates TLS. Backend runs plain HTTP on localhost:7860.
- Tunnel auto-reconnects on restart. Add to systemd/cron for persistence.
- Rate limiting: free tier handles ~10 req/s, fine for single-user use.
- Before public remote access, follow the hardening checklist in `docs/deployment-hardening.md`.
