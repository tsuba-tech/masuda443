const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const context = vm.createContext({});
vm.runInContext(fs.readFileSync('app.js', 'utf8').replace(/init\(\);\s*$/, ''), context);
const estimate = (pa, target, played, remaining) => context.qualificationOutlook({
  masuda: { pa }, target_pa: target, team: { games_played: played, remaining_games: remaining },
});
test('Poisson tail agrees with closed form for one required PA', () => {
  assert.ok(Math.abs(estimate(2, 3, 2, 1).probability - (1 - Math.exp(-1))) < 1e-12);
});
test('reached, season ended, and missing data are distinct', () => {
  assert.equal(estimate(443, 443, 143, 0).probability, 1);
  assert.equal(estimate(392, 443, 143, 0).probability, 0);
  assert.equal(estimate(0, 443, 129, 14).probability, 0);
  assert.equal(estimate(392, 443, undefined, 14), null);
});
test('more remaining games improve the chance; higher target reduces it', () => {
  const base = estimate(392, 443, 129, 14).probability;
  assert.ok(base > 0 && base < 1);
  assert.ok(estimate(392, 443, 129, 15).probability > base);
  assert.ok(estimate(392, 444, 129, 14).probability < base);
});
