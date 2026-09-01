# DOU Fleet OS — Batch 2B Implementation & Acceptance Report
**Scope:** Driver Leaves & Approval Lifecycle E2E Acceptance (Rider 360 Leaves Subtab & Central Shifts Leave Approvals Queue)  
**Date:** 2026-08-31  
**Status:** **100% ACCEPTED & VERIFIED (18/18 PASS + 0 Regressions)**  

---

## 1. Executive Summary

In **Batch 2B**, we restored and verified the end-to-end operational lifecycle for **Driver Leave Management**:
1. **Rider 360 Profile — Leaves Tab (`🌴 الإجازات`)**:
   - **4 Entitlement KPI Cards**: `الرصيد المتاح (أيام)`, `إجمالي الاستحقاق`, `المستخدم`, and `طلبات معلقة`.
   - **Interactive Leave Request Action (`+ طلب إجازة`)**: Dedicated modal allowing Company Admin/Operations to submit leave requests selecting leave type (Annual, Sick, Emergency), start/end dates, and operational reason.
   - **Leaves History Table**: Real-time tabular log with localized status badges (`معتمد` [green], `قيد المراجعة` [amber], `معتمد مبدئياً` [blue], `مرفوض` [red]) and direct administrative approval/rejection actions.
2. **Centralized Shifts Operations — Leaves Approvals Queue (`🌴 طلبات الإجازات`)**:
   - **4 Central KPI Metrics**: Company-wide aggregates for `إجمالي طلبات الإجازة`, `قيد المراجعة`, `معتمدة`, and `مرفوضة`.
   - **Central Approval Queue Table**: Comprehensive overview of all leave requests across the company's entire workforce with courier names, leave types, date ranges, duration in days, and reasons.
   - **Status Filtering**: Instant filtering by `PENDING`, `APPROVED`, `REJECTED`, or `ALL`.
   - **Decision Modal**: Modal with reviewer comments and one-click `✅ اعتماد الإجازة` / `❌ رفض الإجازة` actions triggering `POST /leave/requests/{id}/admin-decide`.
3. **End-to-End Entitlement Deduction & Reflection**:
   - Approving a leave request immediately transitions the status to `APPROVED`, decrements `pending_days`, increments `used_days`, updates `available_days`, and reflects in real-time across both Rider 360 and the central approvals queue.

---

## 2. Technical Changes & Architecture

### A. Frontend Architecture
1. **[`frontend-v2/fleet/views/rider360.js`](file:///Users/sameh/DOU-review/dou-server/frontend-v2/fleet/views/rider360.js)**:
   - Implemented `renderLeave()`:
     - Fetches `GET /leave/entitlements/{id}` and `GET /leave/requests?courier_id={id}`.
     - Renders 4 KPI cards for available, entitled, used, and pending days.
     - Embeds `+ طلب إجازة` modal with automatic date validation and `POST /leave/requests` submission.
     - Direct decision actions for pending requests (`window.openLeaveDecisionModal`).
   - Implemented unified role resolver `getCurrentRole()` and integrated with all 8 profile tabs.
   - Implemented `window.decideDoc` for instant KYC document approvals/rejections (`POST /documents/{id}/review`).
2. **[`frontend-v2/fleet/views/shifts.js`](file:///Users/sameh/DOU-review/dou-server/frontend-v2/fleet/views/shifts.js)**:
   - Added 4th sub-tab `🌴 طلبات الإجازات` (`leaves`).
   - Implemented `renderLeavesTab()` with 4 company-wide KPI cards, status filter dropdown, and central review queue.
   - Added `openCentralLeaveDecisionModal()` and `submitCentralLeaveDecision()` posting to `/leave/requests/{id}/admin-decide`.
3. **[`frontend-v2/fleet/views/riders.js`](file:///Users/sameh/DOU-review/dou-server/frontend-v2/fleet/views/riders.js)**:
   - Refactored `window.openRider360` to pass initial state via `window.__rider360InitialId` and eliminated duplicate asynchronous reloads.

### B. Backend & Data Layer
1. **[`app/routers/leave.py`](file:///Users/sameh/DOU-review/dou-server/app/routers/leave.py)**:
   - Enriched `list_leave_requests` endpoint to return `courier_name` and `leave_type_name` along with request metadata.
   - Permitted direct administrative decisions for `PENDING` requests in `POST /leave/requests/{id}/admin-decide` (`status in ("SUPERVISOR_APPROVED", "PENDING")`).
2. **[`seed_demo.py`](file:///Users/sameh/DOU-review/dou-server/seed_demo.py)**:
   - Seeded active `LeaveType` records (`ANNUAL`, `SICK`, `EMERGENCY`).
   - Seeded `LeavePolicy` (21 entitlement days per year).
   - Seeded `LeaveEntitlement` records for all demo couriers.
   - Seeded representative `LeaveRequest` records in `PENDING` and `APPROVED` states.

---

## 3. Playwright Acceptance Test Results

### Test Suite: `e2e/batch2b-acceptance.mjs` (18/18 PASS — 100%)

| Test ID | Test Scenario | Expected Result | Actual Result | Status |
|---|---|---|---|:---:|
| **B2B-01** | Admin login | 200 OK + Auth session created | Status: 200 | **PASS** |
| **B2B-02** | Rider 360 profile loaded | Rider profile header and selector rendered | Opened rider profile | **PASS** |
| **B2B-03** | Rider 360 Leave tab opened | Leave container `#rider360-leave-wrap` rendered | Container rendered | **PASS** |
| **B2B-04** | Entitlement KPI metric cards | 4 cards (Available, Entitled, Used, Pending) | 4 metrics found | **PASS** |
| **B2B-05** | Request Leave button visible | `+ طلب إجازة` button rendered for admin/ops | Button found | **PASS** |
| **B2B-06** | Request Leave modal | Modal form with date pickers & reason input | Form modal rendered | **PASS** |
| **B2B-07** | Submit Leave Request API | `POST /leave/requests` returns 201 Created | Status: 201 | **PASS** |
| **B2B-08** | New request visible in rider table | New leave row appears with `قيد المراجعة` badge | Row found with unique reason | **PASS** |
| **B2B-09** | Central Leaves sub-tab exists | `🌴 طلبات الإجازات` sub-tab in Shifts view | Tab button found | **PASS** |
| **B2B-10** | Central leave KPI metrics cards | 4 KPI cards for company-wide leave counts | 4 metrics found | **PASS** |
| **B2B-11** | Central leave requests table | Table listing all company leave requests | Table container rendered | **PASS** |
| **B2B-12** | Central Decision Modal | Review modal displays courier, period, reason | Modal rendered | **PASS** |
| **B2B-13** | Admin Approve Leave API | `POST /leave/requests/{id}/admin-decide` (200 OK) | Status: 200 | **PASS** |
| **B2B-14** | Filter by Approved status | Approved request visible under `APPROVED` filter | Found approved status badge | **PASS** |
| **B2B-15** | Balance reflection in Rider 360 | Request updated to `معتمد` in rider profile | Approved badge found | **PASS** |
| **B2B-16** | Supervisor RBAC scope | Supervisor can access leaves tab | Leaves tab accessible | **PASS** |
| **B2B-17** | Browser Console Integrity | 0 unexpected JS console errors | 0 errors | **PASS** |
| **B2B-18** | Browser Runtime Integrity | 0 unhandled page runtime errors | 0 errors | **PASS** |

---

## 4. Full Regression Verification

Across the complete test suite:
- **`e2e/batch1b-acceptance.mjs`**: **39 / 39 PASSED (100%)**
- **`e2e/batch2a-acceptance.mjs`**: **23 / 23 PASSED (100%)**
- **`e2e/batch2b-acceptance.mjs`**: **18 / 18 PASSED (100%)**
- **Total Combined Tests:** **80 / 80 PASSED (100% PASS, 0 FAILURES, 0 REGRESSIONS)**
