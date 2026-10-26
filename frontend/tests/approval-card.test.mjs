import assert from 'node:assert/strict';
import { after, test } from 'node:test';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { createServer } from 'vite';

const server = await createServer({ server: { middlewareMode: true }, appType: 'custom' });
const { ApprovalCard } = await server.ssrLoadModule('/src/ApprovalCard.tsx');
const api = await server.ssrLoadModule('/src/api.ts');
after(() => server.close());
const transfer = {
  proposal_id: 'proposal_from_p1', tool: 'request_transfer',
  arguments: { source_account_id: 'acc_owned', recipient_id: 'bob', amount: '20.00', currency: 'CNY' },
  approval: { action_id: 'act_from_backend', action_digest: 'a'.repeat(64), tier: 'YELLOW', status: 'PENDING_CONFIRMATION' },
};

function render(action = transfer, extra = {}) {
  return renderToStaticMarkup(createElement(ApprovalCard, {
    action, onConfirm() {}, onVerify() {}, onCodeChange() {}, onRetry() {}, ...extra,
  }));
}

test('clean tool arguments plus separate approval render a confirmable transfer', () => {
  const html = render();
  assert.match(html, /20\.00 CNY/);
  assert.match(html, /bob/);
  assert.match(html, /act_from_backend/);
  assert.match(html, /Tier: YELLOW/);
  assert.match(html, /Confirm &amp; Execute/);
  assert.doesNotMatch(html, /6-digit code|>Verify</);
});

test('MFA status replaces confirmation with OTP and displays escalation to RED', () => {
  const html = render(transfer, { state: { status: 'PENDING_MFA', inboxMessage: 'Demo code: 123456' } });
  assert.match(html, /Tier: RED/);
  assert.match(html, /6-digit code/);
  assert.match(html, /Verify/);
  assert.match(html, /Demo code: 123456/);
  assert.doesNotMatch(html, /Confirm &amp; Execute/);
});

test('completion keeps the escalated tier and cannot render execution controls', () => {
  const html = render(transfer, { state: { status: 'COMPLETED', tier: 'RED', message: 'Bank confirmed completion.' } });
  assert.match(html, /Tier: RED/);
  assert.match(html, /Bank confirmed completion/);
  assert.doesNotMatch(html, /Confirm &amp; Execute|6-digit code|>Verify</);
});

test('completed metadata from a replay is safe before local state exists', () => {
  const html = render({ ...transfer, approval: { ...transfer.approval, status: 'COMPLETED' } });
  assert.match(html, /Executed successfully/);
  assert.doesNotMatch(html, /Confirm &amp; Execute|6-digit code/);
});

test('fresh completed metadata replaces stale local MFA state', () => {
  const html = render({ ...transfer, approval: { ...transfer.approval, status: 'COMPLETED', tier: 'RED' } },
    { state: { status: 'PENDING_MFA' } });
  assert.match(html, /Tier: RED/);
  assert.match(html, /Executed successfully/);
  assert.doesNotMatch(html, /Confirm &amp; Execute|6-digit code/);
});

test('delayed pending metadata cannot reopen a locally completed action', () => {
  const html = render(transfer, { state: { status: 'COMPLETED' } });
  assert.match(html, /Executed successfully/);
  assert.doesNotMatch(html, /Confirm &amp; Execute|6-digit code/);
});

test('confirm sends the shared request fields and uses the server action ID', async () => {
  const originalFetch = globalThis.fetch;
  let request;
  globalThis.fetch = async (url, options) => {
    request = { url, options };
    return { ok: true, json: async () => ({ action_id: 'act/id', status: 'COMPLETED' }) };
  };
  try {
    await api.confirmAction('act/id', 'a'.repeat(64));
    assert.equal(request.url, '/api/v1/actions/act%2Fid/confirm');
    const body = JSON.parse(request.options.body);
    assert.deepEqual(Object.keys(body).sort(), ['action_digest', 'confirmation_id', 'idempotency_key']);
    assert.equal(body.action_digest, 'a'.repeat(64));
    assert.ok(body.confirmation_id && body.idempotency_key);
  } finally { globalThis.fetch = originalFetch; }
});

test('MFA sends the shared key and code without financial arguments or identity', async () => {
  const originalFetch = globalThis.fetch;
  let request;
  globalThis.fetch = async (url, options) => {
    request = { url, options };
    return { ok: true, json: async () => ({ action_id: 'act/id', status: 'COMPLETED' }) };
  };
  try {
    await api.verifyAction('act/id', '123456');
    assert.equal(request.url, '/api/v1/actions/act%2Fid/verify');
    const body = JSON.parse(request.options.body);
    assert.deepEqual(Object.keys(body).sort(), ['idempotency_key', 'verification_code']);
    assert.equal(body.verification_code, '123456');
    assert.ok(body.idempotency_key);
  } finally { globalThis.fetch = originalFetch; }
});

for (const status of ['FAILED', 'REJECTED', 'CANCELLED']) {
  test(`${status} metadata cannot render confirmation or verification`, () => {
    const html = render({ ...transfer, approval: { ...transfer.approval, status } });
    assert.match(html, new RegExp(status));
    assert.doesNotMatch(html, /Confirm &amp; Execute|6-digit code|>Verify</);
  });
}

test('subscription cancellation renders its own arguments and approval', () => {
  const html = render({ ...transfer, tool: 'request_subscription_cancel', arguments: { subscription_id: 'sub_owned' } });
  assert.match(html, /sub_owned/);
  assert.match(html, /act_from_backend/);
  assert.match(html, /Confirm &amp; Execute/);
  assert.doesNotMatch(html, /Amount:|Recipient:/);
});

test('conversation delivery failure allows notification retry without another execution', () => {
  const html = render(transfer, { state: { status: 'COMPLETED' }, continuationError: 'Conversation update unavailable.' });
  assert.match(html, /Executed successfully/);
  assert.match(html, /Retry conversation update/);
  assert.doesNotMatch(html, /Confirm &amp; Execute|6-digit code/);
});
