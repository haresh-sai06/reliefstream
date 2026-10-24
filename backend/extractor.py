"""LLM-based structured extraction of flood-rescue requests."""
import json
import os
import re
from openai import OpenAI
from models import ExtractedFields

LLM_BASE_URL = os.getenv('LLM_BASE_URL', 'http://localhost:11434/v1')
LLM_API_KEY = os.getenv('LLM_API_KEY', 'ollama')
LLM_MODEL = os.getenv('LLM_MODEL', 'qwen2.5:7b')
REQUEST_CUES = re.compile(
    r'\b(?:need|needs|needed|help|rescue|stuck|trapped|stranded|urgent|'
    r'please|boat|ambulance|insulin|medicine|wheelchair|injured|fracture|fractured|fever)\b',
    re.IGNORECASE,
)

_client = OpenAI(
    api_key=LLM_API_KEY or 'sk-dummy',
    base_url=LLM_BASE_URL,
    timeout=60.0,
)

SYSTEM_PROMPT = """You are ReliefStream, a structured-extraction agent for flood rescue coordination.

You receive raw text from social media, WhatsApp forwards, or SMS during a flood emergency. Your job is to extract structured fields so volunteers can act quickly.

CRITICAL SAFETY RULES:
1. If you cannot confidently determine location OR urgency OR request type, set parseable=false and confidence < 0.4. A wrong answer sends volunteers to the wrong place while people wait.
2. Never invent a location, phone number, or victim count. If not present in the text, leave the field null.
3. If the message is not actually about needing help (news article, generic tweet, warning), set parseable=false with notes explaining why.
4. If message is in Tamil / Hindi / mixed language, extract the meaning but preserve place names verbatim.

Return ONE JSON object matching this exact schema:
{
  "location": "free-text location or null",
  "lat": null,
  "lon": null,
  "urgency": "immediate|high|medium|low|unknown",
  "request_type": "rescue|medical|food|water|shelter|evacuation|other|unknown",
  "people_count": integer or null,
  "contact": "phone number if visible or null",
  "confidence": 0.0 to 1.0,
  "parseable": true or false,
  "notes": "one short sentence if ambiguity or safety flag, else null"
}

URGENCY GUIDE:
- "immediate": stranded on rooftop, medical emergency, elderly/children/disabled in water, drowning risk
- "high": trapped indoors with rising water, injured, no supplies for >12hr
- "medium": stranded but safe for now, needs relocation
- "low": needs supplies at safe location
- "unknown": cannot determine

Respond with ONLY the JSON object. No markdown, no code fences, no prose."""


def _clean_json(text: str) -> str:
    text = text.strip()
    if text.startswith('```'):
        text = re.sub(r'^```(?:json)?\s*|\s*```$', '', text, flags=re.DOTALL)
    text = text.strip()
    if not text.startswith('{'):
        m = re.search(r'\{.*\}', text, re.DOTALL)
        if m:
            text = m.group(0)
    return text


def extract(raw_text: str) -> ExtractedFields:
    """Call LLM to extract structured fields. Returns unparseable on any failure."""
    try:
        response = _client.chat.completions.create(
            model=LLM_MODEL,
            messages=[
                {'role': 'system', 'content': SYSTEM_PROMPT},
                {'role': 'user', 'content': f'MESSAGE TO EXTRACT:\n\n{raw_text}'},
            ],
            response_format={'type': 'json_object'},
            temperature=0.2,
            max_tokens=400,
        )
        text = response.choices[0].message.content or ''
        text = _clean_json(text)
        data = json.loads(text)
    except json.JSONDecodeError:
        return ExtractedFields(
            confidence=0.0, parseable=False,
            notes='LLM returned malformed JSON — sent to unparseable pile',
        )
    except Exception as e:
        return ExtractedFields(
            confidence=0.0, parseable=False,
            notes=f'LLM extraction failed: {str(e)[:100]}',
        )

    # Post-validation — enforce safety rules the model may violate
    try:
        result = ExtractedFields(**data)
    except Exception as e:
        return ExtractedFields(
            confidence=0.0, parseable=False,
            notes=f'Schema validation failed: {str(e)[:100]}',
        )

    return ground_to_source(result, raw_text)


def ground_to_source(result: ExtractedFields, raw_text: str) -> ExtractedFields:
    """Drop contacts, coordinates and locations that are not present in the message.

    The model is instructed not to invent these fields. This check is the
    deterministic backstop: a place or phone that the message does not contain
    cannot be shown to volunteers as fact.
    """
    notes = []
    source_digits = re.sub(r'\D', '', raw_text)
    if result.contact:
        contact_digits = re.sub(r'\D', '', result.contact)
        if len(contact_digits) < 6 or contact_digits not in source_digits:
            result.contact = None
            notes.append('dropped a contact number that is not in the message')

    for coord in ('lat', 'lon'):
        value = getattr(result, coord)
        if value is None:
            continue
        rendered = {str(value), f'{value:.4f}', f'{value:.5f}', f'{value:.6f}'}
        if not any(item and item in raw_text for item in rendered):
            setattr(result, coord, None)
            notes.append(f'dropped {coord} that is not in the message')

    if result.location:
        tokens = re.findall(r'[^\W\d_]{4,}', result.location, flags=re.UNICODE)
        source = raw_text.casefold()
        long_tokens = [token for token in tokens if len(token) >= 5]
        required = long_tokens or tokens
        if not required or not any(token.casefold() in source for token in required):
            result.location = None
            result.parseable = False
            notes.append('dropped a location that is not grounded in the message')

    if result.parseable and not _reads_as_help_request(raw_text):
        result.parseable = False
        notes.append('message does not read as a request for help')

    if notes:
        extra = '; '.join(notes)
        result.notes = f'{result.notes}; {extra}' if result.notes else extra

    if (not result.location
            or result.urgency == 'unknown'
            or result.request_type == 'unknown'
            or result.confidence < 0.4):
        result.parseable = False
        if not result.notes:
            result.notes = 'Missing one of {location, urgency, request_type} or confidence < 0.4'
    return result


def _reads_as_help_request(raw_text: str) -> bool:
    """Latin-script text must contain a request cue. Tamil and Hindi stay on the model."""
    if re.search(r'[\u0900-\u097F\u0B80-\u0BFF]', raw_text):
        return True
    return REQUEST_CUES.search(raw_text) is not None
