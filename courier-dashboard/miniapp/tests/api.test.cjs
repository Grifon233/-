// Run from miniapp with: node --test tests/api.test.cjs
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '../js/api.js'), 'utf8');

function createAPI(fetch, protocol = 'https:') {
  const timers = new Map();
  const context = {
    window: {}, location: { protocol }, AbortController, URLSearchParams, fetch,
    setTimeout: (callback, ms) => {
      const key = Symbol();
      timers.set(key, { callback, ms });
      return key;
    },
    clearTimeout: (key) => timers.delete(key),
  };
  vm.runInNewContext(source, context);
  return { api: context.window.API, timers };
}

function waitForAbort(signal) {
  return new Promise((resolve, reject) => {
    if (signal.aborted) reject(signal.reason);
    else signal.addEventListener('abort', () => reject(signal.reason), { once: true });
  });
}

test('streets query uses origin, correct city query, and fresh data', async () => {
  const result = [];
  const { api, timers } = createAPI(async (url, options) => {
    assert.equal(new URL(url, 'https://example.test').searchParams.get('city'), 'Санкт-Петербург + область');
    assert.match(url, /^\/streets\?/);
    assert.equal(options.cache, 'no-store');
    return new Response(JSON.stringify(result));
  });
  assert.deepEqual(await api.getStreets('Санкт-Петербург + область'), result);
  assert.equal(timers.size, 0);
});

test('request cancellation stops a stale fetch and cleans up its timeout', async () => {
  const { api, timers } = createAPI((url, { signal }) => waitForAbort(signal));
  const controller = new AbortController();
  const oldCity = api.getStreets('Москва', controller.signal);
  controller.abort();
  await assert.rejects(oldCity, { name: 'AbortError' });
  assert.equal(timers.size, 0);
});

test('the timeout still covers a response whose body has not arrived', async () => {
  const { api, timers } = createAPI(async (url, { signal }) => ({
    ok: true, json: () => waitForAbort(signal),
  }));
  const streets = api.getStreets('Казань');
  await Promise.resolve();
  const [timer] = timers.values();
  assert.equal(timer.ms, 12000);
  timer.callback();
  await assert.rejects(streets, { code: 'timeout' });
  assert.equal(timers.size, 0);
});

test('invalid API body is distinguishable from HTTP errors', async () => {
  const { api } = createAPI(async () => new Response('Not JSON'));
  await assert.rejects(api.getStreets('Москва'), { code: 'invalid_response' });
  const { api: limited } = createAPI(async () => new Response('{}', { status: 429 }));
  await assert.rejects(limited.sendFeedback({ text: 'Сообщение' }), { status: 429 });
});

test('local file sends feedback to loopback without retrying the submission', async () => {
  let requests = 0;
  const { api, timers } = createAPI(async (url, options) => {
    requests++;
    assert.equal(url, 'http://127.0.0.1:8000/feedback');
    assert.equal(options.method, 'POST');
    assert.equal(JSON.parse(options.body).text, 'Текст');
    return new Response(JSON.stringify({ sent: true }));
  }, 'file:');
  const feedback = api.sendFeedback({ text: 'Текст' });
  const [timer] = timers.values();
  assert.equal(timer.ms, 20000);
  assert.deepEqual(await feedback, { sent: true });
  assert.equal(requests, 1);
  assert.equal(timers.size, 0);
});
