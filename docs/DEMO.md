# Demo script

A 3-minute walkthrough for showing ReliefStream to a mentor, judge, or teammate.

## Prerequisites

Two terminals:

**Terminal 1 (backend):**
```bash
cd backend
pip install -r requirements.txt
cp .env.example .env
uvicorn main:app --reload --port 8000
```

**Terminal 2 (frontend):**
```bash
cd frontend
python -m http.server 8080
```

Open http://localhost:8080 in a browser. Also make sure Ollama is running with `qwen2.5:7b` pulled (`ollama pull qwen2.5:7b`).

## Demo beats

### Beat 1 — The problem (30 sec)

Open the dashboard. Empty. Say:

> *"During floods, rescue requests scatter across Twitter, WhatsApp, and Instagram. Volunteers spend more time finding requests than acting on them. ReliefStream funnels them into one dashboard."*

### Beat 2 — Ingest one clear request (30 sec)

Paste into the ingest form:

```
Family of 4 stranded on rooftop near Ganapathy 4th street opposite Bharat petrol pump water rising fast need immediate rescue contact 98765-43210
```

Hit Submit. Point out:

- The extractor pulled `location`, `urgency: immediate`, `type: rescue`, `people_count: 4`, `contact: 98765-43210`
- The card appears in the "New" tab with a red left border (immediate urgency)

### Beat 3 — Ingest an ambiguous message (30 sec)

Paste:

```
Chennai floods 2015 was terrible we should learn from that
```

Hit Submit. Point out:

- The card lands in the "Read yourself" tab, not the actionable queue
- The banner is amber, marked READ YOURSELF
- A human operator must explicitly triage before it can be acted on

Then say:

> *"This is the safety pattern. A confident wrong answer is worse than no answer. If the model isn't sure, a human sees it."*

### Beat 4 — Bulk ingest (60 sec)

Open `sample_data/rescue_messages.txt`. Copy the whole file. Paste into the ingest form. Check the **Bulk** checkbox. Submit.

Point out (as the results stream in):

- 20+ requests process in ~30 seconds via local Ollama
- The map fills with color-coded pins (red = immediate, amber = medium, green = low)
- Roughly 5 messages land in the "Read yourself" pile (news commentary, generic questions)
- Duplicate messages get merged with `×N` badges

### Beat 5 — Workflow (30 sec)

Click a red pin on the map. Modal opens. Show:

- Original message on top
- Extracted fields below
- Type your name in the "Volunteer" box, click Claim
- Card status flips to "claimed"
- Reopen the claimed card, select an outcome (helped / already resolved / not actionable / wrong info), add a note, Resolve

### Beat 6 — Close (10 sec)

> *"Backend is 400 lines of Python. Frontend is one HTML file. Zero cloud dependency. Runs on a laptop offline. Source at github.com/haresh-sai06/reliefstream."*

Total: ~3 minutes.

## Talking points for Q&A

**Q: What if the LLM hallucinates a phone number?**
> A: The system prompt explicitly forbids it. Post-validation double-checks the schema. The `parseable=false` fallback catches misfires. In practice, `qwen2.5:7b` at temperature 0.2 with an explicit "never invent" instruction is highly reliable — but the "Read yourself" pile exists precisely for the tail of cases where it fails.

**Q: What about non-English messages?**
> A: The current prompt handles English + transliterated Tamil (which is common in Coimbatore). Native-script Tamil, Malayalam, and Hindi work reasonably well too. Phase 5 will add a purpose-fine-tuned multilingual model.

**Q: How does deduplication decide two messages are the same?**
> A: If both parse successfully, we hash `location + type + urgency`. If either fails to parse, we hash the normalized text. This is deliberately strict — false-positive merges lose critical information.

**Q: What's the failure mode?**
> A: The extractor being wrong AND confident (setting `parseable=true` on garbage). Post-validation catches most of this, but if the LLM confidently outputs a plausible-but-wrong location, we'd send a volunteer to the wrong place. Mitigations: low temperature (0.2), explicit "never invent" instruction, confidence threshold of 0.4, and human review of anything the system isn't sure about. Not a solved problem — but the surface area is minimized.

**Q: What about at scale?**
> A: SQLite handles ~10K requests/hour on a laptop. Real floods generate that many over ~24 hours, not per hour. Single-process FastAPI + Ollama on one machine covers realistic Indian city-scale events. Migration to PostgreSQL + Redis pub-sub + multi-worker deployment is straightforward when needed.
