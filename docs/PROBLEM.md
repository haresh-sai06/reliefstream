# Source Problem Statement

This project is a reference implementation of **Problem Statement #205** from the *Tech for Good — Code for Communities 2026* hackathon, held at **Dr. G. R. Damodaran College of Science, Coimbatore, on 8-9 August 2026**.

## The original brief

> **Team #205 — "Black hole"** (Good Health & Well-being track)
>
> Local volunteers cannot coordinate effectively during sudden floods because rescue requests scatter across different social media platforms in chaotic, unformatted text formats.
>
> **Building:** We are building a simple, real-time crowdsourcing dashboard to centralize emergency requests during floods.
>
> **Team:** Daksh Chariwal, Huzefa Saroodwala, Mahipal Singh U, Tarun Kumar B

## Mentor condition (non-negotiable)

The event's mentor brief flagged one safety condition for this team:

> *"Build the pile of requests you could not parse. When the model cannot extract a location, or is unsure, that request must appear somewhere visible marked 'read this yourself'."*

## Why this matters

The mentor brief itself frames why this pattern is critical:

> *"Ask what the tool does when it is not sure. A confident wrong answer is worse than no answer in almost every project here — a misread dosage, a missed rescue request, a lesion called harmless. The teams that have an 'I do not know' path are the ones that thought hardest."*

For flood rescue specifically: a misread pincode sends volunteers to the wrong neighborhood while a family waits on a rooftop. The cost of a wrong answer is directly measurable in human lives.

## How ReliefStream implements the condition

The safety pattern is enforced in **two layers**:

1. **In the extractor** (`backend/extractor.py`) — every extraction returns `parseable: bool`. This is set to `false` if:
   - The LLM cannot determine location, or
   - The LLM cannot determine urgency, or
   - The LLM cannot determine request type, or
   - The LLM's own confidence is below 0.4

2. **In the storage layer** (`backend/storage.py`) — requests with `parseable=false` are stored with `status='unparseable'`. They appear in the dashboard's dedicated "Read yourself" tab (styled amber, distinct from actionable requests) and cannot be silently dropped.

3. **In the UI** (`frontend/app.js`) — the "Read yourself" tab is always visible in the top bar with a live count. Human operators must explicitly triage each unparseable request before it enters the actionable queue.

## Relationship to the original team

This is an **independent implementation** of the same problem statement, built as a reference / study case. It is not affiliated with Team #205 "Black hole" or with Dr. G. R. Damodaran College of Science.

If the original team is reading this: your problem statement is genuinely important and your team's implementation almost certainly makes different (and often better) architectural choices. This exists as a companion, not a competitor.

## Full source

The original mentor briefing PDF ("Code-For-communities-PS.pdf") lists all 129 team problem statements across four UN SDG tracks:

- **Good Health & Well-being** (49 teams)
- **Strong Institutions** (39 teams)
- **Sustainable Cities & Climate Action** (18 teams)
- **Zero Hunger & Economic Growth** (23 teams)
