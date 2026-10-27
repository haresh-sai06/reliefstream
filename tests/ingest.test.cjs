const {test} = require('node:test');
const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const {join} = require('node:path');
const {runInNewContext} = require('node:vm');

// Exercise the real submit listener and write helper; no map, model or network.
function form(response, {bulk = false, text = 'Synthetic request at Test Street'} = {}) {
  const elements = new Map();
  let submit;
  const element = id => {
    if (!elements.has(id)) elements.set(id, {value: '', textContent: '', className: '',
      addEventListener(event, handler) { if (id === 'ingest-btn' && event === 'click') submit = handler; }});
    return elements.get(id);
  };
  const calls = [];
  const context = {document: {getElementById: element, querySelectorAll: () => []},
    window: {}, fetch: async (...args) => { calls.push(args); return response; }};
  runInNewContext(readFileSync(join(__dirname, '../frontend/workflow.js'), 'utf8'), context);
  const app = readFileSync(join(__dirname, '../frontend/app.js'), 'utf8');
  const boot = app.indexOf('// ── Boot');
  assert.ok(boot > 0);
  runInNewContext(app.slice(0, boot), context);
  context.refresh = async () => {};
  element('ingest-text').value = text;
  element('ingest-source').value = 'paste';
  element('ingest-bulk').checked = bulk;
  return {submit, element, calls, text};
}

test('single HTTP failure keeps the message and reports the status', async () => {
  const f = form({ok: false, status: 503, json: async () => ({detail: 'unavailable'})});
  await f.submit();
  assert.equal(f.element('ingest-text').value, f.text);
  assert.match(f.element('ingest-result').textContent, /HTTP 503/);
  assert.equal(f.element('ingest-result').className, 'ingest-result err');
  assert.equal(f.element('ingest-btn').disabled, false);
  assert.equal(f.calls.length, 1);
});

test('bulk HTTP failure keeps all messages and reports the status', async () => {
  const f = form({ok: false, status: 413, json: async () => ({detail: 'too large'})},
    {bulk: true, text: 'Synthetic request one\nSynthetic request two'});
  await f.submit();
  assert.equal(f.element('ingest-text').value, f.text);
  assert.match(f.element('ingest-result').textContent, /HTTP 413/);
});

test('unconfirmed single response cannot clear the input or claim it was queued', async () => {
  const f = form({ok: true, json: async () => ({})});
  await f.submit();
  assert.equal(f.element('ingest-text').value, f.text);
  assert.equal(f.element('ingest-result').className, 'ingest-result err');
});

test('partial bulk acknowledgement keeps the complete batch for reconciliation', async () => {
  const f = form({ok: true, json: async () => ({processed: 1, results: [{id: 'one', parseable: true}]})},
    {bulk: true, text: 'Synthetic request one\nSynthetic request two'});
  await f.submit();
  assert.equal(f.element('ingest-text').value, f.text);
  assert.equal(f.element('ingest-result').className, 'ingest-result err');
});

test('confirmed unparseable single is queued and clears only after acknowledgement', async () => {
  const f = form({ok: true, json: async () => ({id: 'saved', extracted: {parseable: false, notes: 'review needed'}})});
  await f.submit();
  assert.equal(f.element('ingest-text').value, '');
  assert.match(f.element('ingest-result').textContent, /Read yourself/);
  assert.equal(f.element('ingest-result').className, 'ingest-result warn');
});

test('complete bulk acknowledgement clears input and reports real counts', async () => {
  const f = form({ok: true, json: async () => ({processed: 2, results: [
    {id: 'one', parseable: true}, {id: 'two', parseable: false}]})},
    {bulk: true, text: 'Synthetic request one\nSynthetic request two'});
  await f.submit();
  assert.equal(f.element('ingest-text').value, '');
  assert.match(f.element('ingest-result').textContent, /Ingested 2 · parseable: 1 · unparseable: 1/);
});

test('bulk submission sends short nonempty messages instead of silently discarding them', async () => {
  const f = form({ok: true, json: async () => ({processed: 2, results: [
    {id: 'one', parseable: true}, {id: 'two', parseable: false}]})},
    {bulk: true, text: 'Synthetic request one\nSOS\n  '});
  await f.submit();
  const payload = JSON.parse(f.calls[0][1].body);
  assert.deepEqual(payload.map(item => item.text), ['Synthetic request one', 'SOS']);
  assert.equal(f.element('ingest-text').value, '');
});

test('acknowledging an earlier message cannot erase text entered while it was saving', async () => {
  let acknowledge;
  const response = new Promise(resolve => { acknowledge = resolve; });
  const f = form(response);
  const pending = f.submit();
  f.element('ingest-text').value = 'A different synthetic request typed while waiting';
  acknowledge({ok: true, json: async () => ({id: 'saved', extracted: {parseable: true}})});
  await pending;
  assert.equal(f.element('ingest-text').value, 'A different synthetic request typed while waiting');
  assert.match(f.element('ingest-result').textContent, /Newer text has been kept/);
  assert.equal(f.calls.length, 1);
});
