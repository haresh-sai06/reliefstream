# Technology readiness self-assessment

Assessment date: 24 October 2026. This is an engineering self-assessment from tests run on this repository. It is not an independent certification, a flood deployment, or permission to use the system in a real rescue.

## Result

**TRL 4.** Integrated laboratory validation.

The workflow (identity, dedup, claim, triage, resolve) and the extraction guardrails were exercised on a developer machine. A local `qwen2.5:7b` model was scored on the checked-in sample corpus. That is component and workflow validation in a laboratory. It is not validation in a volunteer operations room, and it is not operational use.

TRL 5 and above are not claimed. A tested local server is not a public deployment, and this run did not include a browser session or a field exercise.

## Evidence

| Check | Result |
|---|---|
| Python regressions, 24 October 2026 | 21 passed, 0 failed. Includes the earlier identity and workflow tests plus grounding tests. No network. |
| Node write-helper tests and `node --check frontend/app.js` | 4 passed. |
| Local model corpus, `qwen2.5:7b` | 29 sample messages. 12 non-requests, 0 marked parseable. 17 other messages, 14 parseable with a grounded location. The 3 held messages are a missing-person report, an animal-welfare note, and a cremation request. Full rows: [corpus eval](evidence/2026-10-24-corpus-eval.json). |

The model is still instructed not to invent a place or a phone number. `ground_to_source` now drops a contact, coordinate, or location that is not in the message. Latin-script text with no request cue is forced into the unparseable pile. Tamil and Hindi text is not blocked by that English cue list.

## Why this is not higher

| Level | Requirement for this system | Status |
|---|---|---|
| TRL 4 | Integrated components validated in a laboratory | Met by the tests and the local model run above |
| TRL 5 | Validated in a relevant environment | Not met. No operator workstation trial and no deployed intake desk |
| TRL 6 | Prototype demonstrated in a relevant environment | Not met |
| TRL 7–9 | Operational demonstration, qualification, or proven rescue use | Not met. Do not use this as an emergency service |

## Remaining work for TRL 5

26 October follow-up: 21 Python and 11 Node tests pass locally, including seven tests that execute the actual ingest listener with synthetic DOM/fetch fixtures. Four failure scenarios were reproduced before the ingest fix. Failed or incomplete acknowledgements now retain the pasted text, and short nonempty bulk messages are sent to validation. These are laboratory regressions, not a browser session, live model run or evidence for a higher TRL.

27 October draft review: one additional delayed-response regression reproduced input loss when text was edited during a save. The acknowledgement now clears only the text it actually submitted. All 12 Node tests pass; the unchanged 21 Python checks retain their prior exact-base CI evidence. No browser, model, deployment or TRL change is claimed.

- Run the dashboard in a browser against the same corpus and record the operator path: ingest, unparseable pile, claim, resolve.
- Deploy that build where a volunteer can reach it, with a human watching the unparseable pile.
- Repeat the corpus score on a fresh message set that was not used to choose the guard rules.
- Keep authentication and abuse limits in place before any network exposure beyond loopback.
