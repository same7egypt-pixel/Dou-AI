# DOU Fleet OS — Production Launch & Operations Runbook

## 1. Quick Launch with Docker Compose (Recommended)

### Prerequisites:
- Docker 24+ & Docker Compose v2+
- Domain DNS pointing to your host server

### Step-by-Step Deployment:
1. **Clone repository & prepare environment:**
   ```bash
   git clone https://github.com/same7egypt-pixel/Dou-AI.git /opt/dou-fleet
   cd /opt/dou-fleet
   cp .env.example .env
   ```
2. **Generate secure production secrets:**
   ```bash
   # Generate SECRET_KEY and ADMIN_KEY
   openssl rand -hex 32  # Paste into SECRET_KEY
   openssl rand -hex 16  # Paste into ADMIN_KEY
   openssl rand -hex 24  # Paste into POSTGRES_PASSWORD
   ```
3. **Run Pre-flight verification:**
   ```bash
   python scripts/preflight_check.py
   ```
4. **Launch containers:**
   ```bash
   docker compose up -d --build
   ```
5. **Verify health & readiness:**
   ```bash
   curl -i http://127.0.0.1:8123/health/ready
   ```

---

## 2. Nginx Reverse Proxy & SSL Configuration

Deploy Nginx config from `deploy/nginx/dou.conf` with Let's Encrypt:
```bash
sudo apt update && sudo apt install -y nginx certbot python3-certbot-nginx
sudo cp deploy/nginx/dou.conf /etc/nginx/sites-available/dou.conf
sudo ln -s /etc/nginx/sites-available/dou.conf /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
sudo certbot --nginx -d app.doufleet.com
```

---

## 3. Automated Daily Backups

Add cronjob for daily automated backups to S3:
```bash
0 2 * * * /opt/dou-fleet/scripts/backup.py >> /var/log/dou-backup.log 2>&1
```

---

## 4. Health & Monitoring Endpoints

| Endpoint | Purpose | Expected Status |
| :--- | :--- | :--- |
| `GET /health` | Liveness probe for load balancers | `200 OK` |
| `GET /health/ready` | Readiness probe (DB + Redis connectivity) | `200 OK` |
| `GET /health/metrics` | Platform uptime & system health | `200 OK` |

---

## 5. Security & Multi-Tenant Compliance

- **Multi-Tenant Isolation:** Enforced on database queries across all fleet and dispatch domains.
- **Security Headers:** Automatic CSP, HSTS, X-Frame-Options, and nosniff.
- **Rate Limiting:** Default 300 requests/minute per client IP.
