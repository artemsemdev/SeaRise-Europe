# Epic 02 — Cloud Infrastructure and CI/CD

| Field          | Value                                                                                              |
| -------------- | -------------------------------------------------------------------------------------------------- |
| Phase          | 0                                                                                                  |
| Status         | Not Started                                                                                        |
| Effort         | ~5 days                                                                                            |
| Dependencies   | Epic 01 (provider decisions for geocoding and basemap inform Key Vault secrets and environment variables) |
| Produces       | Azure resources, Docker Compose local dev, CI/CD pipeline                                          |

---

## 1  Context

SeaRise Europe is a three-container web app: Next.js frontend, ASP.NET Core API, TiTiler tile server. Backed by Azure Database for PostgreSQL (PostGIS), Azure Blob Storage (COG files), Azure Key Vault (secrets), Azure Container Registry (images). Hosted on Azure Container Apps. Target region: West Europe.

---

## 2  Azure Resources to Provision

| Resource                                          | Name / SKU                                           |
| ------------------------------------------------- | ---------------------------------------------------- |
| Resource Group                                    | `rg-searise-europe-prod`                             |
| Container Apps Environment                        | `cae-searise-europe`                                 |
| Azure Database for PostgreSQL Flexible Server     | Burstable B1ms, PostGIS enabled                      |
| Azure Blob Storage Account                        | LRS, Hot tier, container: `geospatial`, private      |
| Azure Key Vault                                   | `kv-searise-europe`                                  |
| Azure Container Registry                          | `acr-seariseeurope` (Basic tier)                     |
| Log Analytics Workspace                           | `law-searise-europe`                                 |

---

## 3  Product Requirement Traceability

- **NFR-005** — HTTPS
- **NFR-006** — No secrets in client
- **NFR-009** — 99.5 % availability
- **NFR-011** — Health endpoints
- **NFR-019** — Stateless
- **NFR-020** — COG format
- **NFR-023** — No Kubernetes

---

## 4  Architecture Traceability

| Document                                               | Relevance                            |
| ------------------------------------------------------ | ------------------------------------ |
| `docs/architecture/08-deployment-topology.md`          | Primary reference                    |
| `docs/architecture/07-security-architecture.md`        | Key Vault, managed identity          |
| `docs/architecture/02-container-view.md`               | Container responsibilities           |
| `docs/architecture/09-observability-and-operations.md` | Log Analytics                        |

---

## 5  User Stories

### S02-01  Provision Azure Resource Group and Core Services

| Field          | Value                                                           |
| -------------- | --------------------------------------------------------------- |
| Type           | Infrastructure                                                  |
| Effort         | ~1 day                                                          |
| Traceability   | NFR-023, NFR-009                                                |
| Architecture   | `docs/architecture/08-deployment-topology.md` section 2              |

**Statement.** As the engineer maintaining delivery quality, I want all core Azure resources provisioned in West Europe, so that the pipeline, API, and frontend have a deployment target.

**Acceptance Criteria**

1. Resource group exists in West Europe.
2. PostgreSQL Flexible Server is running with PostGIS extension enabled.
3. Blob Storage account exists with private `geospatial` container.
4. Key Vault exists.
5. Container Registry exists.
6. Log Analytics Workspace exists and is connected to the Container Apps Environment.

**Testing.** Infrastructure verification — `az` CLI commands confirm resource existence and configuration.

**Evidence.** `az resource list` output, PostgreSQL connection test, Blob container listing.

---

### S02-02  Configure Key Vault and Secrets

| Field          | Value                                                           |
| -------------- | --------------------------------------------------------------- |
| Type           | Infrastructure                                                  |
| Effort         | ~0.5 days                                                       |
| Traceability   | NFR-006, NFR-005                                                |
| Architecture   | `docs/architecture/07-security-architecture.md` section 3            |

**Statement.** As the system, I need all application secrets stored in Azure Key Vault, so that no credentials appear in source code, Docker images, or environment variable literals.

**Acceptance Criteria**

1. Key Vault contains secrets for: `postgres-connection-string`, `blob-storage-connection-string`, `geocoding-provider-api-key` (placeholder until Epic 01 provider is confirmed), `cors-allowed-origins`.
2. Container Apps can reference Key Vault secrets via `secretref` syntax.
3. No secrets are committed to the repository.

**Testing.** Infrastructure verification — Key Vault secret list, Container Apps secret reference validation.

**Evidence.** Key Vault secret list (names only, not values), Container Apps configuration showing `secretref` usage.

---

### S02-03  Deploy PostgreSQL Schema and Enable PostGIS

| Field          | Value                                                           |
| -------------- | --------------------------------------------------------------- |
| Type           | Platform                                                        |
| Effort         | ~0.5 days                                                       |
| Traceability   | NFR-020                                                         |
| Architecture   | `docs/architecture/05-data-architecture.md` section 2 (full schema)  |

**Statement.** As the system, I need the PostgreSQL schema deployed with PostGIS extension and all tables created, so that the pipeline and API have a functional data store.

**Acceptance Criteria**

1. PostGIS extension is enabled (`CREATE EXTENSION postgis` succeeds).
2. All 5 tables exist: `scenarios`, `horizons`, `methodology_versions`, `layers`, `geography_boundaries`.
3. GIST index on `geography_boundaries.geom` exists.
4. Composite index on `layers` exists.
5. Schema matches `docs/architecture/05-data-architecture.md` section 2 exactly.

**Testing.** Infrastructure verification — `\dt` listing, `\di` index listing, `SELECT PostGIS_Version()`.

**Evidence.** `psql` session output showing tables, indexes, and PostGIS version.

---

### S02-04  Set Up Docker Compose Local Development Environment

| Field          | Value                                                           |
| -------------- | --------------------------------------------------------------- |
| Type           | Platform                                                        |
| Effort         | ~1 day                                                          |
| Traceability   | NFR-023                                                         |
| Architecture   | `docs/architecture/08-deployment-topology.md` section 5.1            |

**Statement.** As the engineer maintaining delivery quality, I want a Docker Compose configuration that runs all three containers plus PostgreSQL locally, so that development and testing can proceed without Azure dependency.

**Acceptance Criteria**

1. `docker-compose.yml` starts frontend (port 3000), api (port 8080), tiler (port 8000), and postgres (port 5432).
2. PostgreSQL is seeded with schema on startup via `init.sql` mount.
3. `.env.local.example` documents required environment variables.
4. TiTiler can read from local or Azure Blob Storage (configurable).
5. All containers start without errors and health endpoints respond.

**Testing.** Manual verification — `docker compose up`, curl health endpoints.

**Evidence.** `docker compose ps` output, curl responses from `/health` and `/healthz`.

---

### S02-05  Establish CI/CD Pipeline (GitHub Actions)

| Field          | Value                                                           |
| -------------- | --------------------------------------------------------------- |
| Type           | Platform                                                        |
| Effort         | ~1.5 days                                                       |
| Traceability   | NFR-009                                                         |
| Architecture   | `docs/architecture/08-deployment-topology.md` section 6              |

**Statement.** As the engineer maintaining delivery quality, I want a GitHub Actions CI/CD pipeline that builds, tests, and deploys containers, so that code changes are validated and deployable automatically.

**Acceptance Criteria**

1. CI workflow triggers on pull request to main: lint, type check, unit tests, Docker build for all three images.
2. CD workflow triggers on merge to main: push images to ACR (tagged with git SHA), deploy to staging Container Apps, run smoke test (`curl /health`).
3. Smoke test failure blocks production deployment.
4. Azure credentials are stored as GitHub repository secrets (not in workflow files).

**Testing.** Deployment verification — trigger CI on a test PR, verify all steps pass.

**Evidence.** GitHub Actions run output showing green CI and successful staging deployment.

---

### S02-06  Provision Container Apps Environment (Staging)

| Field          | Value                                                           |
| -------------- | --------------------------------------------------------------- |
| Type           | Infrastructure                                                  |
| Effort         | ~0.5 days                                                       |
| Traceability   | NFR-023, NFR-019, NFR-011                                       |
| Architecture   | `docs/architecture/08-deployment-topology.md` section 3              |

**Statement.** As the engineer maintaining delivery quality, I want Container Apps deployed for the API container in staging, so that the CI/CD pipeline has a deployment target and infrastructure assumptions can be validated.

**Acceptance Criteria**

1. Container Apps Environment exists.
2. At least the API container app is deployed (`ca-api`) with external ingress, health probes configured, and Key Vault secret references.
3. Container app scales to zero when idle.
4. Custom domain and TLS are configured (or documented as a later step).
5. Health endpoint responds correctly on the public URL.

**Testing.** Infrastructure verification — `az containerapp show`, `curl /health` on public URL.

**Evidence.** `az containerapp show` output, `curl /health` response from staging URL.

---

## 6  Epic-Level Information

### 6.1  Objective

Provision all Azure infrastructure, establish Docker Compose local development, and set up CI/CD pipeline so that the geospatial pipeline and application code have deployment targets.

### 6.2  Why This Epic Exists

The pipeline (Epic 03) needs Blob Storage and PostgreSQL to upload COGs and register layers. The API (Epic 04) needs PostgreSQL, Blob Storage, and Key Vault. No feature work can proceed without infrastructure. The CI/CD pipeline ensures code quality from the earliest commits.

### 6.3  In Scope

- Azure resource provisioning.
- PostgreSQL schema deployment with PostGIS.
- Key Vault secrets.
- Docker Compose local development.
- GitHub Actions CI/CD.
- Container Apps Environment with at least the API container deployed to staging.

### 6.4  Out of Scope

- Full three-container Container Apps deployment (completed incrementally in later epics as containers are built).
- Custom domains and production DNS.
- CDN configuration.
- Load testing infrastructure.
- Analytics infrastructure (OQ-10).

### 6.5  Implementation Plan

Start with Azure resource provisioning (S02-01) since everything depends on it. Then Key Vault (S02-02) and schema (S02-03) in sequence. Docker Compose (S02-04) can be developed alongside Azure work. CI/CD (S02-05) and Container Apps (S02-06) last.

### Execution Order Map

```
S02-01 (Provision Azure Resources)
  │
  ├──► S02-02 (Key Vault + Secrets)
  │       │
  │       └──► S02-03 (PostgreSQL Schema + PostGIS)
  │
  ├──► S02-04 (Docker Compose Local Dev)    ◄── parallel with S02-02/S02-03
  │
  └──► S02-05 (CI/CD Pipeline)             ◄── after S02-01; parallel with S02-03/S02-04
         │
         └──► S02-06 (Container Apps Staging)  ◄── needs CI/CD + Key Vault
```

**Rationale:** S02-01 is the prerequisite for all Azure work. S02-02 and S02-03 are sequential (schema deployment needs connection string from Key Vault). S02-04 (Docker Compose) is independent local work that can proceed in parallel with Azure provisioning. S02-05 (CI/CD) needs the container registry from S02-01 but not the database. S02-06 needs both CI/CD and Key Vault secrets to deploy.

### 6.6  Technical Deliverables

- Azure resources provisioned (or Bicep/Terraform templates).
- Docker Compose configuration.
- GitHub Actions workflows (`.github/workflows/ci.yml`, `.github/workflows/cd.yml`).
- Database `init.sql` script.
- `.env.local.example` file.

---

## 7  Data, API, and Infrastructure Impact

This epic creates the infrastructure foundation. All subsequent epics depend on these resources being available.

---

## 8  Security and Privacy

- Key Vault must be the only location for secrets.
- PostgreSQL must not be publicly accessible.
- Blob Storage container must be private.
- Managed identity should be configured for Blob access where possible.

---

## 9  Observability

- Log Analytics Workspace connected to Container Apps Environment.
- Container stdout routed to Log Analytics.

---

## 10  Testing

- Infrastructure verification via `az` CLI.
- Docker Compose smoke test.
- CI/CD pipeline execution validation.

---

## 11  Risks and Assumptions

| #  | Type       | Description                                                                                        | Mitigation / Note                                                        |
| -- | ---------- | -------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------ |
| R1 | Risk       | Azure subscription quota limits could block resource provisioning.                                 | Check quotas before provisioning.                                        |
| R2 | Risk       | PostGIS extension may not be enabled by default on Flexible Server.                                | Enable via `az` CLI or Azure Portal during provisioning.                 |
| A1 | Assumption | Azure subscription is available with sufficient credits.                                           | —                                                                        |
| A2 | Assumption | GitHub Actions has access to Azure credentials via OIDC or service principal.                      | —                                                                        |

---

## 12  Epic Acceptance Criteria

1. All Azure resources listed in section 2 exist and are operational.
2. PostgreSQL has PostGIS enabled, all 5 tables created, all indexes created.
3. Key Vault contains all required secrets (no secrets in source code).
4. Docker Compose starts all services locally and health endpoints respond.
5. GitHub Actions CI triggers on PR and passes lint + build.
6. GitHub Actions CD deploys the API container to staging.
7. Staging API `/health` endpoint returns 200 OK.

---

## 13  Definition of Done

- All 6 stories completed with evidence.
- Azure resources verified via CLI.
- Docker Compose verified locally.
- CI/CD pipeline tested end-to-end.
- No unresolved infrastructure blocker.
- Documentation updated (infrastructure notes, `.env.local.example`).

---

## 14  Demo / Evidence

- Azure resource listing.
- PostgreSQL schema verification.
- Docker Compose running screenshot or terminal output.
- GitHub Actions CI/CD run output (green).
- Staging `/health` curl response.
