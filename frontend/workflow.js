// Reject failed writes before the caller dismisses the form as successful.
async function sendWorkflowUpdate(url, payload) {
  let response;
  try {
    response = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
  } catch {
    throw new Error('Cannot reach the server. Your action was not confirmed.');
  }
  if (!response.ok) {
    throw new Error(response.status === 409
      ? 'This request has changed. Close and reopen it to see its current state.'
      : `Request could not be updated (HTTP ${response.status}). Check its current state before retrying.`);
  }
  return response;
}
