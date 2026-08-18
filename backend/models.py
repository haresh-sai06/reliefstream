"""Pydantic schemas for ReliefStream."""
from typing import Literal, Optional
from pydantic import BaseModel, Field
from datetime import datetime


class IngestRequest(BaseModel):
    """A raw incoming message from any channel."""
    text: str = Field(..., min_length=3, max_length=4000)
    source: Optional[str] = Field(default='paste', description='twitter|whatsapp|instagram|paste|webhook')
    external_id: Optional[str] = Field(default=None, description='original message id if any')


class ExtractedFields(BaseModel):
    """LLM's structured extraction of a rescue request."""
    location: Optional[str] = Field(default=None, description='free-text location, e.g. "opposite Kovai Kutralam, Ganapathy"')
    lat: Optional[float] = Field(default=None, description='latitude if extractable')
    lon: Optional[float] = Field(default=None, description='longitude if extractable')
    urgency: Literal['immediate', 'high', 'medium', 'low', 'unknown'] = 'unknown'
    request_type: Literal['rescue', 'medical', 'food', 'water', 'shelter', 'evacuation', 'other', 'unknown'] = 'unknown'
    people_count: Optional[int] = Field(default=None, description='number of people needing help if mentioned')
    contact: Optional[str] = Field(default=None, description='phone number or handle if present')
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    parseable: bool = Field(default=False, description='True if location + urgency + type all extracted with confidence >= 0.4')
    notes: Optional[str] = Field(default=None, description='LLM notes on ambiguity or safety flags')


class RescueRequest(BaseModel):
    """A stored rescue request — original text + extraction + workflow state."""
    id: str
    fingerprint: str
    original_text: str
    source: str
    external_id: Optional[str] = None
    extracted: ExtractedFields
    status: Literal['new', 'triaged', 'claimed', 'resolved', 'unparseable'] = 'new'
    claimed_by: Optional[str] = None
    resolved_by: Optional[str] = None
    resolved_note: Optional[str] = None
    duplicate_count: int = 1
    created_at: datetime
    updated_at: datetime


class ClaimRequest(BaseModel):
    volunteer_name: str = Field(..., min_length=1, max_length=100)


class ResolveRequest(BaseModel):
    volunteer_name: str = Field(..., min_length=1, max_length=100)
    outcome: Literal['helped', 'already_resolved', 'not_actionable', 'wrong_info']
    note: Optional[str] = Field(default=None, max_length=500)


class Stats(BaseModel):
    total: int
    new: int
    triaged: int
    claimed: int
    resolved: int
    unparseable: int
    by_urgency: dict[str, int]
    by_type: dict[str, int]
