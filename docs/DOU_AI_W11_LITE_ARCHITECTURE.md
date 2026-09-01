# DOU AI Deterministic Conversational BI Architecture

## Production path

`Browser → DOU auth → deterministic parser → validated ReportSpec → report registry → RBAC/tenant scope → Native DOU report or approved Metabase question → structured response`

DOU AI is an intelligent operations assistant, not a generic chatbot. Phase 1 production operation has **no LLM dependency**. Ollama, Qwen, GPT, Metabot, and external AI APIs are not called by the `/ai/chat` or `/ai/status` paths and are not runtime prerequisites.

## Security boundary

- Tenant, Operator, Supervisor, Project Manager, rider, project, city, and page-context scope are derived or revalidated server-side.
- Prompt text and ReportSpec are never authority.
- Browser values cannot select tenant scope, arbitrary SQL, table names, saved-question IDs, or query plans.
- The report registry is deny-by-default for roles, customer types, operations, metrics, filters, grouping, sorting, periods, outputs, sources, and deep links.
- `LOGISTICS_OPERATOR` and `DELIVERY_PLATFORM` retain different hierarchies. Operator is never treated as Supervisor.
- Financial figures remain in protected Native DOU workflows.

## ReportSpec

A conversation is represented by a validated ReportSpec containing operation, entity, metric, filter identifiers, period, comparison, grouping, sort, limit, output preference, report key, and source. It is persisted inside the assistant message's structured JSON and restored only from the same tenant/user-owned conversation.

Follow-ups copy and modify the previous spec. Entity aliases such as city names are resolved against active tenant-owned catalogs before validation. Unknown, ambiguous, cross-tenant, and out-of-scope identifiers fail closed.

## Registry and sources

The current Phase 1 registry contains composable definitions for rider performance, attendance summary, Operator performance, order performance, workforce summary, needs attention, and import health.

Native DOU is preferred for real-time and authorization-sensitive data. The registry supports an approved `METABASE` source and server-owned saved-question IDs, but no production report is marked Metabase until a saved question and its tenant-filter contract are explicitly approved. Metabase remains an optional analytics engine and notification source; Metabot is not used.

## Structured response

Responses support `answer`, `kpis`, `table`, `chart`, `report_link`, `source`, `freshness`, `warnings`, `suggested_followups`, and `report_spec`. Unknown or ambiguous requests return deterministic clarification choices without operational numbers.

Open Report links are generated only from registry-owned internal `/app?...` destinations. Whitelisted period, comparison, grouping, sort, limit, and validated entity filter IDs are URL-encoded so users do not reconfigure the report.

## Availability and observability

`GET /ai/status` reports deterministic capability health and does not check model availability. `ai_request_logs` records route, source, latency, success, and error category without storing prompts in telemetry. Native-supported questions remain usable if Metabase is unavailable.

## Notifications

Analytical alerts remain independent of conversational BI:

`authenticated source instance → timestamp/nonce-bound HMAC → admin-owned AlertSourceMapping → tenant/role routing → Notification Center`

The closed webhook security design remains unchanged.

## Configuration

```env
DOU_AI_MODE=DETERMINISTIC
METABASE_WEBHOOK_SECRET=<strong local secret>
NOTIFICATION_DEDUPE_MINUTES=60
```

No model service, model URL, model name, model download, or AI API key is required for normal DOU operation. Legacy local model installations may remain on a developer machine but are outside the production path.
