# DOU AI + W11-Lite Security Runbook

## Webhook HMAC Secret

### Design

- `NOTIFICATION_WEBHOOK_SECRET` is the dedicated HMAC signing key for incoming
  Metabase alert webhooks.
- It is **independent** from `SECRET_KEY`, `ADMIN_KEY`, `METABASE_WEBHOOK_SECRET`,
  and any password/credential hash stored in the database.
- It must never be derived from a one-way hash (e.g., `WebhookEndpoint.secret_hash`).
  A hash cannot serve as an HMAC key.

### Secret Generation

Generate a cryptographically random 32+ byte secret:

```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

### Environment Configuration

```env
NOTIFICATION_WEBHOOK_SECRET=<generated-hex>
NOTIFICATION_WEBHOOK_MAX_AGE_SECONDS=300
NOTIFICATION_WEBHOOK_CLOCK_SKEW_SECONDS=30
```

### Signature Construction (Metabase / sender side)

```python
import hmac, hashlib, time

timestamp = str(int(time.time()))
body = json.dumps(payload, separators=(",", ":")).encode()
message = f"{timestamp}.".encode() + body
signature = "sha256=" + hmac.new(SECRET.encode(), message, hashlib.sha256).hexdigest()

headers = {
    "Content-Type": "application/json",
    "X-DOU-Timestamp": timestamp,
    "X-DOU-Signature": signature,
}
```

### Verification (DOU side)

1. Reject if `X-DOU-Timestamp` or `X-DOU-Signature` is missing.
2. Parse timestamp as integer; reject if malformed.
3. Reject if timestamp is older than `NOTIFICATION_WEBHOOK_MAX_AGE_SECONDS` (default 300s).
4. Reject if timestamp is more than `NOTIFICATION_WEBHOOK_CLOCK_SKEW_SECONDS` in the future.
5. Compute HMAC-SHA256 over `"{timestamp}." + raw_body` using `NOTIFICATION_WEBHOOK_SECRET`.
6. Compare using constant-time comparison.
7. Only then parse the JSON payload and resolve the tenant via admin-controlled mapping.

### Rotation

1. Generate a new secret.
2. Deploy with both secrets accepted (grace period).
3. Switch sender to new secret.
4. Remove old secret from acceptor after all in-flight alerts expire
   (≥ `MAX_AGE_SECONDS`).

### What NOT to do

- Do NOT reuse `WebhookEndpoint.secret_hash` (one-way → cannot sign).
- Do NOT commit the real secret.
- Do NOT print or log the real secret.
- Do NOT use the same secret for auth and webhook signing.
- Do NOT trust a payload's own `tenant_id` without signature verification.
