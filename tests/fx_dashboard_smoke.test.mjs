import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { Script } from 'node:vm';

const page = fs.readFileSync('docs/index.html', 'utf8');
const feed = JSON.parse(fs.readFileSync('docs/fx-feed.json', 'utf8'));
const embedded = page.match(/<script>([\s\S]*?)<\/script>/);
test('public payload fits monitoring budget and retains authorised conditional setups', () => {
  assert.equal(Object.hasOwn(feed.pairs,"GBP_ZAR"), false, "broker-unavailable GBP/ZAR must not appear in public pairs");
  assert.ok(feed.priorities.every(s=>s.pair!=="GBP_ZAR"),"No GBP/ZAR ranked watchlist item");
  assert.ok(feed.signals.every(s=>s.instrument!=="GBP_ZAR"),"No GBP/ZAR signal");
  assert.ok(feed.research_setups.every(s=>s.instrument!=="GBP_ZAR"),"No GBP/ZAR research plan");
  assert.ok((feed.hourly?.signals||[]).every(s=>(s.pair||s.instrument)!=="GBP_ZAR"),"No hourly GBP/ZAR alert");
  const raw = fs.readFileSync('docs/fx-feed.json');
  assert.ok(raw.length < 950_000, 'public feed must remain below the hourly size ceiling');
  assert.ok(Array.isArray(feed.research_setups));
  const allowed = new Set(['schema','snapshot_at','news_at','published_at','status',
    'news_status','coverage','priorities','pairs','signals','research_setups',
    'hourly','sources','headlines','calendar','learning']);
  assert.ok(Object.keys(feed).every(k => allowed.has(k)), 'no unexpected fields');
  for (const item of feed.research_setups) {
    assert.equal(item.status, 'CONDITIONAL_RESEARCH_NOT_TRIGGERED');
    assert.equal(item.approved_entry, false);
  }
});
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
test('visual long/short cards fail closed and show entry stop TP1 and price-move percentages', () => {
  assert.match(page, /function renderPlans\(\)/);
  assert.match(page, /id="activePlan"/);
  assert.match(page, /Potential TP1 price move/);
  assert.doesNotMatch(page, /NET R:R|Net R:R at capped spread|Est\. net reward:risk/);
  assert.match(page, /safePlan=/);
  assert.match(page, /quoteFresh\&\&!stale\&\&!blackout/);
  assert.match(page, /WAIT FOR VERIFIED M15 CLOSE/);
  assert.match(page, /NO LIVE ENTRY/);
});
test('today main-assessment cards show only frozen priced plans and hourly performance', () => {
  assert.match(page, /Today.s monitored trades/);
  assert.match(page, /unpriced rankings excluded/);
  assert.match(page, /SCHEDULED_MAIN_ASSESSMENT/);
  assert.match(page, /id="paperScope"/);
  assert.match(page, /function renderPaperAudit\(\)/);
  assert.doesNotMatch(page, /AUTOMATIC RESEARCH WATCH/);
  assert.match(page, /Number\(t\.entry\) > 0/);
  assert.doesNotMatch(page, /id="paperRows"/);
  assert.doesNotMatch(page, /Net R:R|NET R:R|Result R/);
  const audit = feed.learning?.paper_audit;
  assert.ok(audit && Array.isArray(audit.candidates), 'paper-audit shortlist must exist');
  assert.ok(audit.candidates.length >= 10, 'preserve the original 10 Friday/Monday ideas');
  assert.ok(audit.candidates.every(c => c.tracking?.history?.length >= 1),
    'each registered shortlist idea must have a documented observed quote');
  assert.ok(audit.candidates.every(c => c.id && c.instrument && c.direction),
    'no unidentified candidate');
  assert.ok(audit.candidates.every(c => !Object.hasOwn(c,'net_r')),
    'user-facing feed must not contain R outcome metrics');
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
  assert.deepEqual(filenames.sort(), ['bookie-research.yml', 'fx-dashboard.yml']);
  assert.ok(filenames.every(name => !/crypto|trade-execution|paper-agent/i.test(name)));
});

test('separate Pepperstone demo evidence is accurate, attributed and never counted as an entry approval', () => {
  const outcomes = JSON.parse(fs.readFileSync('docs/trade-outcomes.json', 'utf8'));
  assert.equal(outcomes.schema, 1);
  assert.match(outcomes.account_type, /PEPPERSTONE/);
  assert.equal(outcomes.trades.length, 5);
  assert.equal(new Set(outcomes.trades.map(t => t.key)).size, 5);
  const closed = outcomes.trades.filter(t => t.status === 'CLOSED');
  const open = outcomes.trades.filter(t => t.status === 'OPEN_AT_SNAPSHOT');
  assert.equal(closed.length, 5);
  assert.equal(open.length, 0);
  assert.equal(Number(closed.reduce((s, t) => s + t.realised_pnl_gbp, 0).toFixed(2)), 134.19);
  assert.equal(outcomes.trades[2].prior_floating_snapshot.unrealised_pnl_gbp, 55.90);
  assert.equal(outcomes.account_snapshot.equity_gbp, 1117.24);
  assert.equal(outcomes.account_snapshot.used_margin_gbp, 0);
  assert.equal(outcomes.account_snapshot.open_positions, 0);
  assert.equal(Number((outcomes.trades[2].entry_price-outcomes.trades[2].exit_price)*100).toFixed(2), '43.00');
  assert.ok(outcomes.trades.every(t => t.signal_id === null && t.signal_match === 'PENDING'));
  assert.ok(outcomes.trades.every(t => ['USD_JPY','GBP_JPY','EUR_USD','GBP_USD'].includes(t.instrument)));
  assert.equal(outcomes.trades[3].realised_pnl_gbp, 8);
   const gbpUsd = outcomes.trades.find(t => t.key === '2026-10-26-gbpusd-closed-1358');
   assert.ok(gbpUsd);
   assert.equal(gbpUsd.entry_price, 1.33524);
   assert.equal(gbpUsd.exit_price, 1.33345);
   assert.equal(gbpUsd.realised_pnl_gbp, 8.95);
   assert.equal(gbpUsd.net_pnl_gbp, 8.95);
   assert.equal(gbpUsd.commission_gbp, 0);
   assert.equal(gbpUsd.swap_fees_gbp, 0);
  assert.equal(Object.hasOwn(feed, 'demo_trades'), false, 'research feed must remain unchanged');
  assert.match(page, /id="demoOutcomesPanel"/);
  assert.match(page, /id="outcomesRows"/);
  assert.match(page, /function renderOutcomes\(\)/);
  assert.match(page, /trade-outcomes\.json\?fresh=/);
  assert.match(page, /No strategy weights, win probabilities, or entry approvals are updated/);
});

test('setups report independent trend, observed price distance and completed-candle evidence', () => {
  assert.match(page, /function setupDiagnostics\(s,p\)/);
  assert.match(page, /Three independent checks/);
  assert.match(page, /1\. Direction/);
  assert.match(page, /2\. Price vs plan/);
  assert.match(page, /3\. Completed /);
  assert.match(page, /age<=5&&!stale/);
  assert.match(page, /Historical only; NOT a current entry check/);
  assert.match(page, /Historical candle only; NOT a current entry trigger/);
  assert.match(page, /rejection pattern OBSERVED/);
  assert.match(page, /continuation pattern OBSERVED/);
  assert.doesNotMatch(page, /Not verifiable with a recent quote/);
});

test('user-confirmed GBP ZAR Pepperstone exclusion is applied to every dashboard surface', () => {
  assert.match(page, /HIDDEN_PAIRS=new Set\(\["GBP_ZAR"\]\)/);
  assert.match(page, /feed\.research_setups:\[\]\)\.filter\(s=>visiblePair\(s\.instrument\)\)/);
  assert.match(page, /feed\.priorities\.filter\(r=>visiblePair\(r\.pair\)\)/);
  assert.match(page, /Object\.keys\(feed\.pairs\)\.filter\(visiblePair\)/);
  assert.match(page, /keys=Object\.keys\(feed\.pairs\)\.filter\(visiblePair\)/);
  assert.match(page, /!visiblePair\(pair\)/);
  assert.match(page, /visiblePair\(s\.instrument\)&&Date\.parse\(s\.expires_at\)/);
});
