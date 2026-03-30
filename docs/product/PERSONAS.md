# SeaRise Europe — User Personas

## Document Metadata

| Field | Value |
|---|---|
| Owner | Artem Sem |
| Status | Draft — working assumptions; validate before implementation |
| Version | 0.1 |
| Last updated | 2026-03-30 |

**Version History**

| Version | Date | Author | Summary of Changes |
|---|---|---|---|
| 0.1 | 2026-03-30 | Artem Sem | Initial draft — personas derived from brief; primary research not yet conducted |

> **Note:** These personas are working assumptions based on product scope and problem context. They have not been validated through primary user research. Assumptions should be tested before significant design decisions are committed.

---

## Persona Map

| # | Name | Type | Primary Goal |
|---|---|---|---|
| P-01 | Marina | Primary — Climate-Aware Resident / Researcher | Understand coastal exposure for a specific European location she is evaluating |
| P-02 | Tobias | Secondary — Educator / Communicator | Illustrate scenario-based coastal risk to students and event audiences without relying on raw scientific tools |
| P-03 | Yuki | Secondary — Portfolio Reviewer / Technical Evaluator | Quickly assess the product creator's product thinking, architecture decisions, and data honesty |

---

## P-01 — Marina, Climate-Aware Resident and Property Researcher

### Profile

| Field | Detail |
|---|---|
| Age | 34 |
| Location | Berlin, Germany |
| Occupation | Urban planner (public sector) |
| Climate awareness | Moderate-to-high; follows climate news but is not a data scientist |
| Tech comfort | High; comfortable with web apps, Google Maps, and research tools |
| Device | Desktop at work; mobile for casual browsing |

### Background

Marina is exploring whether to buy a flat in a coastal Portuguese city. She has read EEA reports about rising sea levels in Southern Europe but finds the reports hard to translate into a concrete answer about her specific area of interest. She has tried looking at generic flood maps but found them either too alarmist or too vague. She wants to understand what the data actually says — and what it does not say — without needing a GIS background.

Marina's situation represents a growing population: climate-literate enough to want details, not specialist enough to navigate raw data tools.

### Goals

1. Enter a specific European address or neighborhood and receive a clear exposure assessment.
2. Understand which scenario and time horizon she is looking at so she can assess optimistic versus pessimistic outlooks.
3. Trust that the result is not overstating risk or hiding important limitations.
4. Be able to explain the result to a partner or colleague without misrepresenting it.

### Frustrations

- **Fragmented sources:** Has to cross-reference projection tools, elevation data, and narrative reports to get a partial picture.
- **False certainty:** Many flood visualizations look precise but offer no explanation of methodology or uncertainty.
- **Technical gatekeeping:** Tools like the NASA AR6 tool are valuable but require understanding of RCP/SSP scenarios before any result is interpretable.
- **Resolution mismatch:** National-level climate reports do not answer "what about this specific street."

### Key Questions Marina Wants Answered

1. Is this location at modeled coastal exposure risk under a realistic scenario in 2050?
2. What assumptions and data sources is that answer based on?
3. How confident should I be in this result?
4. What does this tool *not* cover that I should look into separately?

### Trigger Moments

- Evaluating a property for purchase or rental in a coastal city.
- Researching a specific city or neighborhood for a work project or policy brief.
- Following a news story about European coastal flooding and wanting to explore a referenced location.

### Mental Model

Marina thinks of this tool as a first-pass filter, not a definitive answer. She wants enough information to decide whether it is worth investigating further with specialists or dismissing as low-exposure. She is comfortable with "modeled" and "scenario-based" framing as long as it is explained clearly.

### Design Implications for P-01

- The empty state and landing copy must quickly communicate what the product does and what it cannot tell you.
- Scenario and time-horizon labels must be human-readable, not scientific codes.
- The methodology panel must be accessible on demand but must not interrupt the primary flow.
- The result must clearly distinguish between "no exposure modeled" and "data unavailable" — these mean different things to Marina and she will notice if they are conflated.
- Color and visual design must be informative without being alarmist.

---

## P-02 — Tobias, Educator and Science Communicator

### Profile

| Field | Detail |
|---|---|
| Age | 47 |
| Location | Amsterdam, Netherlands |
| Occupation | Geography teacher at a secondary school; occasional public speaker on climate topics |
| Climate awareness | High; closely follows IPCC and EEA publications |
| Tech comfort | Moderate; comfortable with web apps but does not work with GIS or data tools |
| Device | Laptop connected to a projector or screen share during presentations |

### Background

Tobias regularly teaches students about sea-level rise and uses it as a real-world application of geography and earth science. He needs tools he can show live in a classroom or seminar — tools that are visually compelling, honest about uncertainty, and quick to navigate during a presentation. He has used Google Earth and Climate Central's Surging Seas in the past but wants something more methodologically transparent that he can direct students to for independent exploration.

### Goals

1. Demonstrate scenario-based coastal exposure for a recognizable European city in a live class setting.
2. Show students the difference between optimistic and pessimistic scenarios visually.
3. Reference tool methodology when students ask "how do they know that?"
4. Recommend the tool to students for self-directed exploration.

### Frustrations

- **Opacity:** Tools that produce compelling visuals but hide or bury their methodology make it hard to teach students about uncertainty and assumptions.
- **Instability:** Public-facing tools sometimes break or change between sessions, undermining live demonstrations.
- **False drama:** Animations or visualizations that show flooding without communicating probability or scenario context are hard to contextualize for students.
- **Language barriers:** Many authoritative European tools default to technical English or specific country languages, limiting use in multilingual classrooms.

### Key Questions Tobias Wants Answered

1. What projection data source is this based on?
2. What does "Scenario X" mean in plain language?
3. Can I trust this tool to still work the same way next month when I use it in class again?
4. What should I tell students this tool *cannot* tell them?

### Trigger Moments

- Preparing a lesson or presentation on sea-level rise or coastal climate change.
- Looking for a demonstration tool ahead of a public lecture or panel.
- Directing students to resources for a research assignment.

### Mental Model

Tobias values transparency above visual richness. He needs to be able to explain the tool's approach to a skeptical 16-year-old. If the methodology is hidden or the result is presented without clear caveats, he cannot use the tool with integrity. He will spend time reading the methodology panel before relying on the product.

### Design Implications for P-02

- The methodology panel must be substantive enough to cite in a classroom context — it is a first-class feature for Tobias, not a fallback.
- Scenario labels must include a short plain-language description, not just a code or number.
- The product must behave consistently across sessions; breaking changes to methodology should be versioned and communicated.
- The attribution and source section must be specific enough to satisfy academic citation standards.
- Desktop-and-projector layout must be clean and readable at presentation size.

---

## P-03 — Yuki, Portfolio Reviewer and Technical Evaluator

### Profile

| Field | Detail |
|---|---|
| Age | 38 |
| Location | London, United Kingdom |
| Occupation | Engineering manager at a software consultancy; occasionally interviews senior engineers and product managers |
| Climate awareness | Low-to-moderate |
| Tech comfort | Very high; evaluates architecture, code quality, and product decisions routinely |
| Device | Desktop or laptop; may also review GitHub repository directly |

### Background

Yuki is reviewing the SeaRise Europe portfolio project as part of evaluating a candidate. She has 15 minutes across a GitHub review and a brief live demo. She is not a climate domain expert but is highly experienced at distinguishing polished, well-considered work from impressive-looking demos that break under scrutiny. She looks for evidence of end-to-end thinking: does the product reflect genuine product design decisions, or is it just an engineering showcase?

### Goals

1. Understand the product's scope and intent within the first two minutes.
2. Identify where thoughtful product decisions were made (scope restrictions, scientific caution, data sourcing).
3. See evidence of clean architecture, maintainable code, and real data — not mock data.
4. Assess whether the creator can articulate limitations and trade-offs, not just features.

### Frustrations

- **Surface-only demos:** A tool that looks great but has no real data, hardcoded states, or hidden error handling.
- **Missing rationale:** No explanation of why certain design or architecture decisions were made.
- **Scope inflation:** A portfolio project that tries to do everything and does nothing well.
- **Unexplained limitations:** A product that has obvious limitations but never acknowledges them, suggesting the creator does not understand what they built.

### Key Questions Yuki Wants Answered

1. Does this product solve a real problem with appropriate constraints?
2. Is the data real and properly attributed?
3. Were the limitations thought through, or were they just left out?
4. How would this product behave in an edge case or failure scenario?

### Trigger Moments

- Reviewing a candidate's portfolio ahead of or during an interview.
- Browsing a GitHub repository to evaluate code quality and project structure.
- Being shown a live demo during a conversation.

### Mental Model

Yuki is not using this tool to assess coastal risk. She is using it to assess the creator. She is looking for the same signals in a portfolio product as in a production product: clear scope, honest communication, graceful failure handling, and evidence that the creator knows what they do not know. A well-documented limitation impresses her more than a feature that hides complexity.

### Design Implications for P-03

- The application must handle all defined edge cases (inland location, data unavailable, geocoding failure) cleanly — these are exactly what evaluators test.
- The methodology panel and data attribution must be substantive, not placeholder text.
- The demo script (see ROADMAP.md) must cover at least three coastal and three inland locations to demonstrate resilience.
- Empty and error states must be polished, not left as raw error messages.
- The UI must be consistent and professional at desktop resolution.

---

## Persona Comparison Summary

| Dimension | Marina (P-01) | Tobias (P-02) | Yuki (P-03) |
|---|---|---|---|
| **Primary motivation** | Personal decision support | Classroom demonstration | Professional evaluation |
| **Depth of methodology interest** | On demand | Deep — reads it proactively | Deep — uses it to judge quality |
| **Tolerance for uncertainty** | Moderate — wants honest framing | High — teaches uncertainty | High — expects it to be acknowledged |
| **Session length** | 5–15 minutes | 3–5 minutes live + prep | 5–10 minutes |
| **Key failure that loses them** | Misleading copy or unexplained state | Hidden methodology or instability | Unhandled error or hardcoded data |
| **What delights them** | A clear, honest result for their address | Transparency + classroom-ready layout | Edge cases handled gracefully |

---

## Validation Plan

Before committing design decisions to these personas, the following research activities are recommended:

| Activity | Goal | Suggested Format | Priority |
|---|---|---|---|
| 5 user interviews with coastal-area residents or property researchers | Validate P-01 goals, triggers, and frustrations | 45-minute semi-structured interview | High |
| 3 interviews with educators or science communicators | Validate P-02 methodology expectations and classroom use context | 30-minute semi-structured interview | Medium |
| Informal feedback from 2–3 technical peers during portfolio review | Validate P-03 evaluation criteria | Structured demo session with debrief | Medium |
| Usability test of MVP prototype | Test whether all three personas can complete core flows | Moderated task-based test, 5 participants | High |
