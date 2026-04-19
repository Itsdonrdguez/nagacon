# NagaCon Product Roadmap

This is the working roadmap for NagaCon as it exists today, not a generic GovCon platform spec.

The guiding idea is simple:

- keep the current clean workspace shape
- improve the quality of the data feeding it
- automate the operational flow behind the scenes
- avoid adding new cards or noisy UI just because the backend can produce more data

## Product Definition

NagaCon is a GovCon operations platform that:

- ingests solicitations from multiple sources
- turns source documents into structured workspace data
- helps decide whether to pursue the opportunity
- supports vendor sourcing and quote collection
- organizes submission readiness
- preserves the operational record after submission

## Product Pillars

Everything we build should strengthen one of these three tracks.

### 1. Core Platform

Purpose:
- make the opportunity-to-workspace flow reliable
- keep the UI clean, fast, and operational
- preserve trustworthy source data and workspace state

What this includes:
- ingestion from SAM and DIBBS
- opportunity normalization
- workspace creation and loading
- document download and storage
- company-profile-driven ingest targeting
- org-aware settings and external integrations
- a stable, uncluttered workspace UI

### 2. Document + Vendor Intelligence

Purpose:
- turn downloaded documents into usable facts
- match solicitations to real vendor actions
- support quote-driven execution, not just research

What this includes:
- auto-processing documents after download
- structured extraction from solicitation PDFs
- compliance facts, required actions, and review items
- vendor research and awardee history
- vendor shortlist, outreach draft, and quote tracking
- submission package data grounded in the processed documents

### 3. Recommendation + Automation

Purpose:
- move from “data available” to “decision support”
- automate the repetitive operational work behind the scenes

What this includes:
- bid recommendation with reasons
- risk and readiness signals
- progress guidance
- document-triggered workflows
- vendor/outreach automation
- long-term: post-award execution support

## Current State

NagaCon already has a strong base.

Working now:
- SAM + DIBBS ingestion
- workspace creation and loading
- DIBBS due-date normalization and backfill behavior
- auto-parse on first workspace open
- auto document download processing
- document-grounded compliance and outreach flow
- vendor research with USAspending support
- quote tracking and planned vendor selection
- submission package and outcome tracking
- org-aware settings and early SaaS foundations

Current workspace shape we should preserve:
- `Overview`
- `Vendors`
- `Documents`
- `Submission Package`
- `Submission`
- `Advanced`

No roadmap item should casually add new first-class cards unless the product truly needs them.

## Canonical Workspace Responsibilities

The workspace should stay organized around these responsibilities:

### Overview
- what the contract is
- whether we are ready
- the AI briefing and next actions

### Vendors
- who can supply
- who won before
- who we contacted
- what they quoted

### Documents
- what files we have
- how they were processed
- what the solicitation requires

### Submission Package
- the final pre-submit review surface

### Submission
- saved submission state
- post-submit outcome tracking

## Roadmap by Track

## Track 1: Core Platform

### Phase 1A: Opportunity Spine

Goal:
- make opportunity records, workspaces, and source documents behave predictably

Build:
- keep normalization logic source-aware and date-safe
- keep raw payload separate from normalized fields
- ensure every opportunity can open directly into a workspace
- preserve clean source document ordering
- keep the opportunity list filters honest and understandable

Primary backend areas:
- `backend/app/services/opportunities/*`
- `backend/app/api/opportunities.py`
- `backend/app/api/workspace.py`
- `backend/app/services/pdf_service.py`
- `backend/app/api/files.py`

Primary frontend areas:
- `nagacon_ui/src/pages/Opportunities.jsx`
- `nagacon_ui/src/pages/Workspace.jsx`

Success criteria:
- opportunity page shows the right rows and dates
- workspace loads without manual rescue steps
- downloaded files appear reliably in the Documents card

### Phase 1B: Company-Driven Intake

Goal:
- let the company profile drive what the system looks for

Build:
- maintain company targeting for:
  - DIBBS FSCs
  - SAM NAICS
  - agencies
  - locations
  - keywords
- keep `Run Recommended Ingest`
- move toward scheduled ingest from saved profile settings

Primary backend areas:
- `backend/app/models/company_profile.py`
- `backend/app/services/company_profile_ingest.py`
- `backend/app/services/auto_ingest_scheduler.py`

Primary frontend areas:
- `nagacon_ui/src/pages/Company.jsx`

Success criteria:
- company profile becomes the intake control center
- recommended ingest uses saved profile targets, not ad hoc user memory

### Phase 1C: SaaS-Ready Foundations

Goal:
- keep the local-first app moving toward SaaS without destabilizing the product

Build:
- continue org scoping
- continue auth/current-user work
- keep settings provider-aware and org-aware
- avoid broad schema churn unless it clearly supports the product spine

Success criteria:
- the product remains single-user friendly locally
- the data model keeps moving toward true tenant safety

## Track 2: Document + Vendor Intelligence

### Phase 2A: Document Truth

Goal:
- make processed solicitation documents the main truth source for workspace facts

Build:
- keep the automatic document pipeline:
  - extract
  - classify
  - fields
  - requirements/actions
  - summary
- improve extraction for:
  - solicitation number
  - due/return-by
  - quantity and unit
  - delivery
  - packaging
  - shipping terms
  - buyer/POC
  - submission destination
- ensure the best document is chosen consistently

Primary backend areas:
- `backend/app/services/document_pipeline.py`
- `backend/app/services/agents/workspace_agents.py`
- `backend/app/services/workspace_service.py`

Success criteria:
- `Opportunity Summary`, `Compliance Brief`, `Outreach Draft`, and `Submission Package` all agree on the best document-grounded facts

### Phase 2B: Compliance as Operations

Goal:
- make compliance useful for action, not just observation

Build:
- treat the compliance brief as:
  - confirmed facts
  - required actions
  - missing / needs review
- avoid vague phrases like “language is present”
- keep the card sourced from processed document data
- keep the package and printable views aligned with the same compliance output

Success criteria:
- a user can look at `Compliance Brief` and know what to do next

### Phase 2C: Vendor Execution

Goal:
- turn vendor research into usable sourcing operations

Build:
- keep approved-source and USAspending evidence visible but clean
- improve vendor ranking using:
  - approved-source context
  - award history
  - quote completeness
  - lead time
  - price
- keep outreach drafts grounded in:
  - item details
  - quote asks
  - buyer / vendor context

Primary backend areas:
- `backend/app/services/research/usaspending_research_service.py`
- `backend/app/services/vendor_service.py`
- `backend/app/services/workspace_service.py`

Primary frontend areas:
- `nagacon_ui/src/pages/Workspace.jsx`

Success criteria:
- users can go from document -> vendor shortlist -> quote request -> quote comparison without leaving the workspace

## Track 3: Recommendation + Automation

### Phase 3A: Bid Recommendation Engine

Goal:
- explain whether to bid, not just label an opportunity

Build:
- recommendation states:
  - `Bid`
  - `Needs Review`
  - `Do Not Bid`
- reason list
- next actions
- confidence and supporting signals

Inputs should come from:
- opportunity fit
- document completeness
- vendor coverage
- quote coverage
- time pressure
- compliance review state

Success criteria:
- the recommendation can be defended from workspace facts

### Phase 3B: Background Operational Automation

Goal:
- remove repetitive user clicks without creating agent chaos

Build:
- automatic processing after document download
- automatic compliance/outreach refresh after processing
- automatic workspace refresh for stale document-derived artifacts
- later:
  - scheduled recommendation refresh
  - stale task warnings
  - quote follow-up suggestions

Design rule:
- automation should feed existing workspace sections, not create new visible complexity

### Phase 3C: Agent Roles

Goal:
- keep agent scope clear and operational

The existing agents should map like this:

- `opportunity_analyst`
  - explain what the opportunity is
  - summarize fit, risk, and next actions

- `compliance_document`
  - extract document facts
  - produce required actions
  - flag missing/review items

- `vendor_research`
  - identify likely suppliers and awardees
  - explain why they match

- `email_outreach`
  - draft vendor communication from document-grounded asks

- `proposal_workspace`
  - turn current workspace state into execution guidance

Success criteria:
- each agent has one job
- each agent feeds existing workflow surfaces
- no “AI for AI’s sake”

## Canonical Data Objects

These are the must-have data objects for the current roadmap.

### Opportunities
- normalized source record
- raw source payload
- summary fields
- status and due dates

### Opportunity Files
- downloaded source docs
- extracted text
- processed metadata
- document processing status

### Workspace Artifacts
- compliance brief
- email draft
- opportunity analysis
- vendor research
- submission package

### Vendor Leads / Quotes
- likely suppliers
- quote requests
- quote responses
- recommendation scoring

### Submission State
- planned vendor
- submitted vendor
- submitted price
- outcome tracking

## API Direction

We do not need a total route rewrite right now. We should keep consolidating around the domains we already use most:

- `opportunities`
- `workspace`
- `files`
- `vendors`
- `submissions`
- `settings`
- `integrations`

Near-term API priority:
- make document processing and workspace refresh behavior more reliable
- keep route outputs consistent with the cleaned workspace UI
- avoid adding large parallel route trees unless the product actually needs them

## Immediate Build Order

This is the practical sequence for the next build slices.

### Now
- keep improving document-grounded workspace fields
- tighten vendor research quality
- tighten submission package correctness
- reduce stale artifact drift

### Next
- add recommendation logic with reasons
- improve quote-based vendor recommendation
- improve POC and submission-channel extraction
- add better task/progress automation inside the existing workspace

### After That
- scheduled company-profile-driven ingest
- more robust background job handling
- stronger org/user auth and permissions
- post-award execution workflow

## What We Are Not Doing Right Now

To keep NagaCon coherent, we should explicitly avoid a few traps:

- not rebuilding the UI around ten new tabs
- not creating a generic chat layer and calling it product progress
- not over-modeling every future SaaS concept before the core workflow is stronger
- not introducing heavy orchestration frameworks before the current automation path is fully trusted

## Current Definition of Success

NagaCon succeeds if a user can:

1. ingest opportunities from multiple sources
2. open a workspace immediately
3. get the important facts from the documents automatically
4. understand whether the opportunity is worth pursuing
5. identify vendors and past awardees
6. request and compare quotes
7. prepare a clean submission package
8. track what happened after submission

That is the core product.

Everything else should strengthen that flow.
