# Architecture

A walkthrough of every stage in the ReliefStream pipeline, why each design choice was made, and where the extension points live.

## Design principles

1. **A wrong answer is worse than no answer.** Everything downstream of the extractor branches on `parseable: bool`. Requests that can't be confidently parsed go to a human, never into the actionable queue.
2. **Runs on a laptop offline.** The entire stack — LLM, DB, API, UI — runs on a single machine with no cloud dependency. During a real flood, cellular data is saturated and cloud API rate limits kick in exactly when you need them least.
3. **One file per concern, no build step.** SQLite is one file. `main.py` is FastAPI. `index.html` is the frontend. Anyone can `cp -r reliefstream/ backup/` and deploy elsewhere in seconds.
4. **Fingerprint everything.** WhatsApp forwards the same rescue request 40 times. A dashboard flooded with duplicates is worse than one that dedups aggressively.

---

## Stage 1 — Ingest

Three entry points, all landing in the same pipeline:

- **Paste-in web form** (dashboard `/frontend/index.html`) — for a volunteer operator monitoring social media manually
- **`POST /ingest`** — for a single message
- **`POST /ingest/bulk`** — for batch upload (paste a whole thread, or a text file dump)

Every request goes through the same extractor and dedup pipeline. There is no "trusted source" fast path.

### Extension points for Phase 2

- Twitter API webhook receiver
- WhatsApp Business API webhook
- Meta Graph API for Facebook / Instagram
- SMS gateway integration (Textlocal / MSG91)

These all just POST to `/ingest` with the appropriate `source` field. No changes to the extraction or storage layers needed.

---

## Stage 2 — Extractor (LLM)

Located in `backend/extractor.py`. Single function: `extract(raw_text) -> ExtractedFields`.

### Model choice

Default is **Ollama running `qwen2.5:7b` locally**. Chosen because:

- Solid tool-use / JSON-mode reliability at 7B scale
- Runs on ~6GB VRAM (or CPU with 8GB RAM, slower)
- Zero cost, zero rate limit, zero network dependency
- Handles English + transliterated Tamil / Hindi / Kannada well enough for this scope

The extractor uses the OpenAI SDK against an OpenAI-compatible endpoint. Swap models by editing `.env`:

```
LLM_BASE_URL=https://openrouter.ai/api/v1
LLM_API_KEY=sk-or-v1-...
LLM_MODEL=meta-llama/llama-3.3-70b-instruct:free
```

No code change required.

### The prompt

System prompt (see `extractor.py`) does four things:

1. **Names the safety rules first** — never invent location/contact/count; if not confident, set `parseable=false`
2. **Provides an exact JSON schema** — one field per line, types explicit
3. **Defines urgency levels** with concrete rules (immediate = stranded, rooftop, drowning; low = supplies needed at safe location)
4. **Insists on raw JSON output** — no markdown, no code fences (though we strip them anyway as a belt-and-braces)

Temperature is set to `0.2` — extraction should be deterministic, not creative.

### Post-validation

After the LLM returns JSON, `extractor.py` runs a hard validation pass:

- Schema check via Pydantic
- **Enforce `parseable=false`** if any of `{location, urgency, request_type}` is missing or unknown, or if the LLM's own `confidence` is below 0.4

This is defense-in-depth. Even if the LLM sets `parseable=true` inappropriately, our code refuses to trust it without the required fields.

---

## Stage 3 — Fingerprint + dedup

Located in `backend/storage.py`, function `_fingerprint(text, extracted)`.

### Two-tier fingerprinting

- **If extraction succeeded:** fingerprint = SHA256 of `location|request_type|urgency`. Two messages about "rooftop rescue at Ganapathy 4th street immediate" collapse to one card even if the wording differs.
- **If extraction failed:** fingerprint = SHA256 of normalized text (lowercase, punctuation stripped, whitespace collapsed). Prevents exact duplicates in the "read yourself" pile.

On duplicate: `duplicate_count` increments, the original record's `updated_at` refreshes. The UI shows a `×N` badge to indicate how many times a request was forwarded — high N is a signal that this request is real and urgent.

### Why not embed-based dedup?

Considered semantic dedup via embeddings but rejected for MVP because:

- Adds a second model dependency (embedding model)
- Adds a vector DB dependency
- False positives are dangerous — merging "grandma stuck on rooftop at X" with "grandma stuck on rooftop at Y" loses critical information

Sticking with exact-field-match dedup keeps the system predictable. Phase 3 can add embedding-based near-dup detection with careful thresholds.

---

## Stage 4 — Storage (SQLite)

Located in `backend/storage.py`. Single-file database at `reliefstream.db` (path configurable via `DATABASE_PATH` env var).

Schema is a single `requests` table with indexes on `fingerprint` (dedup), `status` (filtering), `created_at` (chronological listing).

### Why SQLite

- Zero setup — no service to install, no port to configure
- Backup by `cp reliefstream.db backup.db`
- Restore by `cp backup.db reliefstream.db && systemctl restart`
- Runs from a USB drive if needed
- WAL mode gives concurrent-read performance adequate for hundreds of volunteers

Scaling ceiling is roughly **10,000 requests/hour** on a laptop before we'd want to migrate to PostgreSQL. Real floods generate on the order of thousands of requests over 24 hours, not per hour, so this is comfortable headroom.

### Why not Redis / DynamoDB / Firestore

Every one of those requires a service, credentials, and network access. SQLite requires none of those and survives when the internet doesn't.

---

## Stage 5 — API (FastAPI)

Located in `backend/main.py`. Endpoints:

| Method + Path | Purpose |
|---|---|
| `POST /ingest` | Ingest one message |
| `POST /ingest/bulk` | Ingest many messages |
| `GET /requests` | List with optional `?status=` filter |
| `GET /requests/{id}` | Get one request |
| `POST /requests/{id}/claim` | Volunteer claims a request |
| `POST /requests/{id}/triage` | Human moves unparseable → actionable |
| `POST /requests/{id}/resolve` | Mark resolved with outcome |
| `GET /stats` | Aggregate counts |
| `GET /stream` | Server-Sent Events for live updates |

FastAPI auto-generates OpenAPI docs at `/docs`.

### Why SSE, not WebSockets

Volunteers only need to *receive* updates, not push them. SSE:

- Works over plain HTTP (no upgrade handshake, no proxy issues)
- Auto-reconnects natively in browsers
- Fewer moving parts than WebSockets
- Adequate for the fan-out pattern (1 backend → N dashboards)

The in-memory subscriber list (`_subscribers`) is fine for single-process deployment. For multi-worker deployments, swap to Redis pub-sub. Not needed for MVP.

---

## Stage 6 — Dashboard (frontend)

Located in `frontend/`. Three files: `index.html`, `style.css`, `app.js`. No build step, no framework, no dependencies except Leaflet (via CDN).

### Layout

Two-column split: filterable list on the left (with ingest form at top), Leaflet map on the right. Filter tabs across the top of the list.

### The "Read yourself" tab

This is the safety pattern made visible. It:

- Is always in the tab row, always shows a live count
- Uses a distinct amber color (not the cyan/green of parseable requests)
- Cards in this tab display "READ YOURSELF" prominently instead of urgency/type badges
- Requires a volunteer name + explicit triage action before entering the actionable queue

The tab was intentionally not hidden behind a "settings" menu or expandable section. If it's not visible, it's not doing its job.

### Real-time updates

Every state change (new request, claim, resolve) triggers an SSE event. The dashboard listens and refreshes. A 15-second polling fallback covers SSE reconnection gaps.

---

## What's not in the MVP

Explicit non-goals for scope discipline:

- **Geocoding.** Extractor returns `location` as free text. Lat/lon fields exist in the schema but the LLM is instructed to leave them null unless coordinates are explicitly in the message. Phase 3 will integrate Nominatim.
- **Authentication.** Anyone with the dashboard URL can claim/resolve. This is a coordination tool for volunteer networks, not a system-of-record. Real deployment would put this behind SSO/basic-auth.
- **Notification back to requesters.** When a volunteer claims a request, the original poster isn't notified. Phase 4 will add SMS/WhatsApp callback.
- **Multi-language extraction.** The prompt handles English + transliterated Indian languages. Native-script extraction (Tamil, Devanagari, etc.) will benefit from a purpose-fine-tuned model in Phase 5.
- **Analytics / post-event reports.** No dashboards for response time, coverage gaps, volunteer utilization. Phase 7.
