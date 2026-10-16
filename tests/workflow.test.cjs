const {test} = require('node:test');
const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const {runInNewContext} = require('node:vm');
const source = readFileSync(require('node:path').join(__dirname, '../frontend/workflow.js'), 'utf8');
function sender(fetch) {
  const context = {fetch};
  runInNewContext(source, context);
  return context.sendWorkflowUpdate;
}
test('successful write sends the intended payload once', async () => {
  const calls = [];
  await sender(async (...args) => {calls.push(args); return {ok:true};})('/requests/test/claim', {volunteer_name:'Synthetic A'});
  assert.equal(calls.length, 1);
  assert.equal(calls[0][0], '/requests/test/claim');
  assert.equal(calls[0][1].method, 'POST');
  assert.deepEqual(JSON.parse(calls[0][1].body), {volunteer_name:'Synthetic A'});
});
test('409 rejects the write instead of reporting success', async () => {
  await assert.rejects(sender(async () => ({ok:false,status:409}))('/test', {}), /request has changed/);
});
test('missing or unavailable server status rejects the write', async () => {
  for (const status of [404,503]) {
    await assert.rejects(sender(async () => ({ok:false,status}))('/test', {}), new RegExp(`HTTP ${status}`));
  }
});
test('network failure does not claim the action was saved', async () => {
  await assert.rejects(sender(async () => {throw new Error('offline');})('/test', {}), /action was not confirmed/);
});
