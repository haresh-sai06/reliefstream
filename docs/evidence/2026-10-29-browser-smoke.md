# Browser smoke validation — 29 October 2026

Tested application commit: `8acce235ea531d13473d4a525de9575d367be521`.

Nine manual scenarios passed in an actual browser against the real FastAPI backend, a new isolated SQLite database and the local `qwen2.5:7b` model. Four messages reached the model. This was a small synthetic English laboratory run, not an operator trial or field exercise. The scenarios are separate from the 33 automated regression checks.

The frontend was served on loopback port 18741 and the backend on 18742. Only the served API-origin constant was replaced to use that isolated backend; the repository's application bytes were unchanged. The existing service on port 8000 and all existing databases were left untouched. The owned lab servers were stopped after testing.

| Scenario | Observed result |
|---|---|
| Single intake | Synthetic rooftop request produced a saved card with the source location, four people and immediate rescue classification. Text cleared after acknowledgement. |
| Invalid single | `xx` received HTTP 422. Text remained and Submit became available again. No row added. |
| Invalid batch | One valid line plus `xx` received HTTP 422. Both lines remained; neither was stored. |
| Short-message batch | `SOS` plus a synthetic food request produced two rows: one unparseable and one parseable. Neither line was silently dropped. |
| Editing while saving | While the real model processed an evacuation message, a new draft was typed. The earlier message was saved; the new draft remained with the explicit next-submission notice and was absent from the database. |
| Human triage | The `SOS` review modal showed the original text and ambiguity. An explicit synthetic volunteer action moved it to triaged without changing its model parseability flag. |
| Claim | Claiming the synthetic rooftop case updated both the browser card/counter and persisted volunteer assignment. |
| Resolve | The synthetic case was resolved as `not_actionable`, with a note stating that it was a lab case and no real rescue occurred. Browser and persisted state agreed. |
| Backend outage | Stopping the owned backend produced an unconfirmed-action error. The new draft remained and Submit was enabled. No fifth row appeared. |

Final persistence check: four synthetic rows, comprising two new, one triaged and one resolved case. Three model outputs were parseable; `SOS` was held for human review. These figures describe this sample only and are not accuracy or adoption metrics.

The sample did not cover multilingual or adversarial messages, concurrent operators, load, authentication, deployment or real flood coordination. Model confidence was not calibrated. Response loss can still leave an ambiguous committed result: inspect the queue before retrying. TRL 4 remains the engineering self-assessment.
