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
    action, onConfirm() {}, onCancel() {}, onVerify() {}, onCodeChange() {}, onRetry() {}, ...extra,
  }));
}

test('clean tool arguments plus separate approval render a confirmable transfer', () => {
  const html = render();
  assert.match(html, /20\.00 CNY/);
  assert.match(html, /bob/);
  assert.match(html, /act_from_backend/);
  assert.match(html, /Tier: YELLOW/);
  assert.match(html, /Confirm &amp; Execute/);
  assert.match(html, /Cancel approval/);
  assert.doesNotMatch(html, /6-digit code|>Verify</);
});

test('MFA status replaces confirmation with OTP and displays escalation to RED', () => {
  const html = render(transfer, { state: { status: 'PENDING_MFA', inboxMessage: 'Demo code: 123456' } });
  assert.match(html, /Tier: RED/);
  assert.match(html, /6-digit code/);
  assert.match(html, /Verify/);
  assert.match(html, /Demo code: 123456/);
  assert.match(html, /Cancel approval/);
  assert.doesNotMatch(html, /Confirm &amp; Execute/);
});

test('completion keeps the escalated tier and cannot render execution controls', () => {
  const html = render(transfer, { state: { status: 'COMPLETED', tier: 'RED', message: 'Bank confirmed completion.' } });
  assert.match(html, /Tier: RED/);
  assert.match(html, /Bank confirmed completion/);
  assert.doesNotMatch(html, /Confirm &amp; Execute|Cancel approval|6-digit code|>Verify</);
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

test('cancellation sends only the approval digest and a stable action-scoped key', async () => {
  const originalFetch = globalThis.fetch;
  const requests = [];
  globalThis.fetch = async (url, options) => {
    requests.push({ url, options });
    return { ok: true, json: async () => ({ action_id: 'act/id', status: 'CANCELLED', audit_id: 'aud_cancel' }) };
  };
  try {
    await api.cancelAction('act/id', 'a'.repeat(64));
    await api.cancelAction('act/id', 'a'.repeat(64));
    assert.equal(requests[0].url, '/api/v1/actions/act%2Fid/cancel');
    const body = JSON.parse(requests[0].options.body);
    assert.deepEqual(Object.keys(body).sort(), ['action_digest', 'idempotency_key']);
    assert.equal(body.action_digest, 'a'.repeat(64));
    assert.equal(requests[0].options.body, requests[1].options.body);
  } finally { globalThis.fetch = originalFetch; }
});

test('cancellation conflicts remain errors rather than being labelled cancelled', async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () => ({ ok: false, json: async () => ({ detail: 'Already completed; cannot cancel' }) });
  try {
    await assert.rejects(api.cancelAction('act', 'a'.repeat(64)), /Already completed; cannot cancel/);
  } finally { globalThis.fetch = originalFetch; }
});

test('status recovery uses the owned action read endpoint without an execution request', async () => {
  const originalFetch = globalThis.fetch;
  let request;
  globalThis.fetch = async (url, options) => {
    request = { url, options };
    return { ok: true, json: async () => ({ ...transfer.approval, status: 'COMPLETED' }) };
  };
  try {
    const metadata = await api.fetchActionStatus('act/id');
    assert.equal(metadata.status, 'COMPLETED');
    assert.equal(request.url, '/api/v1/actions/act%2Fid');
    assert.equal(request.options.body, undefined);
    assert.equal(request.options.method, undefined);
  } finally { globalThis.fetch = originalFetch; }
});

for (const status of ['FAILED', 'REJECTED', 'CANCELLED']) {
  test(`${status} metadata cannot render confirmation or verification`, () => {
    const html = render({ ...transfer, approval: { ...transfer.approval, status } });
    assert.match(html, new RegExp(status, 'i'));
    assert.doesNotMatch(html, /Confirm &amp; Execute|Cancel approval|6-digit code|>Verify</);
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
  assert.doesNotMatch(html, /Confirm &amp; Execute|Cancel approval|6-digit code/);
});

test('pending controls and notification retry are disabled during an action request', () => {
  const html = render(transfer, { state: { status: 'PENDING_MFA' }, busy: true, continuationError: 'Retry later' });
  assert.match(html, /Cancel approval/);
  assert.match(html, /Verify/);
  assert.equal((html.match(/<button disabled=""/g) || []).length, 3);
});

test('history retrieval is read-only and uses the selected conversation and page cursor', async () => {
  const originalFetch = globalThis.fetch;
  const requests = [];
  globalThis.fetch = async (url, options) => {
    requests.push({ url, options });
    return { ok: true, json: async () => ({ messages: [], has_more: false }) };
  };
  try {
    await api.fetchConversation('conv/owned', 42);
    await api.fetchConversations(50);
    assert.equal(requests[0].url, '/api/v1/conversations/conv%2Fowned?before_id=42');
    assert.equal(requests[1].url, '/api/v1/conversations?offset=50');
    for (const request of requests) {
      assert.equal(request.options.method, undefined);
      assert.equal(request.options.body, undefined);
      assert.equal(request.options.headers['X-Demo-User-Id'], 'usr_demo_01');
      assert.doesNotMatch(request.url, /confirm|verify|continue/);
    }
  } finally { globalThis.fetch = originalFetch; }
});

test('new chats are created on the server without a previous conversation state', async () => {
  const originalFetch = globalThis.fetch;
  let request;
  globalThis.fetch = async (url, options) => {
    request = { url, options };
    return { ok: true, json: async () => ({ conversation_id: 'conv_new' }) };
  };
  try {
    assert.equal((await api.createConversation()).conversation_id, 'conv_new');
    assert.equal(request.url, '/api/v1/conversations');
    assert.equal(request.options.method, 'POST');
    assert.equal(request.options.body, undefined);
  } finally { globalThis.fetch = originalFetch; }
});

test('missing history can fall back to a new selection but server errors stay errors', async () => {
  const originalFetch = globalThis.fetch;
  try {
    globalThis.fetch = async () => ({ ok: false, status: 404 });
    assert.equal(await api.fetchConversation('missing'), null);
    globalThis.fetch = async () => ({ ok: false, status: 500 });
    await assert.rejects(api.fetchConversation('owned'), /Could not load this chat/);
  } finally { globalThis.fetch = originalFetch; }
});

test('chat sends the selected conversation rather than the legacy shared ID', async () => {
  const originalFetch = globalThis.fetch;
  let request;
  globalThis.fetch = async (url, options) => {
    request = { url, options };
    return { ok: true, json: async () => ({ conversation_id: 'conv_selected', actions: [] }) };
  };
  try {
    await api.sendChatMessage('What is my balance?', 'conv_selected');
    assert.deepEqual(JSON.parse(request.options.body), {
      conversation_id: 'conv_selected', message: 'What is my balance?',
    });
  } finally { globalThis.fetch = originalFetch; }
});
