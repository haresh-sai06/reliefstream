"""LLM-based structured extraction of flood-rescue requests."""
import json
import os
import re
from openai import OpenAI
from models import ExtractedFields

LLM_BASE_URL = os.getenv('LLM_BASE_URL', 'http://localhost:11434/v1')
LLM_API_KEY = os.getenv('LLM_API_KEY', 'ollama')
LLM_MODEL = os.getenv('LLM_MODEL', 'qwen2.5:7b')

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

    # Enforce: parseable requires location + urgency + type + confidence >= 0.4
    if (not result.location
            or result.urgency == 'unknown'
            or result.request_type == 'unknown'
            or result.confidence < 0.4):
        result.parseable = False
        if not result.notes:
            result.notes = 'Missing one of {location, urgency, request_type} or confidence < 0.4'

    return result
