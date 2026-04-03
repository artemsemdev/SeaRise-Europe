# Epic 02 — Local Development Environment

| Field          | Value                                                                                              |
| -------------- | -------------------------------------------------------------------------------------------------- |
| Phase          | 0                                                                                                  |
| Status         | Done                                                                                               |
| Effort         | ~2 days                                                                                            |
| Dependencies   | Epic 01 (provider decisions for geocoding and basemap inform environment variables)                 |
| Produces       | Docker Compose local dev, local PostgreSQL schema, local blob storage, basic CI pipeline            |

> **Change history (v0.2, 2026-04-02):** This epic was formerly titled "Cloud Infrastructure and CI/CD" (~5 days). It has been re-scoped to cover only the local development environment. All Azure resource provisioning (Resource Group, Container Apps, Key Vault, Container Registry, Blob Storage account), CI/CD deployment pipelines, and staging deployment have moved to Epic 08 (Azure Deployment, Release Hardening, and Go-Live). This change implements the local-first delivery strategy: build, run, and test locally before touching the cloud.

---

## 1  Context

SeaRise Europe is a three-container web app: Next.js frontend, ASP.NET Core API, TiTiler tile server. During development, these run locally via Docker Compose backed by a local PostgreSQL instance (with PostGIS) and local blob storage (Azurite emulator or filesystem mount). No Azure resources are needed until Epic 08.

---

## 2  Product Requirement Traceability

- **NFR-005** — HTTPS (deferred to Epic 08 for cloud; local uses HTTP)
- **NFR-011** — Health endpoints
- **NFR-019** — Stateless
- **NFR-020** — COG format
- **NFR-023** — No Kubernetes

---

## 3  Architecture Traceability

| Document                                               | Relevance                            |
| ------------------------------------------------------ | ------------------------------------ |
| `docs/architecture/08-deployment-topology.md`          | Section 5.1 — Docker Compose spec   |
| `docs/architecture/05-data-architecture.md`            | Full database schema                 |
| `docs/architecture/02-container-view.md`               | Container responsibilities           |
| `docs/architecture/09-observability-and-operations.md` | Local logging                        |

---

## 4  User Stories

### S02-01  Set Up Docker Compose Local Development Environment

| Field          | Value                                                           |
| -------------- | --------------------------------------------------------------- |
| Type           | Platform                                                        |
| Effort         | ~1 day                                                          |
| Traceability   | NFR-023                                                         |
| Architecture   | `docs/architecture/08-deployment-topology.md` section 5.1       |

**Statement.** As the engineer maintaining delivery quality, I want a Docker Compose configuration that runs all three containers plus PostgreSQL and local blob storage, so that development and testing can proceed without any Azure dependency.

**Acceptance Criteria**

1. `docker-compose.yml` starts frontend (port 3000), api (port 8080), tiler (port 8000), postgres (port 5432), and azurite (port 10000) or equivalent local blob storage.
2. PostgreSQL is seeded with schema on startup via `init.sql` mount.
3. `.env.local.example` documents required environment variables.
4. TiTiler reads COG files from local storage (Azurite or filesystem volume mount).
5. All containers start without errors and health endpoints respond.

**Testing.** Manual verification — `docker compose up`, curl health endpoints, verify TiTiler can serve a sample COG.

**Evidence.** `docker compose ps` output, curl responses from `/health` and `/healthz`.

---

### S02-02  Deploy Local PostgreSQL Schema and Enable PostGIS

| Field          | Value                                                           |
| -------------- | --------------------------------------------------------------- |
| Type           | Platform                                                        |
| Effort         | ~0.5 days                                                       |
| Traceability   | NFR-020                                                         |
| Architecture   | `docs/architecture/05-data-architecture.md` section 2           |

**Statement.** As the system, I need the PostgreSQL schema deployed locally with PostGIS extension and all tables created, so that the pipeline and API have a functional local data store.

**Acceptance Criteria**

1. PostGIS extension is enabled (`CREATE EXTENSION postgis` succeeds).
2. All 5 tables exist: `scenarios`, `horizons`, `methodology_versions`, `layers`, `geography_boundaries`.
3. GIST index on `geography_boundaries.geom` exists.
4. Composite index on `layers` exists.
5. Schema matches `docs/architecture/05-data-architecture.md` section 2 exactly.
6. Schema applies automatically on `docker compose up` via init script.

**Testing.** Infrastructure verification — `\dt` listing, `\di` index listing, `SELECT PostGIS_Version()`.

**Evidence.** `psql` session output showing tables, indexes, and PostGIS version.

---

### S02-03  Establish Basic CI Pipeline (GitHub Actions)

| Field          | Value                                                           |
| -------------- | --------------------------------------------------------------- |
| Type           | Platform                                                        |
| Effort         | ~0.5 days                                                       |
| Traceability   | NFR-009                                                         |
| Architecture   | `docs/architecture/08-deployment-topology.md` section 6         |

**Statement.** As the engineer maintaining delivery quality, I want a GitHub Actions CI pipeline that runs lint, type checks, and unit tests on every pull request, so that code quality is validated from the earliest commits.

**Acceptance Criteria**

1. CI workflow triggers on pull request to main: lint, type check, unit tests, Docker build for all three images.
2. CI passes on a test PR.
3. No deployment steps — deployment is deferred to Epic 08.

**Testing.** Trigger CI on a test PR, verify all steps pass.

**Evidence.** GitHub Actions run output showing green CI.

> **Note:** The CI/CD deployment pipeline (push images to ACR, deploy to staging, smoke test gate) is established in Epic 08 when Azure resources are provisioned.

---

## 5  Epic-Level Information

### 5.1  Objective

Establish the Docker Compose local development environment and basic CI pipeline so that all subsequent epics can develop, run, and test locally without Azure dependency.

### 5.2  Why This Epic Exists

The pipeline (Epic 03) needs local PostgreSQL and local blob storage to store COGs and register layers. The API (Epic 04) needs local PostgreSQL and a local TiTiler instance. No feature work can proceed without a local runtime environment. This epic provides that foundation while deferring all Azure provisioning to Epic 08.

### 5.3  In Scope

- Docker Compose configuration with all containers, PostgreSQL, and local blob storage (Azurite or filesystem).
- PostgreSQL schema deployment with PostGIS (locally).
- `.env.local.example` documenting required environment variables.
- Basic GitHub Actions CI (lint, type check, unit tests, Docker build).

### 5.4  Out of Scope (Deferred to Epic 08)

- Azure resource provisioning (Resource Group, Container Apps, Key Vault, Container Registry, Blob Storage account).
- Azure PostgreSQL Flexible Server provisioning.
- CI/CD deployment pipeline (push to ACR, deploy to staging, smoke test gate).
- Container Apps Environment and staging deployment.
- Key Vault secrets configuration.
- Custom domains and TLS.
- CDN configuration.
- Analytics infrastructure (OQ-10).

### 5.5  Implementation Plan

Start with Docker Compose (S02-01) since everything depends on it. Then schema deployment (S02-02) in sequence. Basic CI (S02-03) can be developed in parallel with S02-02.

### Execution Order Map

```
S02-01 (Docker Compose + Local Blob Storage)
  │
  ├──► S02-02 (PostgreSQL Schema + PostGIS)
  │
  └──► S02-03 (Basic CI Pipeline)    ◄── parallel with S02-02
```

### 5.6  Technical Deliverables

- Docker Compose configuration (`docker-compose.yml`).
- Database `init.sql` script.
- `.env.local.example` file.
- GitHub Actions CI workflow (`.github/workflows/ci.yml`).

---

## 6  Data, API, and Infrastructure Impact

This epic creates the local development foundation. All subsequent epics depend on Docker Compose being operational. No Azure resources are created or modified.

---

## 7  Security and Privacy

- `.env.local` is gitignored — no secrets committed to the repository.
- PostgreSQL is accessible only from Docker Compose network (not exposed to the internet).
- Local blob storage does not require authentication configuration.

---

## 8  Observability

- Container stdout is visible via `docker compose logs`.
- No Log Analytics or cloud monitoring in this epic.

---

## 9  Testing

- Docker Compose smoke test (all containers start, health endpoints respond).
- CI pipeline execution validation (lint, type check, unit tests pass on test PR).

---

## 10  Risks and Assumptions

| #  | Type       | Description                                                                                        | Mitigation / Note                                                        |
| -- | ---------- | -------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------ |
| R1 | Risk       | Azurite may not perfectly emulate Azure Blob Storage behavior for TiTiler GDAL VSIAZ driver.       | Test TiTiler against Azurite early. Fallback: mount COGs via filesystem volume. |
| R2 | Risk       | PostGIS extension version in local Docker image may differ from Azure Flexible Server version.      | Pin postgis/postgis Docker image version. Verify version parity in Epic 08. |
| A1 | Assumption | Docker Desktop (or equivalent) is installed and functional on the development machine.              | —                                                                        |
| A2 | Assumption | GitHub Actions has access to run CI workflows on pull requests.                                     | —                                                                        |

---

## 11  Epic Acceptance Criteria

1. Docker Compose starts all containers and local blob storage without errors.
2. PostgreSQL has PostGIS enabled, all 5 tables created, all indexes created (locally).
3. TiTiler can read a sample COG from local storage.
4. Health endpoints respond correctly on localhost.
5. GitHub Actions CI triggers on PR and passes lint + type check + unit tests.
6. No Azure resources are provisioned.

---

## 12  Definition of Done

- All 3 stories completed with evidence.
- Docker Compose verified locally (all containers healthy).
- PostgreSQL schema verified locally.
- CI pipeline tested end-to-end (lint + tests pass on test PR).
- No unresolved local infrastructure blocker.
- Documentation updated (`.env.local.example`, Docker Compose usage notes).

---

## 13  Demo / Evidence

- Docker Compose running: `docker compose ps` output.
- PostgreSQL schema verification: `psql` session output.
- Health endpoint responses: curl output from `localhost:3000`, `localhost:8080/health`, `localhost:8000/healthz`.
- TiTiler COG read: sample tile or `/point` response from local TiTiler.
- GitHub Actions CI run output (green).
