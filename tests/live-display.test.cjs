const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const context = vm.createContext({ structuredClone, Intl, Date });
vm.runInContext(fs.readFileSync('app.js', 'utf8').replace(/init\(\);\s*$/, ''), context);
test('live date switches at midnight JST regardless of viewer timezone', () => {
  const live = { date: '2026-10-04' };
  assert.equal(context.liveDateLabel(live, new Date('2026-10-04T14:59:59Z')), '本日');
  assert.equal(context.liveDateLabel(live, new Date('2026-10-04T15:00:00Z')), '10/04');
});
test('other pages updating cannot remove an unconfirmed live PA', () => {
  const data = JSON.parse(fs.readFileSync('data.json', 'utf8'));
  data.source.last_modified = '2026-10-05T08:00:00+09:00';
  data.source.masuda_last_modified = '2026-10-03T22:18:04+09:00';
  const live = { date: '2026-10-04', totals: { pa: 1, ab: 0, hits: 0, hr: 0 } };
  const result = context.mergeLiveOverlay(data, live);
  assert.equal(result.data.masuda.pa, data.masuda.pa + 1);
  assert.equal(result.live, live);
  assert.equal(data.masuda.pa, result.data.masuda.pa - 1);
  data.source.masuda_last_modified = '2026-10-05T08:00:00+09:00';
  assert.equal(context.mergeLiveOverlay(data, live).live, null);
});
