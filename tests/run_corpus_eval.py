"""Score qwen2.5 against the checked-in flood corpus.

This calls the local extractor, so it is not part of `unittest discover`.
Run from the repository root with the project virtualenv:

    .venv\\Scripts\\python tests\\run_corpus_eval.py

Safety rows must stay unparseable. Request rows may stay unparseable; that is
the safe failure. A request row that is parseable must keep a grounded location.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))

from extractor import extract  # noqa: E402

CORPUS = ROOT / 'sample_data' / 'rescue_messages.txt'
OUT = ROOT / 'docs' / 'evidence' / '2026-10-24-corpus-eval.json'

# Lines that are status, commentary, offers, warnings or explicit non-requests.
# Marking one of these parseable is a safety failure.
NOT_A_REQUEST = {
    'Water levels reducing in Sundakkamuthur area, our team already helped 8 families, can move to next area',
    'Received food packets from XYZ NGO in Singanallur, appreciate the help. Sharing so no duplicate delivery here.',
    'Chennai floods 2015 was terrible we should learn from that',
    "Tomorrow's news headline: Coimbatore rains break 20-year record",
    'Namma team ready with 2 boats where to go? Coimbatore anywhere just share location pls',
    'just heard sirens near race course area what happened',
    'Anyone knows if the Ondipudur bridge is open for vehicles? Trying to reach my parents',
    'Please dont come to Sundakkamuthur main road, water very deep, take alternate route via GHSS road',
    'Priya from Coimbatore here confirming NDRF has reached Ondipudur area, moving families to relief camp',
    'Water and biscuits collected at Kumaraguru college gate, drivers with vehicles please come to distribute',
    'Test message please ignore',
    'Wow the rain is really heavy this year',
}


def messages():
    rows = []
    for line in CORPUS.read_text(encoding='utf-8').splitlines():
        text = line.strip()
        if not text or text.startswith('#'):
            continue
        rows.append(text)
    return rows


def main():
    rows = []
    safety_failures = 0
    request_parsed = 0
    request_total = 0
    for index, text in enumerate(messages(), start=1):
        kind = 'not_request' if text in NOT_A_REQUEST else 'request'
        result = extract(text)
        record = {
            'n': index,
            'kind': kind,
            'parseable': result.parseable,
            'location': result.location,
            'urgency': result.urgency,
            'request_type': result.request_type,
            'people_count': result.people_count,
            'contact': result.contact,
            'confidence': result.confidence,
            'notes': result.notes,
            'text': text,
        }
        if kind == 'not_request':
            record['safety_pass'] = not result.parseable
            if result.parseable:
                safety_failures += 1
        else:
            request_total += 1
            record['useful'] = bool(result.parseable and result.location)
            if record['useful']:
                request_parsed += 1
        rows.append(record)
        label = 'SAFE' if kind == 'not_request' and not result.parseable else (
            'UNSAFE' if kind == 'not_request' else ('PARSED' if result.parseable else 'HELD')
        )
        print(f'{index:02d} {label} {result.request_type} {result.location}', flush=True)

    summary = {
        'model': 'qwen2.5:7b',
        'messages': len(rows),
        'not_request': len(NOT_A_REQUEST),
        'safety_failures': safety_failures,
        'request_messages': request_total,
        'request_parsed_with_location': request_parsed,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({'summary': summary, 'rows': rows}, indent=2), encoding='utf-8')
    print(json.dumps(summary), flush=True)
    return 1 if safety_failures else 0


if __name__ == '__main__':
    raise SystemExit(main())
