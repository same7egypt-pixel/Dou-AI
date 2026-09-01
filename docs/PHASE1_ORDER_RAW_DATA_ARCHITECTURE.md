# DOU Phase 1 — Multi-Tenant Order & Raw Data Architecture

## Purpose

This architecture supports fleet operations, rider performance, KPI/target calculation, incentives/deductions, payroll inputs, reconciliation, dashboards, and reporting for logistics companies and delivery platforms.

It is **not** the Phase 2 consumer ordering, merchant marketplace, smart-dispatch, or customer-tracking architecture.

## Mandatory boundary

The existing legacy `Order`, `Merchant`, and `CourierTask` delivery-network models are not reused as the Phase 1 source of truth because the legacy order model has no tenant ownership.

Every new source, raw record, mapping, normalized fact, reconciliation issue, derived metric, and payroll input must resolve to `tenant_id` through a server-controlled relationship.

## Design principles

1. Preserve raw source evidence before normalization.
2. Never calculate payroll directly from raw rows.
3. Separate ingestion, validation, mapping, normalization, approval, and derivation states.
4. Make repeated delivery idempotent.
5. Keep normalization/calculation versions.
6. Resolve rider and organization context as-of the event date.
7. Expose data trust/freshness, not just values.
8. Minimize and protect customer personal data.
9. Derive tenant from authenticated credentials or trusted connection configuration, never an untrusted payload alone.

## Proposed data model

### `operational_data_sources`

One external platform/source available to a tenant.

Key fields:

- `id`
- `tenant_id` — required
- `code` — tenant-unique stable code
- `platform_name` — Jahez, HungerStation, Ninja, internal TMS, etc.
- `source_type` — `CSV`, `XLSX`, `SFTP`, `API`, `WEBHOOK`, `MANUAL`
- `project_id` / `contract_id` — optional approved mapping
- `timezone`, `currency`, `market_code`
- `schema_version`
- `status` — `DRAFT`, `ACTIVE`, `SUSPENDED`, `RETIRED`
- `secret_reference` — pointer only; no plaintext credentials
- `created_by`, `created_at`, `updated_at`

Constraints/indexes:

- unique `(tenant_id, code)`
- index `(tenant_id, status)`

### `operational_import_batches`

The existing table can be retained for rider/performance imports but must be extended or complemented for raw order ingestion.

Required target fields:

- `tenant_id`, `source_id`
- `import_type` — `RIDERS`, `PERFORMANCE`, `DELIVERY_FACTS`
- `ingestion_mode`
- `schema_version`, `normalizer_version`
- `source_file_name`, `source_object_key`
- `content_sha256`
- `source_period_start`, `source_period_end`
- `received_at`, `created_by`
- row counts: received/valid/invalid/warning/unmapped/duplicate/accepted
- state: `RECEIVED`, `VALIDATED`, `MAPPING_REQUIRED`, `READY`, `COMMITTED`, `FAILED`, `SUPERSEDED`
- `confirmed_by`, `confirmed_at`
- failure/error summary without secrets or raw PII

Constraints:

- unique `(tenant_id, source_id, content_sha256)` where applicable
- all status transitions audited

### `operational_raw_rows`

Immutable row-level evidence for bounded-size imports, or metadata pointers when raw content is retained in object storage.

Key fields:

- `id`
- `tenant_id`, `source_id`, `batch_id`
- `row_number`
- `external_record_id`
- `raw_payload` — JSONB only for approved/minimized fields; otherwise object-storage pointer
- `payload_sha256`
- `source_event_at`, `received_at`
- `validation_status`
- `validation_issues` — structured JSON
- `pii_classification`
- `retention_until`

Constraints:

- unique `(batch_id, row_number)`
- optional unique `(tenant_id, source_id, payload_sha256)` for exact duplicate detection
- no update of source payload after receipt; corrections create new batches/rows

### `rider_source_identities`

Maps platform/source rider identifiers to DOU riders.

Key fields:

- `id`
- `tenant_id`, `source_id`, `courier_id`
- `external_rider_id`
- `external_rider_name/phone_hint` — masked/minimized as allowed
- `effective_from`, `effective_to`
- `status` — `PENDING`, `ACTIVE`, `REJECTED`, `ENDED`
- `match_method` — `EXACT_EXTERNAL_ID`, `PHONE_REVIEW`, `MANUAL`, `API_VERIFIED`
- `confidence`
- `reviewed_by`, `reviewed_at`

Constraints:

- unique active mapping `(tenant_id, source_id, external_rider_id)`
- mapping target courier must belong to the same tenant
- no silent fuzzy-match activation

### `delivery_facts`

Normalized, tenant-owned operational facts used by fleet analytics after validation/mapping.

Key fields:

- `id`
- `tenant_id`, `source_id`, `batch_id`, `raw_row_id`
- `external_delivery_id`
- `courier_id`
- organization as-of event: `project_id`, `contract_id`, `contract_branch_id`, `city_id`, `team_id`, `zone_id`, `supervisor_id`
- `service_date`
- lifecycle timestamps where supplied: offered/accepted/arrived/picked-up/delivered/cancelled
- normalized status — `COMPLETED`, `CANCELLED`, `FAILED`, `REJECTED`, `UNKNOWN`
- order counts default to one fact; aggregate source rows use an explicit `fact_granularity`
- distance and duration fields with units
- monetary fields only when approved: delivery fee, rider earning, COD amount, currency
- quality flags and trust level
- `normalizer_version`
- `source_updated_at`, `normalized_at`
- `superseded_by_id` for corrected source versions

Constraints/indexes:

- unique `(tenant_id, source_id, external_delivery_id, source_updated_at)` or source-specific immutable version key
- index `(tenant_id, service_date, project_id)`
- index `(tenant_id, courier_id, service_date)`
- index `(tenant_id, source_id, normalized_status, service_date)`
- tenant consistency validated for every referenced organization/rider record

### `delivery_fact_adjustments`

Controlled correction overlay; original facts stay immutable.

- tenant/fact ownership
- field/reason/category
- old/new approved values where safe
- requested/approved/rejected state
- actor, approver, timestamps
- audit link

### `data_reconciliation_runs`

Compares source declarations, raw rows, normalized facts, accepted KPI facts, and payroll inputs.

Key fields:

- `tenant_id`, `source_id`, `batch_id`
- expected/received/valid/mapped/normalized/accepted counts
- source amount totals and normalized totals where applicable
- status and tolerance policy version
- started/completed timestamps

### `data_reconciliation_issues`

- `tenant_id`, run/batch/raw/fact references
- issue type: duplicate, unmapped rider, invalid timestamp, missing project, amount mismatch, status conflict, late update, unknown schema
- severity
- owner and resolution state
- resolution action and audit actor

### `metric_definitions` and `metric_results`

A later Wave 3 layer; definitions and results must point to accepted normalized facts and calculation version. Results used by payroll must be frozen into the payroll-input ledger and final snapshot.

### `payroll_input_ledger`

One approved, reversible input stream for:

- delivery facts
- attendance events
- leave effects
- incentive/deduction rules
- approved manual adjustments

Key controls:

- tenant/rider/payroll period
- source type/source ID
- amount or quantity/unit
- rule and calculation version
- status `PENDING`, `APPROVED`, `REVERSED`, `LOCKED`
- idempotency key
- reversal reference rather than destructive update

## Pipeline

```text
Receive
  → persist immutable batch/raw evidence
  → validate source schema and values
  → detect exact/semantic duplicates
  → map source rider/project identities
  → normalize with versioned rules
  → reconcile totals and exceptions
  → human approval where policy requires
  → publish accepted delivery facts
  → derive KPI/target results
  → create approved payroll-input ledger entries
  → close payroll into immutable snapshots
```

Raw or unmapped rows never affect payroll/KPIs.

## State transitions

### Batch

```text
RECEIVED
  → VALIDATED
  → MAPPING_REQUIRED (when unresolved identities exist)
  → READY
  → COMMITTED
```

Alternatives:

- Any processing state → `FAILED`
- A committed batch corrected by a later authoritative batch → `SUPERSEDED` with explicit relationship

### Reconciliation issue

```text
OPEN → ASSIGNED → RESOLVED
                 → WAIVED (approved reason required)
```

No silent deletion of issues.

## API surface

### Tenant/company fleet APIs

- `GET/POST /fleet/data-sources`
- `GET/PATCH /fleet/data-sources/{id}`
- `POST /fleet/order-data/imports/preview`
- `POST /fleet/order-data/imports/{batch_id}/confirm`
- `GET /fleet/order-data/imports/{batch_id}`
- `GET /fleet/order-data/imports/{batch_id}/issues`
- `GET /fleet/order-data/facts`
- `GET /fleet/order-data/facts/{id}`
- `GET /fleet/order-data/reconciliation`
- `POST /fleet/order-data/mappings/{id}/approve|reject`
- `POST /fleet/order-data/issues/{id}/resolve|waive`

Every ID lookup includes tenant ownership and role/scope policy.

### Integration API

- `POST /integrations/v1/delivery-events`
- `POST /integrations/v1/import-manifests`

Tenant is derived from scoped API credential/connection. If a tenant hint is present, it must match the credential; it is never trusted as authorization.

Controls:

- request signature/API key scope
- idempotency key
- timestamp/replay window
- payload size/schema limits
- rate limit
- integration audit and correlation ID

## File import workflow

1. Upload to quarantine/object storage.
2. Calculate SHA-256 and create batch.
3. Parse in bounded streaming chunks.
4. Preserve raw evidence/pointer.
5. Show preview counts, mappings, errors, warnings, and replacement effects.
6. Confirm only by authorized role.
7. Normalize and reconcile transactionally per bounded chunk/job.
8. Present final result and immutable audit record.

Large files must not be placed in one JSON column or one web request transaction.

## KPI and payroll rules

- `DailyLog` may remain a compatibility aggregate during migration but is not the long-term raw/order fact source.
- Completed-order KPI counts only accepted `delivery_facts` matching the KPI definition/version.
- Late source corrections create reversals/recomputations in open periods.
- Closed payroll is never mutated; corrections enter a later adjustment period with reference to the original fact.
- Manual data is labeled `MANUAL` and is not presented as platform-verified.

## Security and privacy

- Minimize customer name, phone, and address; most fleet KPIs do not require them.
- Mask customer identifiers in UI/logs/exports unless explicitly authorized.
- Encrypt transport; store integration secrets in secret management, not database plaintext.
- Separate raw-object access from general dashboard access.
- Signed, short-lived object URLs.
- Retention by market/source/data class, followed by deletion/anonymization with audit.
- Audit raw export/download and mapping/payroll-impact decisions.
- Never expose one tenant’s source IDs in another tenant’s validation messages.

## Observability

Per source/batch:

- ingestion latency
- rows/sec
- valid/invalid/unmapped/duplicate ratio
- normalization/reconciliation duration
- late-arriving updates
- fact-to-payroll lag
- data freshness timestamp
- failure reason class without sensitive payload

## Phased implementation

### Slice 1 — CSV foundation

Source registry, delivery import batch, raw rows/pointers, rider mapping, completed-delivery facts, preview/confirm, basic reconciliation.

### Slice 2 — KPI/payroll lineage

Accepted facts to KPI definitions and payroll-input ledger; dashboard trust/freshness and drill-down.

### Slice 3 — API/webhook ingestion

Scoped credentials, signatures, idempotency, replay controls, async processing.

### Slice 4 — Enterprise reconciliation

Corrections, late updates, source totals, exception ownership, operator/platform rollups.

## Acceptance tests

- Cross-tenant source/batch/raw/fact/mapping IDs return not found.
- Same file/event repeated does not double count.
- External rider cannot map to another tenant’s courier.
- Unmapped/invalid rows produce no KPI/payroll input.
- Corrected facts preserve original provenance and create controlled reversals.
- Closed payroll snapshots do not change after late source data.
- Every KPI/payroll delivery input traces to a normalized fact and raw source.
- Legacy `orders` table is not queried by the new Phase 1 order-data service.
- Large import processing is bounded and recoverable.
