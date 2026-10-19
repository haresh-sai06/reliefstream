// ReliefStream frontend — vanilla JS

// Same-origin when served by the backend at /ui (Docker / cloud); localhost:8000 for the
// two-terminal dev setup (python -m http.server 8080). Override with window.RELIEFSTREAM_API.
const API = window.RELIEFSTREAM_API
  || (location.pathname.startsWith('/ui') ? location.origin : 'http://localhost:8000');
const state = {
  requests: [],
  filter: 'all',
  map: null,
  markers: new Map(),
};

// Coimbatore default center — where the source hackathon was held
const DEFAULT_CENTER = [11.0168, 76.9558];

// ── Init map ──────────────────────────────────────────────
function initMap() {
  state.map = L.map('map', { zoomControl: true }).setView(DEFAULT_CENTER, 12);
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19,
    attribution: '&copy; OpenStreetMap contributors',
  }).addTo(state.map);
}

function pinIcon(urgency) {
  return L.divIcon({
    className: 'custom-marker',
    html: `<div class="marker-pin ${urgency || 'unknown'}"></div>`,
    iconSize: [22, 30],
    iconAnchor: [11, 30],
    popupAnchor: [0, -30],
  });
}

// ── Load and render ───────────────────────────────────────
async function loadRequests() {
  try {
    const res = await fetch(`${API}/requests?limit=500`);
    state.requests = await res.json();
    render();
  } catch (e) {
    document.getElementById('request-list').innerHTML =
      '<div class="empty">Backend unreachable. Start it: <code>cd backend && uvicorn main:app</code></div>';
  }
}

async function loadStats() {
  try {
    const res = await fetch(`${API}/stats`);
    const s = await res.json();
    document.getElementById('stats-summary').textContent =
      `${s.total} requests · ${s.new + s.triaged} open · ${s.unparseable} unparseable`;
    document.getElementById('count-all').textContent = s.total;
    document.getElementById('count-new').textContent = s.new + s.triaged;
    document.getElementById('count-claimed').textContent = s.claimed;
    document.getElementById('count-resolved').textContent = s.resolved;
    document.getElementById('count-unparseable').textContent = s.unparseable;
  } catch (e) { /* silent */ }
}

function render() {
  const listEl = document.getElementById('request-list');
  const filtered = state.filter === 'all'
    ? state.requests
    : state.filter === 'new'
      ? state.requests.filter(r => r.status === 'new' || r.status === 'triaged')
      : state.requests.filter(r => r.status === state.filter);

  if (filtered.length === 0) {
    listEl.innerHTML = `<div class="empty">No requests in this bucket yet.</div>`;
  } else {
    listEl.innerHTML = filtered.map(renderRequest).join('');
    listEl.querySelectorAll('.req').forEach(el => {
      el.addEventListener('click', () => openModal(el.dataset.id));
    });
  }

  // Update markers
  syncMapMarkers();
}

function renderRequest(r) {
  const x = r.extracted;
  const isUnparseable = r.status === 'unparseable';
  const cls = isUnparseable ? 'unparseable' : `urgency-${x.urgency}`;
  const time = new Date(r.created_at).toLocaleTimeString('en-IN',
    { hour: '2-digit', minute: '2-digit' });
  return `
    <div class="req ${cls}" data-id="${r.id}">
      <div class="req-head">
        <div class="req-badges">
          ${isUnparseable
            ? '<span class="badge badge-urgency-immediate" style="background:var(--amber);color:var(--bg-deep)">READ YOURSELF</span>'
            : `<span class="badge badge-urgency-${x.urgency}">${x.urgency}</span>
               <span class="badge badge-type">${x.request_type}</span>`}
          ${r.status === 'claimed' ? `<span class="badge badge-status claimed">claimed · ${r.claimed_by}</span>` : ''}
          ${r.status === 'resolved' ? `<span class="badge badge-status resolved">resolved</span>` : ''}
          ${r.duplicate_count > 1 ? `<span class="badge badge-dup">×${r.duplicate_count}</span>` : ''}
        </div>
        <div class="req-time">${time}</div>
      </div>
      <div class="req-text">${escapeHtml(r.original_text)}</div>
      <div class="req-meta">
        ${x.location ? `<span>📍 <strong>${escapeHtml(x.location)}</strong></span>` : ''}
        ${x.people_count ? `<span>👥 ${x.people_count} people</span>` : ''}
        ${x.contact ? `<span>📞 ${escapeHtml(x.contact)}</span>` : ''}
        <span>src: ${r.source}</span>
      </div>
    </div>`;
}

function syncMapMarkers() {
  // Clear existing
  state.markers.forEach(m => state.map.removeLayer(m));
  state.markers.clear();

  state.requests.forEach(r => {
    const { lat, lon } = r.extracted;
    if (r.status === 'resolved') return;
    if (lat == null || lon == null) return;
    const marker = L.marker([lat, lon], { icon: pinIcon(r.extracted.urgency) })
      .addTo(state.map);
    marker.bindPopup(`
      <strong>${r.extracted.urgency.toUpperCase()} · ${r.extracted.request_type}</strong><br>
      ${escapeHtml(r.extracted.location || '')}<br>
      <em style="font-size:11px;color:#7a90b8">${escapeHtml(r.original_text.slice(0, 100))}...</em>
    `);
    marker.on('click', () => openModal(r.id));
    state.markers.set(r.id, marker);
  });
}

// ── Modal ─────────────────────────────────────────────────
function openModal(rid) {
  const r = state.requests.find(x => x.id === rid);
  if (!r) return;
  const x = r.extracted;
  const isUnparseable = r.status === 'unparseable';
  const html = `
    <button class="modal-close" onclick="closeModal()">&times;</button>
    <h3>${isUnparseable ? '⚠️ Read Yourself' : (x.urgency || '').toUpperCase() + ' — ' + (x.request_type || '')}</h3>
    <div class="modal-section">
      <div class="modal-section-label">Original message</div>
      <div class="modal-original">${escapeHtml(r.original_text)}</div>
    </div>
    ${isUnparseable ? `
      <div class="modal-section">
        <div class="modal-section-label">Why this went to "read yourself"</div>
        <div style="color:var(--amber);font-size:13px">${escapeHtml(x.notes || 'LLM could not extract required fields with sufficient confidence.')}</div>
      </div>` : `
      <div class="modal-section">
        <div class="modal-section-label">Extracted fields</div>
        <div style="font-family:monospace;font-size:12px;color:var(--text-muted);line-height:1.7">
          location: <strong style="color:var(--text)">${escapeHtml(x.location || '—')}</strong><br>
          urgency: <strong style="color:var(--text)">${x.urgency}</strong><br>
          type: <strong style="color:var(--text)">${x.request_type}</strong><br>
          people: <strong style="color:var(--text)">${x.people_count ?? '—'}</strong><br>
          contact: <strong style="color:var(--text)">${escapeHtml(x.contact || '—')}</strong><br>
          confidence: <strong style="color:var(--text)">${(x.confidence * 100).toFixed(0)}%</strong>
        </div>
      </div>`}
    ${r.duplicate_count > 1 ? `<div class="modal-section">confirmed by ${r.duplicate_count} identical messages</div>` : ''}
    <div class="modal-section">
      <div class="modal-section-label">Status</div>
      <div>${r.status}${r.claimed_by ? ` · claimed by ${escapeHtml(r.claimed_by)}` : ''}</div>
    </div>
    ${renderActions(r)}
  `;
  document.getElementById('modal-content').innerHTML = html;
  document.getElementById('modal').classList.remove('hidden');
}

function renderActions(r) {
  if (r.status === 'resolved') return '';
  if (r.status === 'unparseable') {
    return `
      <div class="modal-actions">
        <input type="text" id="volunteer" placeholder="Your name" />
        <button class="btn btn-primary" onclick="doTriage('${r.id}')">Move to queue (I read it)</button>
      </div>`;
  }
  if (r.status === 'new' || r.status === 'triaged') {
    return `
      <div class="modal-actions">
        <input type="text" id="volunteer" placeholder="Your name" />
        <button class="btn btn-primary" onclick="doClaim('${r.id}')">Claim</button>
      </div>`;
  }
  if (r.status === 'claimed') {
    return `
      <div class="modal-actions">
        <input type="text" id="volunteer" placeholder="Your name" value="${escapeAttr(r.claimed_by || '')}" />
        <select id="outcome">
          <option value="helped">Helped</option>
          <option value="already_resolved">Already resolved</option>
          <option value="not_actionable">Not actionable</option>
          <option value="wrong_info">Wrong info</option>
        </select>
        <input type="text" id="note" placeholder="Note (optional)" />
        <button class="btn btn-primary" onclick="doResolve('${r.id}')">Resolve</button>
      </div>`;
  }
  return '';
}

function closeModal() { document.getElementById('modal').classList.add('hidden'); }

async function doClaim(rid) {
  const name = document.getElementById('volunteer').value.trim();
  if (!name) { alert('Enter your name'); return; }
  await fetch(`${API}/requests/${rid}/claim`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ volunteer_name: name }),
  });
  closeModal();
  await refresh();
}

async function doTriage(rid) {
  const name = document.getElementById('volunteer').value.trim();
  if (!name) { alert('Enter your name'); return; }
  await fetch(`${API}/requests/${rid}/triage`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ volunteer_name: name }),
  });
  closeModal();
  await refresh();
}

async function doResolve(rid) {
  const name = document.getElementById('volunteer').value.trim();
  const outcome = document.getElementById('outcome').value;
  const note = document.getElementById('note').value.trim();
  if (!name) { alert('Enter your name'); return; }
  await fetch(`${API}/requests/${rid}/resolve`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ volunteer_name: name, outcome, note: note || null }),
  });
  closeModal();
  await refresh();
}

// ── Ingest ────────────────────────────────────────────────
document.getElementById('ingest-btn').addEventListener('click', async () => {
  const btn = document.getElementById('ingest-btn');
  const text = document.getElementById('ingest-text').value.trim();
  const source = document.getElementById('ingest-source').value;
  const bulk = document.getElementById('ingest-bulk').checked;
  const resultEl = document.getElementById('ingest-result');
  if (!text) return;

  btn.disabled = true;
  btn.textContent = 'Extracting…';
  resultEl.className = 'ingest-result';

  try {
    if (bulk) {
      const lines = text.split('\n').map(l => l.trim()).filter(l => l.length > 5);
      const items = lines.map(l => ({ text: l, source }));
      const res = await fetch(`${API}/ingest/bulk`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(items),
      });
      const data = await res.json();
      const parseable = data.results.filter(r => r.parseable).length;
      resultEl.textContent = `Ingested ${data.processed} · parseable: ${parseable} · unparseable: ${data.processed - parseable}`;
      resultEl.className = 'ingest-result ok';
    } else {
      const res = await fetch(`${API}/ingest`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text, source }),
      });
      const data = await res.json();
      if (data.extracted && data.extracted.parseable) {
        resultEl.textContent = `Parsed: ${data.extracted.urgency} · ${data.extracted.request_type} · ${data.extracted.location || 'no location'}`;
        resultEl.className = 'ingest-result ok';
      } else {
        resultEl.textContent = `Sent to "Read yourself" pile — ${data.extracted?.notes || 'insufficient extraction'}`;
        resultEl.className = 'ingest-result warn';
      }
    }
    document.getElementById('ingest-text').value = '';
  } catch (e) {
    resultEl.textContent = `Error: ${e.message}`;
    resultEl.className = 'ingest-result err';
  } finally {
    btn.disabled = false;
    btn.textContent = 'Submit';
    await refresh();
  }
});

// ── Tab filtering ─────────────────────────────────────────
document.querySelectorAll('.tab').forEach(t => {
  t.addEventListener('click', () => {
    document.querySelectorAll('.tab').forEach(x => x.classList.remove('active'));
    t.classList.add('active');
    state.filter = t.dataset.filter;
    render();
  });
});

// ── SSE ───────────────────────────────────────────────────
function connectSSE() {
  const dot = document.getElementById('connection-dot');
  const txt = document.getElementById('connection-text');
  const es = new EventSource(`${API}/stream`);
  es.onopen = () => { dot.className = 'conn-dot connected'; txt.textContent = 'live'; };
  es.onerror = () => {
    dot.className = 'conn-dot disconnected'; txt.textContent = 'reconnecting…';
    setTimeout(connectSSE, 3000);
    es.close();
  };
  ['new', 'duplicate', 'claimed', 'resolved', 'triaged', 'update'].forEach(evt => {
    es.addEventListener(evt, e => {
      const data = JSON.parse(e.data);
      if (evt === 'new') toast('New request received');
      refresh();
    });
  });
}

function toast(msg) {
  const t = document.createElement('div');
  t.className = 'toast';
  t.textContent = msg;
  document.body.appendChild(t);
  setTimeout(() => t.remove(), 3000);
}

async function refresh() {
  await loadStats();
  await loadRequests();
}

function escapeHtml(s) {
  return String(s || '').replace(/[&<>"']/g, c =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}
function escapeAttr(s) { return escapeHtml(s); }
window.closeModal = closeModal;
window.doClaim = doClaim;
window.doTriage = doTriage;
window.doResolve = doResolve;

// ── Boot ──────────────────────────────────────────────────
initMap();
refresh();
connectSSE();
setInterval(refresh, 15000);  // fallback polling every 15s
