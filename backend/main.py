"""ReliefStream FastAPI backend — ingest, extract, dedup, serve, stream."""
import asyncio
import json
import os
from contextlib import asynccontextmanager
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sse_starlette.sse import EventSourceResponse

load_dotenv()

# Imports must come after load_dotenv so extractor picks up env vars
import extractor  # noqa: E402
import storage  # noqa: E402
from models import (  # noqa: E402
    ClaimRequest, IngestRequest, RescueRequest, ResolveRequest,
)

ALLOW_ORIGIN = os.getenv('ALLOW_ORIGIN', 'http://localhost:8080')

# ── Event bus for SSE (in-memory, single-process) ──
_subscribers: list[asyncio.Queue] = []


async def _broadcast(event: dict):
    dead = []
    for q in _subscribers:
        try:
            q.put_nowait(event)
        except asyncio.QueueFull:
            dead.append(q)
    for q in dead:
        _subscribers.remove(q)


@asynccontextmanager
async def lifespan(app: FastAPI):
    storage.init_db()
    print(f'[reliefstream] DB ready · model={extractor.LLM_MODEL} @ {extractor.LLM_BASE_URL}')
    yield


app = FastAPI(
    title='ReliefStream',
    description='Real-time centralization of flood-rescue requests',
    version='0.1.0',
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[ALLOW_ORIGIN, 'http://localhost:8080', 'http://127.0.0.1:8080'],
    allow_credentials=True,
    allow_methods=['*'],
    allow_headers=['*'],
)


@app.get('/', tags=['meta'])
async def root():
    return {
        'name': 'ReliefStream',
        'version': '0.1.0',
        'docs': '/docs',
        'endpoints': [
            'POST /ingest',
            'POST /ingest/bulk',
            'GET /requests',
            'GET /requests/{id}',
            'POST /requests/{id}/claim',
            'POST /requests/{id}/resolve',
            'POST /requests/{id}/triage',
            'GET /stats',
            'GET /stream',
        ],
    }


@app.post('/ingest', tags=['ingest'], response_model=RescueRequest)
async def ingest(req: IngestRequest):
    """Ingest a single raw message, extract, store, broadcast."""
    extracted = extractor.extract(req.text)
    stored, is_new = storage.upsert_request(
        text=req.text, source=req.source or 'paste',
        external_id=req.external_id, extracted=extracted,
    )
    await _broadcast({
        'type': 'new' if is_new else 'duplicate',
        'request_id': stored.id,
        'parseable': extracted.parseable,
    })
    return stored


@app.post('/ingest/bulk', tags=['ingest'])
async def ingest_bulk(items: list[IngestRequest]):
    """Ingest a batch — returns per-item results."""
    results = []
    for it in items:
        extracted = extractor.extract(it.text)
        stored, is_new = storage.upsert_request(
            text=it.text, source=it.source or 'paste',
            external_id=it.external_id, extracted=extracted,
        )
        results.append({'id': stored.id, 'parseable': extracted.parseable, 'is_new': is_new})
        await _broadcast({
            'type': 'new' if is_new else 'duplicate',
            'request_id': stored.id,
            'parseable': extracted.parseable,
        })
    return {'processed': len(results), 'results': results}


@app.get('/requests', tags=['read'], response_model=list[RescueRequest])
async def list_all(status: Optional[str] = Query(default=None), limit: int = 500):
    """Filter by status: new|triaged|claimed|resolved|unparseable (omit for all)."""
    return storage.list_requests(status=status, limit=limit)


@app.get('/requests/{rid}', tags=['read'], response_model=RescueRequest)
async def get_one(rid: str):
    r = storage.get_request(rid)
    if not r:
        raise HTTPException(404, 'not found')
    return r


@app.post('/requests/{rid}/claim', tags=['workflow'], response_model=RescueRequest)
async def claim(rid: str, body: ClaimRequest):
    r = storage.claim_request(rid, body.volunteer_name)
    if not r:
        raise HTTPException(404, 'not found or not claimable')
    await _broadcast({'type': 'claimed', 'request_id': rid, 'by': body.volunteer_name})
    return r


@app.post('/requests/{rid}/triage', tags=['workflow'], response_model=RescueRequest)
async def triage(rid: str, body: ClaimRequest):
    """Move an unparseable request into actionable queue after human review."""
    r = storage.triage_unparseable(rid, body.volunteer_name, note='human-triaged')
    if not r:
        raise HTTPException(404, 'not found or not in unparseable state')
    await _broadcast({'type': 'triaged', 'request_id': rid, 'by': body.volunteer_name})
    return r


@app.post('/requests/{rid}/resolve', tags=['workflow'], response_model=RescueRequest)
async def resolve(rid: str, body: ResolveRequest):
    r = storage.resolve_request(rid, body.volunteer_name, body.outcome, body.note)
    if not r:
        raise HTTPException(404, 'not found')
    await _broadcast({'type': 'resolved', 'request_id': rid, 'outcome': body.outcome})
    return r


@app.get('/stats', tags=['read'])
async def get_stats():
    return storage.stats()


@app.get('/stream', tags=['read'])
async def stream():
    """SSE: emits one event per request lifecycle change."""
    q: asyncio.Queue = asyncio.Queue(maxsize=100)
    _subscribers.append(q)

    async def event_gen():
        try:
            # Initial hello event
            yield {'event': 'hello', 'data': json.dumps({'connected': True})}
            while True:
                event = await q.get()
                yield {'event': event.get('type', 'update'), 'data': json.dumps(event)}
        except asyncio.CancelledError:
            if q in _subscribers:
                _subscribers.remove(q)
            raise

    return EventSourceResponse(event_gen())


if __name__ == '__main__':
    import uvicorn
    uvicorn.run('main:app', host='0.0.0.0', port=8000, reload=True)
