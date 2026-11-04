import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { Script } from 'node:vm';

const page = fs.readFileSync('docs/index.html', 'utf8');
const script = page.match(/<script>([\s\S]*?)<\/script>/)?.[1];

test('stale data and failed assessment cannot be portrayed as no market trades', () => {
  assert.ok(script);
  assert.doesNotThrow(() => new Script(script));
  assert.match(script, /\["OK","PARTIAL"\]\.includes\(feed\.status\)/);
  assert.match(script, /assessment_health\?\.status!==["']ASSESSMENT_UNAVAILABLE["']/);
  assert.match(script, /verdict["']\)\.textContent=stale\?["']⚪ ASSESSMENT UNAVAILABLE["']/);
  assert.match(script, /This is not evidence the market offered no trades/);
  assert.match(script, /ASSESSMENT UNAVAILABLE · NO ENTRY/);
  assert.match(script, /monitoredDecision\(scoutContext\)/);
});

test('research current scouts remain sorted by numeric priority with stable final ties', () => {
  assert.match(script, /Number\(b\.item\.priority_score\?\?b\.item\.priority\?\?-1\)/);
  assert.match(script, /Number\(a\.item\.priority_score\?\?a\.item\.priority\?\?-1\)/);
  assert.match(script, /a\.item\.instrument\.localeCompare\(b\.item\.instrument\)/);
  assert.match(script, /openMonitoredSetupPopup\(scoutContext\)/);
  assert.match(script, /Priority is a screening rank, NOT entry approval/);
});
