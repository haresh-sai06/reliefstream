<div align="center">

# ReliefStream

### Real-time centralization of flood-rescue requests from social media chaos

*Volunteers can't coordinate when rescue calls are scattered across Twitter, WhatsApp forwards, and Instagram DMs. ReliefStream funnels them into one prioritized dashboard.*

![Status](https://img.shields.io/badge/status-MVP-blue)
![License](https://img.shields.io/badge/license-MIT-green)
![Stack](https://img.shields.io/badge/stack-FastAPI%20·%20Ollama%20·%20Leaflet-cyan)
![SDG](https://img.shields.io/badge/UN%20SDG-3%20·%20Good%20Health%20%26%20Well--being-purple)

</div>

---

## The problem

When floods hit — Chennai 2015, Kerala 2018, Hyderabad 2020, Bengaluru 2022, every monsoon somewhere — the first hours are chaos. Rescue requests scatter across:

- Twitter threads with garbled locations
- WhatsApp forwards that lose context after 3 hops
- Instagram DMs with only a photo and a postcode
- Facebook posts with hundreds of comments burying the actual address

Local volunteers show up ready to help but spend more time **finding requests** than acting on them. Meanwhile the same request gets forwarded 40 times while an untouched request across town waits.

Existing government helplines exist but are structured (call, form, wait). The chaotic, informal channels are where real requests actually flow in the first hour.

## The solution

**ReliefStream is a single-screen dashboard that:**

1. **Ingests** raw social media text (paste-in or webhook)
2. **Extracts** structured fields via LLM: location, urgency, request type, people affected, contact number
3. **Counts repeated ingests** — matching source IDs, or matching full normalized messages from the same source, reuse one card. The count is not independent confirmation; different households are kept separate.
4. **Maps** all requests as pins on Leaflet with severity color-coding
5. **Assigns** — volunteers claim requests, mark them resolved, log outcomes
6. **Surfaces failures** — when the model can't parse a location, that request goes to a **"Read this yourself"** pile visible to a human operator, never silently dropped

The last one is the most important design decision: **a confident wrong answer during a flood is worse than no answer.** A misread pincode sends volunteers to the wrong neighborhood while a family waits on a rooftop. Every ambiguous parse is escalated to a human.

---

## What ReliefStream is not

To keep scope honest:

- **Not** an emergency dispatch service. It doesn't call 108 for you or promise SLA.
- **Not** a replacement for NDRF/SDRF. It's a coordination layer for informal volunteer networks.
- **Not** a general-purpose disaster tool. Scoped to flood rescue coordination in the first 24-72 hrs of an event.
- **Not** deployable without a human operator watching the "read this yourself" pile.

---

## Architecture

```
┌────────────────────────────────────────────────────────────────┐
│  INGEST                                                        │
│  paste-in web form  ·  webhook /ingest  ·  bulk file upload    │
└────────────────────────────┬───────────────────────────────────┘
                             ▼
┌────────────────────────────────────────────────────────────────┐
│  EXTRACTOR — Ollama (qwen2.5:7b) via OpenAI-compatible API     │
│  output: { location, urgency, type, people, contact,           │
│            confidence, parseable }                             │
└──────────────┬────────────────────────┬────────────────────────┘
    parseable=true            parseable=false / low confidence
               ▼                        ▼
┌──────────────────────────┐  ┌──────────────────────────────────┐
│  DEDUP + STORE (SQLite)  │  │  UNPARSEABLE PILE                │
│  fingerprint hash        │  │  "read this yourself" queue      │
└──────────────┬───────────┘  │  operator triages manually       │
               ▼              └──────────────────┬───────────────┘
┌──────────────────────────┐                     │
│  DASHBOARD               │◀────────────────────┘
│  · Map (Leaflet)         │   both feed the dashboard;
│  · List (filter/sort)    │   unparseable badge stays visible
│  · Claim / Resolve       │   until human resolves
│  · Live via SSE          │
└──────────────────────────┘
```

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the full walkthrough.

---

## Key design decisions

| Decision | Why |
|---|---|
| **Local Ollama over cloud LLM** | Zero cost, runs on a laptop in an offline field kit, no rate limits during a surge |
| **SQLite over PostgreSQL** | One file, no DB server to set up during a crisis, backup by `cp` |
| **Server-Sent Events over WebSockets** | Simpler; volunteers only receive updates, don't need to push |
| **Vanilla JS + Leaflet** | No build step, single HTML file, works on any browser without npm |
| **Explicit "unparseable" queue** | The safety pattern the mentor brief flags is non-negotiable — chose to build it in from day 1, not add it later |
| **Conservative identity dedup** | Source IDs or full message text identify repeats; location/urgency/type alone cannot identify a household |

---

## Tech stack

**Backend**
- Python 3.11 + FastAPI (async, auto-docs)
- Ollama + `qwen2.5:7b` (LLM extraction, local, ₹0)
- SQLite (persistence, one file)
- OpenAI-compatible SDK (swap Ollama for Gemini/Claude with one env change)

**Frontend**
- Vanilla HTML + JS (no build step)
- Leaflet.js (open-source maps)
- OpenStreetMap tiles (no API key)
- Server-Sent Events for live updates

**Ops**
- No external dependencies at runtime beyond an Ollama server
- Single-file deploy: `git clone && cd backend && pip install -r requirements.txt && uvicorn main:app`

---

## Quick start

Two commands after clone:

```bash
# 1. Backend
cd backend
pip install -r requirements.txt
cp .env.example .env    # defaults to local Ollama, no key required
uvicorn main:app --reload --port 8000

# 2. Frontend (any static server, or open index.html directly)
cd ../frontend
python -m http.server 8080
# open http://localhost:8080
```

Prerequisites: `ollama pull qwen2.5:7b` if not already local. Or swap `.env` to point at Gemini/Groq/OpenRouter.

Sample data to test with is in [`sample_data/`](sample_data/) — realistic-style rescue messages you can paste into the dashboard ingest form.

---

## Regression checks

From the repository root, create a virtual environment, then run:

```bash
python -m pip install -r requirements-dev.txt
python -m unittest discover -s tests -p 'test_*.py' -v
node --test tests/workflow.test.cjs
```

The tests use temporary SQLite files, synthetic messages and a stub extractor through actual HTTP handlers; no model, credentials or external service is contacted. Node's built-in test runner checks how the browser write helper handles conflicts and network errors. These checks do not verify a real model, real-browser rendering or emergency use.

Before upgrading an existing database, back it up. Startup adds an identity map and preserves all old rows. New repeats use a canonical record; previously discarded household details cannot be recovered. See [identity and workflow notes](docs/ARCHITECTURE.md#stage-3--fingerprint--dedup).

## Cost

| Deployment | Cost per parsed request |
|---|---|
| Local Ollama | ₹0 (electricity only) |
| Gemini 2.5 Flash free tier | ₹0 up to 1M tokens/day |
| Gemini 2.5 Flash paid | ~₹0.05 |
| Claude Haiku 4.5 | ~₹0.15 |

During a real flood surge (10,000+ messages/hour), local deployment is the only economically defensible option.

---

## Roadmap

- **Phase 1 (this MVP)** — paste-in ingest, LLM extraction, map + list dashboard, unparseable pile, manual claim/resolve
- **Phase 2** — webhook receivers for Twitter API, WhatsApp Business API, Meta Graph API
- **Phase 3** — geocoding integration (Nominatim / MapmyIndia) so "opposite Kovai Kutralam" resolves to lat/lon
- **Phase 4** — SMS/WhatsApp notifications back to requester when a volunteer claims their request
- **Phase 5** — multi-language: Tamil, Malayalam, Kannada, Telugu, Hindi extraction (currently English + transliterated Tamil)
- **Phase 6** — offline-first mode: PWA with local model, works when 4G is saturated
- **Phase 7** — post-event analytics: response times, coverage gaps, volunteer utilization

---

## Origin

Inspired by problem statement **#205** at *Tech for Good — Code for Communities 2026* (Dr. G. R. Damodaran College of Science, Coimbatore, Aug 8-9, 2026), attributed in the mentor brief to team "Black hole" (Daksh Chariwal, Huzefa Saroodwala, Mahipal Singh U, Tarun Kumar B). This is an **independent implementation** of that same problem statement — not affiliated with the original team.

The mentor brief flagged one non-negotiable safety condition:

> *"Build the pile of requests you could not parse. When the model cannot extract a location, or is unsure, that request must appear somewhere visible marked 'read this yourself'."*

ReliefStream implements exactly that. See [`docs/PROBLEM.md`](docs/PROBLEM.md) for the full source.

---

## License

MIT — see [LICENSE](LICENSE).

Attribution appreciated when deployed. If you use this for an actual flood response, please cite in your post-event report so the safety patterns propagate.

---

<div align="center">
<sub>Built as a reference implementation for Code for Communities · Tech for Good 2026</sub>
</div>
