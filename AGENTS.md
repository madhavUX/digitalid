# AGENTS.md — Coding Rules for AI Agents

This file is binding for every AI agent and contributor working in this repository.
If any instruction here conflicts with a user request, **stop and ask for clarification**.

---

## 1. Source of Truth

The following documents define the approved architecture:

| Document | Defines |
|---|---|
| `docs/PRD.md` | Product vision, users, journeys, module scope |
| `docs/ARCHITECTURE.md` | System boundaries, layers, deployment |
| `docs/DATABASE.md` | Entities, fields, relationships, constraints |
| `docs/API.md` | Endpoints, conventions, auth, errors |

**Read the relevant documents before writing any code.** For a task touching the database, read `docs/DATABASE.md`. For a task touching endpoints, read `docs/API.md`. For anything structural, read `docs/ARCHITECTURE.md`.

---

## 2. Do Not Invent Architecture

- Do not add new apps, services, layers, queues, caches, or third-party dependencies that are not described in `docs/ARCHITECTURE.md`.
- Do not introduce a new architectural pattern because it is "cleaner".
- Do not create models, tables, or fields that are not in `docs/DATABASE.md`.
- Do not create endpoints that violate the conventions in `docs/API.md`.

If the documented architecture does not cover your task, **ask before proceeding**. Then update the docs in the same change.

---

## 3. Scope Discipline

- Do not modify modules unrelated to the current task.
- Do not refactor, reformat, or "clean up" files you were not asked to touch.
- Do not upgrade dependencies as a side effect of a feature task.
- Do not delete or rewrite existing tests to make new code pass.

One task, one coherent change.

---

## 4. Business Logic Placement

Business logic lives in the **service layer** (`<app>/services.py` or `<app>/services/`).

| Layer | Allowed | Not allowed |
|---|---|---|
| Model | Field definitions, constraints, simple derived properties | Cross-entity orchestration, external calls |
| Serializer | Field shape, format validation, presentation | Business rules, DB writes across entities, side effects |
| View | HTTP concerns, permissions, calling one service | Business rules, multi-step orchestration |
| Service | Business rules, transactions, orchestration | HTTP status codes, request parsing |
| Task (Celery) | Async orchestration by calling services | Duplicated business logic |

**Do not duplicate business logic.** If a rule exists in a service, call that service — do not reimplement it in a view, task, serializer, admin action, or management command.

**Do not put critical business logic in React/Next.js components.** The frontend may perform UX-level validation for responsiveness, but the backend must re-validate and remains authoritative. Booking availability, pricing, quota enforcement, and permission decisions are backend-only.

---

## 5. Tenant Isolation (Non-Negotiable)

- **Never trust `tenant_id`, `organization_id`, `business_id`, or `location_id` supplied by the client** in a request body, query string, header, or JWT claim used as authority.
- The current organization is resolved **server-side** from the authenticated user's membership. See `core/mixins.py` and `organizations/services.resolve_current_membership`.
- **Every query against a tenant-owned model must be tenant-scoped.** A bare `Model.objects.all()` or `Model.objects.get(pk=...)` on a tenant-owned model is a defect.
- Scoping by a path/body identifier alone is not sufficient. The identifier must be validated against the resolved tenant, or the queryset must be filtered by the resolved tenant first.
- Cross-tenant access must return `404` (not `403`) so tenant boundaries do not leak existence information.
- Platform administration is separate from organization roles. Do not grant cross-tenant access via an organization role.

Correct:

```python
Appointment.objects.filter(location__business__organization=request.organization, id=appointment_id)
```

Incorrect:

```python
Appointment.objects.get(id=request.data["appointment_id"])
Appointment.objects.filter(organization_id=request.data["organization_id"])
```

---

## 6. Database Changes

- **Do not silently change database architecture.** Any change to entities, fields, relationships, indexes, or constraints requires a matching update to `docs/DATABASE.md` in the same change.
- Do not edit an existing applied migration. Add a new one.
- Do not delete migrations.
- Do not use raw SQL where the ORM is sufficient. If raw SQL is required, parameterize it and document why.
- Destructive migrations (drop column, drop table, narrowing a type) require explicit approval.
- New tenant-owned tables must carry the tenant foreign key and the indexes described in `docs/DATABASE.md`.

---

## 7. Testing

- **Add tests for business-critical functionality.** Business-critical means: authentication, authorization, tenant isolation, booking, availability, payments, subscription limits, and anything that writes money or customer data.
- Every new tenant-owned endpoint requires a test proving Organization A cannot read or write Organization B data.
- Every new service function containing a business rule requires a test for the rule and at least one failure path.
- **Run the test suite after changes.** Do not report a task complete without a passing run.
- Do not weaken assertions to force a pass.

```bash
python manage.py test
```

---

## 8. Lint and Type Checks

Run before reporting completion:

```bash
ruff check .
ruff format --check .
python manage.py check
```

Fix issues you introduced. Do not mass-fix pre-existing issues in unrelated files as part of a feature task.

---

## 9. Security Baseline

- No secrets in source. All configuration comes from environment variables.
- Never log secrets, tokens, passwords, or full customer PII.
- Validate and normalize all external input at the boundary.
- Webhooks must verify signatures before processing.
- Public (unauthenticated) endpoints must be explicitly marked and must never expose tenant-internal data.

---

## 10. When Requirements Conflict

If a request conflicts with the documented architecture — for example, asking to trust a client-supplied tenant ID, to put booking rules in the frontend, or to add an undocumented table — **do not implement it silently**.

Stop, state the conflict, reference the specific document and rule, and ask how to proceed.

---

## 11. Definition of Done

A change is complete when:

1. Code follows the documented architecture.
2. Tenant-owned queries are tenant-scoped.
3. Business logic is in the service layer.
4. Tests exist for business-critical behavior and the suite passes.
5. Lint and Django checks pass.
6. Documentation is updated if architecture, schema, or API surface changed.
7. No unrelated files were modified.
8. The report lists changed files and test results.
