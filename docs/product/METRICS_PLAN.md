# SeaRise Europe — Product Metrics & Analytics Plan

## Document Metadata

| Field | Value |
|---|---|
| Owner | Artem Sem |
| Status | Draft |
| Version | 0.1 |
| Last updated | 2026-03-30 |

**Version History**

| Version | Date | Author | Summary of Changes |
|---|---|---|---|
| 0.1 | 2026-03-30 | Artem Sem | Initial draft |

> **Dependency:** Analytics instrumentation strategy is subject to OQ-10 (analytics enablement decision and privacy model). This document describes the full measurement framework. The subset that requires client-side analytics tracking is conditional on that decision.

---

## 1. Purpose

This document defines:
1. The KPI framework for SeaRise Europe MVP.
2. Which metrics require instrumentation versus manual evaluation.
3. The events to track if analytics are enabled.
4. The privacy constraints that apply to any analytics.
5. The review cadence for ongoing product health monitoring.

---

## 2. Metric Tiers

Metrics are organized into three tiers based on how quickly they need action if they move.

| Tier | Name | Review frequency | Action threshold |
|---|---|---|---|
| T1 | Health metrics | Real-time / daily | Any breach triggers immediate investigation |
| T2 | Core product metrics | Weekly | Trends over 2+ weeks trigger response |
| T3 | Quality & trust metrics | Per release / on demand | Evaluated at launch and after each methodology update |

---

## 3. Tier 1 — Health Metrics

These metrics indicate whether the system is operating correctly. A breach means something is broken or severely degraded.

| Metric | Target | Data Source | Notes |
|---|---|---|---|
| **Application availability** | ≥ 99.5% monthly (NFR-009) | Azure Container Apps health monitoring, uptime check | Excludes planned maintenance windows |
| **Backend error rate (5xx)** | < 1% of requests | Structured backend logs (NFR-012) | Alerts on sustained breach |
| **Unhandled client error rate** | < 2% of sessions (SM-6) | Frontend error tracking (conditional on OQ-10) | Defined as a session ending in an unhandled exception reaching the UI |
| **Assessment p95 latency** | ≤ 3.5 seconds (NFR-003) | Backend request logs with timestamps | Measured from request receipt to response |
| **Geocoding p95 latency** | ≤ 2.5 seconds (NFR-002) | Backend request logs | Excludes known upstream provider outages |
| **App shell load p95** | ≤ 4 seconds (NFR-001) | Browser performance timing (conditional on OQ-10) | Measured to interactive state; broadband desktop |

---

## 4. Tier 2 — Core Product Metrics

These metrics indicate whether the product is fulfilling its purpose for users.

### 4.1 Search-to-Result Completion Rate

**Definition:** The percentage of sessions where a user completes the full flow from search submission to receiving a defined result state (any state, including Out of Scope and Unsupported Geography — not only Modeled Exposure).

**Target:** ≥ 85% of sessions (SM-1)

**Calculation:** `Sessions with a result state returned / Sessions with at least one search submission`

**Data source:**
- Pre-analytics: QA regression test using a defined address set (≥20 addresses). Manual pass/fail.
- Post-analytics: Session funnel from search submission event to result-state-returned event.

**Exclusions:** Sessions abandoned before any search submission (bounce before interaction).

---

### 4.2 Result State Distribution

**Definition:** The breakdown of result states returned across all completed assessments.

| State | What a high rate indicates |
|---|---|
| Modeled Coastal Exposure Detected | High coastal query volume; core use case active |
| No Modeled Coastal Exposure Detected | Healthy — diverse location queries being evaluated |
| Data Unavailable | Potential data coverage gap; investigate if sustained |
| Out of Scope | Many inland queries; may indicate user expectation mismatch |
| Unsupported Geography | Many non-European queries; may indicate SEO or discovery issue |

**Target:** No specific rate target for MVP; monitor for anomalous concentration in Data Unavailable or Unsupported Geography states.

**Data source:** Backend assessment logs.

---

### 4.3 Scenario and Time Horizon Usage

**Definition:** Which scenario and time horizon are most selected by users.

**Target:** No specific target; used to inform defaults (OQ-03) and future roadmap decisions.

**Data source:** Backend assessment logs (scenario and horizon parameters per request).

---

### 4.4 Methodology Panel Open Rate

**Definition:** The percentage of sessions with a result where the user opens the methodology panel.

**Target:** No specific target for MVP; tracked to understand how many users engage with transparency features.

**Data source:** Frontend analytics event (conditional on OQ-10).

---

### 4.5 Control-Switch Latency After Initial Result

**Definition:** p95 time from scenario or horizon change event to updated result visible in the UI.

**Target:** ≤ 1.5 seconds p95 (NFR-004, SM-5)

**Data source:** Backend logs (time between scenario/horizon-change request receipt and response completion).

---

## 5. Tier 3 — Quality and Trust Metrics

These metrics are evaluated at release and after any methodology update, not continuously.

### 5.1 Search-to-Result Completion Rate (QA Baseline)

Evaluated by QA before each launch using the defined address test set.
- Target: ≥ 85% (SM-1).
- Test set: ≥ 20 representative in-scope European addresses covering coastal and near-coastal locations across multiple countries.
- Pass/fail recorded per address in the QA run sheet.

### 5.2 Result Comprehension Quality

Evaluated in moderated or unmoderated usability sessions.
- Target: ≥ 80% of participants correctly identify all four main result states (SM-3).
- Minimum participants: 5.
- Evaluation method: Comprehension check questions or think-aloud tasks using live application or high-fidelity prototype.
- Timing: Before MVP launch; repeat after major UX changes.

### 5.3 Copy Integrity

Evaluated by product owner and at least one independent reviewer before each release.
- Target: 0 approved QA findings where UI copy overstates certainty beyond methodology (SM-8).
- Review checklist: Every result state copy, disclaimer, and methodology panel text is reviewed against the CONTENT_GUIDELINES prohibited language list.
- Timing: Before MVP launch; before any release that changes result copy.

### 5.4 Attribution and Disclaimer Completeness

Evaluated by QA before each launch.
- Target: 100% of displayed results include visible source attribution and methodology version (SM-7).
- Test: AC-013 and AC-014 from the PRD acceptance criteria.
- Timing: Every release.

---

## 6. Analytics Event Plan

*Conditional on OQ-10 (analytics enablement decision).*

If analytics are enabled, the following events shall be tracked. No raw address strings are stored in any event. All events use non-identifying aggregate data.

### Event Taxonomy

| Event Name | Trigger | Properties | PII Risk |
|---|---|---|---|
| `search_submitted` | User submits a location query | `query_length` (character count, not text), `timestamp` | None — length only, not content |
| `geocoding_candidates_shown` | Geocoding returns ≥1 results | `candidate_count` (1–5), `timestamp` | None |
| `location_selected` | User selects a candidate | `result_index` (position 1–5), `country_code`, `timestamp` | Low — country code only |
| `marker_moved` | User moves marker on map | `country_code`, `timestamp` | Low |
| `assessment_completed` | Assessment returns a result | `result_state`, `scenario_id`, `horizon_year`, `methodology_version`, `country_code`, `duration_ms`, `timestamp` | Low — country code only |
| `scenario_changed` | User changes the active scenario | `from_scenario_id`, `to_scenario_id`, `timestamp` | None |
| `horizon_changed` | User changes the active time horizon | `from_year`, `to_year`, `timestamp` | None |
| `methodology_panel_opened` | User opens the methodology/details panel | `result_state_at_open`, `timestamp` | None |
| `error_shown` | An error state is displayed to the user | `error_type` (enum), `timestamp` | None |
| `reset_invoked` | User activates the reset action | `timestamp` | None |

### Properties excluded from all events

- Raw query text
- Full address strings
- Precise coordinates (only country-level aggregation)
- Any user-identifying information

### Session definition

A session begins at page load and ends after 30 minutes of inactivity. Session IDs are ephemeral and not linked to any user identity.

---

## 7. Privacy Constraints

These constraints apply to all analytics and logging behavior, regardless of which tool is used.

1. Raw address strings entered by users must not be stored in logs, analytics, or databases beyond the duration of the originating request (BR-016, NFR-007).
2. Precise coordinate data from location selections must not be stored in analytics events; country-code-level aggregation is the maximum granularity permitted without further privacy review.
3. If a third-party analytics provider is used, its data processing agreement must be reviewed against applicable privacy regulation (GDPR at minimum) before go-live.
4. A cookie or tracking consent banner must be displayed before any client-side event tracking fires, if the chosen analytics tool sets cookies or uses device fingerprinting.
5. Analytics should be disabled by default in non-production environments.

---

## 8. Dashboards and Review Cadence

### MVP Launch Dashboard (to be configured before go-live)

| Panel | Metric | Visualization |
|---|---|---|
| Availability | Uptime % (rolling 30 days) | Gauge |
| Errors | Backend 5xx rate (hourly) | Time series |
| Performance | Assessment p95 latency (daily) | Time series |
| Performance | Geocoding p95 latency (daily) | Time series |
| Usage | Assessments completed (daily) | Bar chart |
| Usage | Result state distribution (daily) | Stacked bar |
| Usage | Scenario and horizon usage (weekly) | Bar chart |
| Quality | Unhandled client error rate (weekly) | Gauge |

### Review Cadence

| Review | Frequency | Owner | Focus |
|---|---|---|---|
| Health check | Daily (automated alert if T1 breach) | Artem Sem | T1 metrics — system is up and responsive |
| Product health review | Weekly | Artem Sem | T2 metrics — usage patterns, state distribution |
| Quality review | Per release | Artem Sem + reviewer | T3 metrics — copy, attribution, comprehension |
| Usability review | Before launch + after major UX changes | Artem Sem | SM-2 and SM-3 (task completion, comprehension) |

---

## 9. Metrics Reference Map

| Success Metric (from PRD §14) | Tier | Primary Data Source | Evaluation Timing |
|---|---|---|---|
| SM-1 Search-to-result completion ≥ 85% | T3 (QA), T2 (ongoing) | QA test set / analytics funnel | Before launch; ongoing |
| SM-2 First-use task completion ≥ 90% / 2 min | T3 | Usability sessions | Before launch |
| SM-3 Result comprehension ≥ 80% | T3 | Usability sessions | Before launch |
| SM-4 Search-to-first-result p95 ≤ 5 sec | T1 | Backend + frontend timing | Continuous |
| SM-5 Control-switch latency p95 ≤ 1.5 sec | T1 | Backend logs | Continuous |
| SM-6 Unhandled error rate < 2% | T1 | Frontend error tracking | Continuous |
| SM-7 Attribution 100% visible | T3 | QA checklist | Per release |
| SM-8 Copy integrity 0 findings | T3 | Manual copy review | Per release |
| SM-9 Demo pass rate ≥ 3+3 locations | T3 | Demo script execution | Before launch |
| SM-10 Reviewer clarity / 3-min walkthrough | T3 | Portfolio review sessions | Ongoing |
