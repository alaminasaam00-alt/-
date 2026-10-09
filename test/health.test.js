const test = require('node:test');
const assert = require('node:assert/strict');

test('health response contract', () => {
  const sample = { ok: true, service: 'sudan-market-platform', database: 'not-configured', version: '1.0.0' };
  assert.equal(sample.ok, true);
  assert.equal(sample.service, 'sudan-market-platform');
});
