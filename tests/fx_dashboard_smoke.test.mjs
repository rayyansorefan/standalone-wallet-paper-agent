import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { Script } from 'node:vm';

const page = fs.readFileSync('docs/index.html', 'utf8');
const feed = JSON.parse(fs.readFileSync('docs/fx-feed.json', 'utf8'));
const embedded = page.match(/<script>([\s\S]*?)<\/script>/);
test('published dashboard JavaScript parses', () => {
  assert.ok(embedded, 'dashboard must include an inline script');
  assert.doesNotThrow(() => new Script(embedded[1], { filename: 'fx-dashboard.js' }));
});
test('public feed schema and required research fields', () => {
  assert.equal(feed.schema, 1);
  assert.ok(Date.parse(feed.snapshot_at) > 0);
  assert.ok(feed.coverage.quoted > 0);
  assert.ok(Array.isArray(feed.signals));
  assert.ok(feed.pairs.GBP_USD.quote);
  assert.ok(!JSON.stringify(feed).includes('OANDA_ACCOUNT_ID'));
  assert.ok(!JSON.stringify(feed).includes('OANDA_API_TOKEN'));
});
test('all detailed pairs include usable numeric OHLC across available frames', () => {
  const deep = Object.entries(feed.pairs).filter(([_, p]) => p.deep);
  assert.ok(deep.length > 0, 'at least one detailed chart required');
  for (const [name, p] of deep) {
    for (const [tf, f] of Object.entries(p.frames)) {
      const candles = f.candles || [];
      assert.ok(candles.length >= 6, name + ' ' + tf + ': insufficient OHLC bars');
      for (const bar of candles) {
        const [o,h,l,c] = [bar.o,bar.h,bar.l,bar.c].map(Number);
        assert.ok([o,h,l,c].every(Number.isFinite), name + ' ' + tf + ': nonnumeric bar');
        assert.ok(l <= o && o <= h && l <= c && c <= h, name + ' ' + tf + ': inconsistent bar');
      }
    }
  }
});
test('UI converts OANDA numeric-string OHLC safely before plotting', () => {
  assert.match(page, /map\(c=>\(\{\.\.\.c,o:Number\(c\.o\),h:Number\(c\.h\),l:Number\(c\.l\),c:Number\(c\.c\)\}\)\)/);
  assert.match(page, /Date\.now\(\)-Date\.parse\(feed\.snapshot_at\)<4200000/);
  assert.match(page, /NO LIVE ENTRY/);
});
test('visual long/short cards fail closed and show entry stop TP1 and capped-spread reward risk', () => {
  assert.match(page, /function renderPlans\(\)/);
  assert.match(page, /id="activePlan"/);
  assert.match(page, /NET R:R|Net R:R at capped spread/);
  assert.match(page, /safePlan=/);
  assert.match(page, /quoteFresh\&\&!stale\&\&!blackout/);
  assert.match(page, /WAIT FOR VERIFIED M15 CLOSE/);
  assert.match(page, /NO LIVE ENTRY/);
});
test('top directional plans are displayed with labelled entry, stop, targets and fail-closed state', () => {
  assert.match(page, /id="researchCards"/);
  assert.match(page, /function renderResearchSetups\(\)/);
  assert.match(page, /Entry zone · OANDA/);
  assert.match(page, /Take-profit 1/);
  assert.match(page, /Take-profit 2/);
  assert.match(page, /CONDITIONAL · NOT TRIGGERED/);
  assert.match(page, /STALE · DO NOT TRADE/);
  assert.match(page, /Pepperstone availability/);
});
test('crypto trading UI and execution scripts absent', () => {
  assert.doesNotMatch(page, /trading engine at a glance|whale wallet|crypto futures/i);
  const filenames = fs.readdirSync('.github/workflows');
  assert.deepEqual(filenames, ['fx-dashboard.yml']);
});
