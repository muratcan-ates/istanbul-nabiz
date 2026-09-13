# Deep Research Brief — İstanbul Nabız

> **Kullanım:** Bu dosyayı bir derin araştırma modeline (ChatGPT Deep Research, Gemini Deep Research,
> Perplexity, Claude) tek mesajda gönder. Öncesinde `docs/NABIZ.md` dosyasını yapıştır; oradaki kurallar ve
> doğrulanmış gerçekler bağlayıcıdır. Aynı brifi birden fazla modele gönderip raporları karşılaştır; ana
> sohbet (Integrator) bunları birleştirip yol haritasını çıkarır. Prompt İngilizce, çünkü kaynakların çoğu
> İngilizce ve araştırma modelleri bu dilde daha isabetli çalışıyor; raporun başında Türkçe özet isteniyor.

---

You are a senior research engineer preparing a **one-day, AI-assisted build sprint** for the project described
in the attached charter (`NABIZ.md`). Today is **2026-09-13**. Treat every fact in the charter as verified and
every claim you add as unverified until you cite a source with a URL and the date you read it.

Our motto is *"Legerdemain — every second counts."* The report's only purpose is to save hours tomorrow and
to fill real gaps in the product without breaking its rules (unofficial status, CC BY 4.0 attribution, no
personal data stored server-side, gateway rate limits, honest numbers, swappable LLM, Azure for Students limits).

## What we are optimising for

1. **Time-to-working-feature** in a single day, by one developer with AI pair-programmers, on a MacBook (M1,
   16 GB), Python 3.12, Azure for Students. Anything that needs approval workflows, paid tiers, GPU, or more
   than ~4 hours of integration is *not* day-1 buildable — say so.
2. **Product depth** in four candidate epics (E1–E4 below), positioned against İBB's own citizen app
   *İstanbul Senin* and the separate İSPARK / Mobiett / CepHava / Metro İstanbul apps.
3. **Trustworthiness**: every feature must be measurable by our eval harness; every number must carry provenance.

## Research questions

### A. Accelerators — what cuts build time on *this exact stack*
Stack: Python 3.12 · MCP SDK 2.x (`MCPServer`) · FastAPI · Azure Functions Flex · Azure Container Apps ·
Azure Data Explorer free cluster (KQL) · Delta Lake · Bicep + `azd` · GitHub Actions · optional Azure Maps Gen2 ·
LLM via any OpenAI-compatible endpoint (Azure OpenAI / Microsoft Foundry serverless / Foundry Local on the Mac).

For each item give: what it is, why it saves time *for us specifically*, the exact repo/template/doc URL, licence,
last-commit or last-updated date, and a **day-1 buildability score (0–3)** with the reason.

- A1. Reference implementations of **MCP servers over public transport / city open data** (GTFS, GBFS,
  parking, air quality) that we could borrow patterns from. Include how they handle rate limiting and caching.
- A2. **Microsoft Agent Framework 1.x** patterns for: an agent that consumes an MCP server, tool-call loops with a
  post-hoc verifier, OpenTelemetry tracing to Application Insights, and running with *no* hosted model
  (deterministic fallback). Cite the exact docs pages.
- A3. **Microsoft Foundry / Azure OpenAI on Azure for Students in September 2026**: current reality of model
  deployment quota, "sold by Azure" serverless models, and Foundry Local tool-calling on Apple Silicon. We know
  GitHub Models was retired on 2026-07-30 — do not propose it.
- A4. **Azure Data Explorer free cluster**: verified ways to ingest from a Function's managed identity, KQL
  functions for time-series profiles (e.g., typical occupancy by weekday × hour), and dashboard sharing.
- A5. **Container Apps + azd**: the shortest verified path to a live HTTPS URL for a Python MCP server
  (streamable HTTP) and a FastAPI app, with `minReplicas: 0`, remote build, and no local Docker.
- A6. **Testing and eval accelerators**: libraries or patterns for scenario-based evaluation of tool-using
  agents, numeric-faithfulness checks, and contract tests against recorded fixtures (we already have 330 tests;
  what would a senior reviewer add?).

### B. Similar systems — what exists, what worked, what failed
- B1. Everything public built on **İBB open data** (`data.ibb.gov.tr`, `api.ibb.gov.tr`): GitHub repos,
  hackathon entries (İBB Açık Veri hackathons, Teknofest, university projects), papers, blog posts. Include the
  Microsoft/Azure ones if any. For each: stack, what it does, last activity, and what it teaches us.
- B2. **İBB's own products** we must position against or integrate with: *İstanbul Senin* (feature list, which
  data it exposes, whether it has public APIs), Mobiett, İSPARK app, CepHava, Metro İstanbul app, İBB Kültür
  Sanat / event calendars, *İBB WhatsApp / chatbot* initiatives. What do they **not** do that we can?
- B3. **City agents and open-data copilots in other cities** (TfL, MTA, Helsinki HSL, Barcelona, Singapore LTA,
  Seoul, Madrid EMT): architectures, routing engines, notification designs, privacy approaches. Which ones
  publish accuracy numbers for arrival predictions, and what are they?
- B4. **Microsoft public-sector / smart-city reference architectures** (Azure, Fabric Real-Time Intelligence,
  Copilot Studio) relevant to a municipality. Which pieces are realistic on a student subscription?

### C. Gap-filling epics — design options, not just ideas
For each epic: at least two architecture options, a recommended one, the data it needs (and whether İBB actually
publishes it — **verify; do not assume**), the privacy design, how our eval harness would measure it, effort in
hours, day-1 buildability score, and the risk that kills it.

- **E1 Route advisor** — "Given current traffic, metro status, parking availability and the timetable, is it
  faster or more comfortable to drive, take the metro, or combine?" Compare: OpenTripPlanner 2 with İETT +
  Metro GTFS; Valhalla/OSRM for driving; Azure Maps Route API (note: Azure Maps *transit/mobility* routing was
  retired — confirm current status); Google Routes / Moovit APIs (cost, terms). Define "comfortable" as
  something measurable (transfers, walking metres, crowding proxies, reliability from our ETA log).
- **E2 Proactive, location-aware alerts** — the user's line has a disruption, the car park they usually use is
  filling up, an air-quality episode is near them. Design it **KVKK-compliant by construction**: location and
  preferences on device only, explicit opt-in, no server-side storage or logs of location, clear deletion.
  Compare delivery channels (Web Push, e-mail, Microsoft Teams, Telegram) on cost, consent and demo-ability.
- **E3 Event recommendations** — verify whether İBB publishes a machine-readable events feed (Kültür Sanat,
  *İstanbul Senin*, kulturportali, or others). If yes: schema, licence, freshness. If no: what is the honest
  alternative? Recommendation must work with an on-device profile and a cold start; no user history leaves the
  device.
- **E4 Field operations console for İBB staff** — the owner's idea: staff stay in touch and track live status.
  Be candid: this changes the customer from citizens to İBB internally and normally needs a partnership. Propose
  the most realistic MVP with only open data plus a Microsoft 365 developer tenant — e.g., a Teams/Copilot
  Studio surface or a Fabric Real-Time Dashboard fed by the same MCP server/collector — and say what it cannot
  do without İBB's internal systems.

### D. Engineering process for a one-day, multi-chat AI sprint
- D1. Best current practice (2025–2026) for **AI-assisted SDLC**: spec-driven briefs, parallel agent branches,
  handoff formats, integration cadence, eval-gated merges, "definition of done" for agent work. Cite sources
  (Microsoft, GitHub, Anthropic, ThoughtWorks, DORA, etc.).
- D2. **CI/CD on a public repo with no deploy secrets**: GitHub Actions patterns for lint/test/smoke; when and
  how to add OIDC federated credentials to Azure from a university tenant; `azd pipeline config` realities.
- D3. Guardrails that catch the failure modes we have already hit: tools advertising `(*args, **kwargs)`,
  Excel-truncated CSVs, coordinate corruption, terminus contamination in ETA ground truth, plates leaking.
  What automated checks would a senior team add?

### E. Constraints and risks to re-verify (short, sourced)
- Azure for Students: credit, allowed-regions policy, OpenAI quota, Functions Flex region availability, Maps
  Gen2 creation under the policy. Anything changed since August 2026?
- İBB Açık Veri Lisansı: confirm CC BY 4.0 basis and attribution wording; any clause relevant to caching or
  redistribution of live feeds.
- KVKK implications of E2/E3 for a student project with no legal entity; what a responsible minimum looks like.
- İETT/İBB terms on request rates beyond the documented 100/hour; any sign of an API-key programme.

## Output format (strict)

1. **Türkçe yönetici özeti** (≤ 12 satır): en yüksek getirili 5 hızlandırıcı, en riskli 3 varsayım, ve
   yarın sabah ilk 3 saatte ne yapılmalı.
2. **Roadmap table**: `Now (day 1) / Next (week) / Later`, each row = item · epic · effort (h) · day-1 score ·
   dependency · source URL.
3. **Per-section findings** (A–E) as tables where possible. Every row: claim · source URL · date read ·
   confidence (`verified` = you read it on the page · `likely` = strong secondary source · `unverified`).
4. **"Do not build" list** with reasons.
5. **Open questions** only a human with Azure/İBB access can answer.

Rules for the report: no invented repos, prices, APIs or endpoints; if a page is blocked or a fact cannot be
confirmed, say so; prefer official docs and primary sources; mark anything older than 12 months as such; answer in
English with the Turkish summary on top; keep Turkish proper nouns as they are.
