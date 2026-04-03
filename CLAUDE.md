# CLAUDE.md — SeaRise Europe

## Project Identity

SeaRise Europe is a public open-source, portfolio-grade web application that lets users enter a European location and view scenario-based coastal sea-level exposure on an interactive map. The product prioritizes scientific honesty, data transparency, and engineering quality over feature breadth.

- **Owner:** Artem Sem
- **License:** MIT (public repo — treat every commit as public)
- **Audience:** Climate-aware residents, researchers, educators, portfolio reviewers

---

## Security — Absolute Rules

This is a **public open-source repository**. Every file committed is visible to the world.

### Never commit secrets

- API keys, connection strings, passwords, tokens, certificates, private keys — **none of these may appear in any tracked file, ever**.
- The only place for secrets is `.env.local` (gitignored). The checked-in `.env.local.example` documents variable names with empty values only.
- Before staging files, verify `.gitignore` covers all secret-bearing patterns. Current protected patterns:
  ```
  .env / .env.* / .env.local / .env.*.local
  ```
  Exception: `.env.example` and `.env.local.example` are explicitly unignored.
- If you create a new file that holds secrets (config files, credential stores, key files), **add it to `.gitignore` first**, then create it.
- If you discover a secret in a tracked file, remove it immediately, rotate the credential, and force-push a cleaned history if the secret was already pushed.

### Sensitive patterns to watch for

| Pattern | Example | Rule |
|---------|---------|------|
| API keys | `GEOCODING_API_KEY=sk-abc...` | `.env.local` only |
| Connection strings | `Host=...;Password=...` | `.env.local` or Docker Compose env (no real passwords) |
| Azure storage keys | `AccountKey=...` | `.env.local` only; Docker Compose uses Azurite well-known dev key |
| MapTiler keys | `?key=...` in style URLs | `.env.local` only via `BASEMAP_STYLE_URL` |
| JWT / auth tokens | `Bearer eyJ...` | Never committed; not used in MVP |
| Private SSH keys | `id_rsa`, `*.pem` | Never committed |

### Docker Compose local credentials

The `docker-compose.yml` uses hardcoded **development-only** credentials (`searise` / `dev`) for local PostgreSQL and the well-known Azurite development key. These are not secrets — they run only in local Docker and are documented in Microsoft's Azurite docs. **Never reuse these values for any cloud or staging environment.**

---

## Repository Structure

```
SeaRise Europe/
├── CLAUDE.md                    ← you are here
├── docker-compose.yml           ← local dev: 5 services
├── .env.local.example           ← env var documentation (no secrets)
├── .github/workflows/ci.yml    ← CI: lint, type-check, test, Docker build
├── infra/db/init.sql            ← PostgreSQL schema + PostGIS + seed data
├── src/
│   ├── frontend/                ← Next.js 14+ (TypeScript, App Router)
│   │   ├── Dockerfile
│   │   ├── src/app/             ← pages, API routes, components
│   │   └── ...
│   └── api/                     ← ASP.NET Core .NET 8 (Minimal API)
│       ├── Dockerfile
│       ├── Program.cs
│       └── ...
├── docs/
│   ├── product/                 ← PRD, Vision, Personas, Content Guidelines, Mocks
│   ├── architecture/            ← 19 architecture docs, ADRs, diagrams
│   └── delivery/                ← ROADMAP.md, 8 epic files, artifacts/
└── data/geometry/               ← coastal analysis zone specification
```

**All source code lives under `src/`.** Never place application code at the repo root.

---

## Tech Stack

| Layer | Technology | Key Details |
|-------|-----------|-------------|
| Frontend | Next.js 14+, TypeScript, App Router | Zustand (state), TanStack Query (server state), MapLibre GL JS (map) |
| Backend API | ASP.NET Core .NET 8, Minimal API | Npgsql (PostgreSQL), structured JSON logging |
| Tile Server | TiTiler (Python/FastAPI) | Off-the-shelf; reads COGs via GDAL |
| Database | PostgreSQL 16 + PostGIS 3.4 | 5 tables: `scenarios`, `horizons`, `methodology_versions`, `layers`, `geography_boundaries` |
| Local Blob | Azurite | Azure Blob Storage emulator for local dev |
| Cloud (Epic 08) | Azure Container Apps, Blob Storage, Key Vault | Not provisioned yet — all dev is local-first |
| CI | GitHub Actions | Triggers on PR to `master` |

---

## Local Development

```bash
cp .env.local.example .env.local    # first time only — fill in API keys
docker compose up --build
```

| Service | URL | Health endpoint |
|---------|-----|-----------------|
| Frontend | http://localhost:3000 | `GET /api/health` |
| API | http://localhost:8080 | `GET /health` |
| TiTiler | http://localhost:8000 | `GET /healthz` |
| PostgreSQL | localhost:5432 | `pg_isready` (Docker healthcheck) |
| Azurite | localhost:10000 | port check (Docker healthcheck) |

- PostgreSQL auto-seeds schema and data from `infra/db/init.sql` on first start.
- To reset the database: `docker compose down -v && docker compose up --build`
- Frontend and API rebuild on `docker compose up --build`. TiTiler and Azurite are pre-built images.

---

## Architecture Decisions

All key decisions are recorded as ADRs in `docs/architecture/11-architecture-decisions.md`. When making implementation choices, check existing ADRs first. Key decisions:

| ADR | Decision | Impact |
|-----|----------|--------|
| ADR-001 | Next.js App Router | SSR shell, dynamic import for MapLibre |
| ADR-002 | Zustand for state | `useAppStore` + `useMapStore` |
| ADR-003 | TanStack Query v5 | Server-state caching with specific staleTime per query |
| ADR-004 | ASP.NET Core Minimal API | No MVC controllers; clean layered architecture |
| ADR-015 | Binary exposure methodology | 0/1 classification, no runtime threshold |
| ADR-016 | 3 scenarios: ssp1-26, ssp2-45, ssp5-85 | Covers optimistic/moderate/pessimistic |
| ADR-017 | Default: ssp2-45 + 2050 | Most commonly used IPCC combination |
| ADR-018 | Copernicus Coastal Zones 2018 | ~10 km inland extent |
| ADR-019 | Azure Maps Search (geocoding) | Enterprise reliability, GDPR-friendly |
| ADR-020 | MapTiler Dataviz Light (basemap) | Minimal visual competition with data |

---

## Delivery Context

Progress is tracked in `docs/delivery/ROADMAP.md`. Epics are sequential — each wave depends on the previous.

| Wave | Epic | Status |
|------|------|--------|
| 1 | Decision Closure | Done |
| 2 | Local Dev Environment | Done |
| 3 | Geospatial Pipeline | Done |
| 4 | Backend API Core | Done |
| 5 | Frontend Search | Planned |
| 6 | Assessment UX | Planned |
| 7 | Transparency & A11y | Planned |
| 8 | Azure Release | Planned |

When implementing a story, always check its epic file (`docs/delivery/0X-*.md`) for acceptance criteria, architecture traceability, and testing requirements.

---

## Coding Standards

### General

- Follow existing patterns in the codebase. Consistency over personal preference.
- No dead code, no commented-out code, no TODO comments without a linked story ID.
- Prefer explicit over clever. This is a portfolio project — readability matters.
- No premature abstractions. Three similar lines are better than an unnecessary helper.
- Keep functions small and focused. One function, one responsibility.

### Frontend (TypeScript / Next.js)

- Strict TypeScript (`"strict": true`). No `any` types without justification.
- ESLint with `next/core-web-vitals` config. All code must pass `npm run lint`.
- Use App Router conventions: `page.tsx` for routes, `route.ts` for API handlers, `layout.tsx` for layouts.
- Client components only where browser APIs are needed (map, search input, interactive panels). Server components by default.
- MapLibre GL JS must be dynamically imported with `{ ssr: false }` — it requires WebGL.
- No secret keys in `NEXT_PUBLIC_*` environment variables (NFR-006).

### Backend (C# / ASP.NET Core)

- .NET 8, Minimal API style. No MVC controllers.
- `dotnet format` must pass with no changes.
- Layered architecture: HTTP endpoints -> Application services -> Domain logic -> Infrastructure adapters.
- All PostGIS queries via parameterized Npgsql — never string-interpolate SQL.
- Structured JSON logging to stdout. No raw addresses in logs (NFR-007).
- Every response includes a `requestId` correlation ID.

### Database

- Schema is the source of truth in `infra/db/init.sql`.
- Schema changes must update `init.sql` and the corresponding architecture doc (`docs/architecture/05-data-architecture.md`).
- Seed data values come from `docs/delivery/artifacts/seed-data-spec.sql` — keep them in sync.

### Python (Geospatial Pipeline — Epic 03)

- Python 3.9+. Use `ruff` for linting, `mypy` for type checking.
- GDAL, rasterio, rio_cogeo for geospatial processing.
- Pipeline code lives under `src/pipeline/` (when created).

---

## Testing Requirements

| Layer | Tool | Scope |
|-------|------|-------|
| Frontend | Vitest or Jest | Unit tests for components and utilities |
| Frontend | Playwright | E2E smoke tests, accessibility checks |
| Backend | xUnit + Testcontainers | Unit tests, integration tests against real PostgreSQL |
| Pipeline | pytest | Pipeline step validation |
| All | CI (`ci.yml`) | Lint + type-check + test + Docker build on every PR |

- Tests must pass before merging. CI is the gate.
- No mocks for database tests — use Testcontainers with real PostgreSQL + PostGIS.
- Playwright tests run against the full Docker Compose stack locally.

---

## Git Workflow

- **Main branch:** `master`
- **Branch naming:** `{epic-number}-{short-description}` (e.g., `03-geospatial-pipeline`)
- **PR target:** always `master`
- **CI triggers:** on pull request to `master`
- **Commits:** concise messages focused on "why", not "what". Reference story IDs when applicable (e.g., `S03-01`).
- **Never force-push to `master`.**
- **Never commit secrets.** If you accidentally do, treat it as a security incident.

---

## Documentation Rules

- Architecture docs are in `docs/architecture/`. They describe *design*, not implementation details.
- Delivery docs are in `docs/delivery/`. Update `ROADMAP.md` when completing stories or epics.
- Epic files track story status. Update the epic status field when all stories are done.
- PRD (`docs/product/PRD.md`) is the source of truth for product requirements. Reference FR-xxx, BR-xxx, NFR-xxx IDs.
- Do not create new markdown files unless a new architectural concern or epic emerges. Prefer updating existing docs.

---

## Key Domain Concepts

| Concept | Meaning |
|---------|---------|
| Scenario | IPCC SSP emission pathway (ssp1-26, ssp2-45, ssp5-85) |
| Horizon | Future year for projection (2030, 2050, 2100) |
| Methodology version | Versioned processing recipe (v1.0 = binary exposure) |
| Layer | One COG file = one scenario x horizon x methodology version |
| COG | Cloud-Optimized GeoTIFF — raster data format for efficient tile serving |
| Coastal analysis zone | Copernicus-derived ~10 km inland buffer defining assessment eligibility |
| Result states | 5 possible outcomes: ModeledExposureDetected, NoModeledExposureDetected, DataUnavailable, OutOfScope, UnsupportedGeography |

---

## Non-Functional Requirements (Key)

| ID | Requirement | Target |
|----|-------------|--------|
| NFR-001 | Shell load time | <= 4s on 4G |
| NFR-003 | Assessment latency | p95 <= 3.5s |
| NFR-006 | No API keys in frontend env | Geocoding key stays in API only |
| NFR-007 | No raw addresses in logs | Privacy-preserving logging |
| NFR-011 | Health endpoints | All services expose health checks |
| NFR-019 | Stateless containers | No shared in-memory state |
| NFR-020 | COG format for rasters | Required for TiTiler |
| NFR-023 | No Kubernetes | Container Apps or Docker Compose only |

---

## Checklist Before Every Commit

1. `git diff --staged` — no secrets, no `.env` files, no credentials in any file.
2. `.gitignore` covers any new secret-bearing file patterns.
3. Frontend: `npm run lint && npm run type-check` pass.
4. API: `dotnet format --verify-no-changes && dotnet build` pass.
5. Docker: `docker compose up --build` starts without errors (when infra changes are made).
6. Schema changes reflected in both `init.sql` and `docs/architecture/05-data-architecture.md`.
7. Story completion reflected in the epic file and `docs/delivery/ROADMAP.md`.
