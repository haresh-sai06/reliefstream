# Sample data

## `rescue_messages.txt`

30 realistic-style rescue messages for testing ReliefStream's extraction pipeline. Copy any subset, paste into the dashboard's ingest form with the **Bulk** checkbox on, one message per line.

**Composition:**
- 20 legit rescue requests spanning all urgency levels and request types
- 3 in transliterated Tamil (Coimbatore is a Tamil-speaking region)
- 2 in mixed Tamil+English
- 5 non-actionable messages (news commentary, generic questions, test messages) — these should land in the "Read yourself" pile if the LLM does its job

**Locations used** are real Coimbatore neighborhoods: Ganapathy, Peelamedu, RSPuram, Saibaba Colony, Kuniyamuthur, Vadavalli, Ondipudur, Sundakkamuthur, Puliyakulam, Singanallur, Selvapuram, Nanjundapuram, Kavundampalayam, Ramanathapuram, Vellalore, Race Course.

**No real phone numbers.** All contact numbers are placeholders in the format `9XXXXXXXXX` or masked with `XXXXX`. Do not attempt to call them.

## What "good" extraction looks like

For the message *"Family of 4 stranded on rooftop near Ganapathy 4th street opposite Bharat petrol pump water rising fast need immediate rescue contact 98765-43210"* the LLM should produce something like:

```json
{
  "location": "Ganapathy 4th street opposite Bharat petrol pump",
  "urgency": "immediate",
  "request_type": "rescue",
  "people_count": 4,
  "contact": "98765-43210",
  "confidence": 0.9,
  "parseable": true
}
```

## What "correctly refused" looks like

For *"Chennai floods 2015 was terrible we should learn from that"* — this is commentary, not a request. The LLM should return `parseable: false` with a note like *"General commentary, not an active rescue request"*.
