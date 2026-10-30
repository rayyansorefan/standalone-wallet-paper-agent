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
    'hourly','sources','headlines','calendar','learning','public_compaction','fast_entry_monitor']);
  assert.ok(Object.keys(feed).every(k => allowed.has(k)), 'no unexpected fields');
  for (const item of feed.research_setups) {
    assert.ok(['CONDITIONAL_RESEARCH_NOT_TRIGGERED',
      'EXTENDED_RETEST_PAPER_NOT_TRIGGERED'].includes(item.status),
      'paper retest is not an approved signal');
    assert.equal(item.approved_entry, false);
  }
});
test('published dashboard JavaScript parses', () => {
  assert.ok(embedded, 'dashboard must include an inline script');
  assert.doesNotThrow(() => new Script(embedded[1], { filename: 'fx-dashboard.js' }));
});
test('early-opportunity charts retain frozen entry, stop, target, start time and no-fill status', () => {
  assert.match(page, /id="early-opportunities"/);
  assert.match(page, /id="earlyGrid"/);
  assert.match(page, /function renderEarlyOpportunities\(\)/);
  assert.match(page, /id="earlySort"/);
  assert.match(page, /Highest potential/);
  assert.match(page, /id="earlyScope"/);
  assert.match(page, /function rankEarlyWatch\(t\)/);
  assert.match(page, /function primaryEarlyWatches\(rows\)/);
  assert.match(page, /const selected=primaryEarlyWatches\(scoped\)/);
  assert.match(page, /earlier version/);
  assert.match(page, /POTENTIAL UNRATED/);
  assert.match(page, /best_observed_pct/);
  assert.match(page, /FAST M5 ROUTE UNDER STUDY/);
  assert.match(page, /id="earlyEntryReview"/);
  assert.match(page, /function earlyCandidate\(instrument\)/);
  assert.match(page, /EARLY ENTRY ZONE/);
  assert.match(page, /WATCH START/);
  assert.match(page, /PAPER ONLY/);
  assert.match(page, /FAVOURABLE_MOVE_WITHOUT_VERIFIED_ENTRY/);
  assert.match(page, /historical price candles|historical price|M15 historical price candles/);
  assert.match(page, /renderEarlyOpportunities\(\);renderResearchSetups/);
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
  assert.match(page, /directional watches shown separately below/);
  assert.match(page, /const currentPlans = todayPlans.filter\(isCurrent\)/);
  assert.match(page, /function renderHourlyCohorts\(\)/);
  assert.match(page, /id="currentVisualStrip"/);
  assert.match(page, /id="paperArchive"/);
  assert.match(page, /id="paperHistory"/);
  assert.match(page, /id="hourlyCohortCards" class="current-watch-grid"/);
  assert.match(page, /current-watch-chart/);
  assert.match(page, /renderCards\(currentPlans\.slice\(\)\.sort\(/);
  assert.match(page, /historyHolder\.replaceChildren/);
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
  assert.match(page, /WATCH ONLY · NOT APPROVED/);
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
  assert.ok(outcomes.trades.length >= 5);
  assert.equal(new Set(outcomes.trades.map(t => t.key)).size, outcomes.trades.length);
  const closed = outcomes.trades.filter(t => t.status === 'CLOSED');
  const open = outcomes.trades.filter(t => t.status === 'OPEN_AT_SNAPSHOT');
  assert.ok(closed.length >= 5);
  assert.equal(closed.length + open.length, outcomes.trades.length);
  assert.equal(Number(outcomes.trades.slice(0, 5).reduce((s, t) => s + t.realised_pnl_gbp, 0).toFixed(2)), 134.19);
  assert.equal(outcomes.trades[2].prior_floating_snapshot.unrealised_pnl_gbp, 55.90);
  assert.ok(Number.isFinite(outcomes.account_snapshot.equity_gbp), 'published snapshot equity must be numeric');
  assert.ok(Number.isFinite(outcomes.account_snapshot.used_margin_gbp) && outcomes.account_snapshot.used_margin_gbp >= 0);
  assert.ok(Number.isInteger(outcomes.account_snapshot.open_positions) && outcomes.account_snapshot.open_positions >= 0);
  assert.equal(Number((outcomes.trades[2].entry_price-outcomes.trades[2].exit_price)*100).toFixed(2), '43.00');
  assert.ok(outcomes.trades.every(t => t.signal_match !== 'VERIFIED' || (typeof t.signal_id === 'string' && t.signal_id.length > 0)));
  assert.ok(outcomes.trades.every(t => /^[A-Z]{3}_[A-Z]{3}$/.test(t.instrument)));
  assert.equal(outcomes.trades[3].realised_pnl_gbp, 8);
   const gbpUsd = outcomes.trades.find(t => t.key === '2026-10-26-gbpusd-closed-1358');
   assert.ok(gbpUsd);
   assert.equal(gbpUsd.entry_price, 1.33524);
   assert.equal(gbpUsd.exit_price, 1.33345);
   assert.equal(gbpUsd.realised_pnl_gbp, 8.95);
   assert.equal(gbpUsd.net_pnl_gbp, 8.95);
   assert.equal(gbpUsd.commission_gbp, 0);
   assert.equal(gbpUsd.swap_fees_gbp, 0);
   const audLoss = outcomes.trades.find(t => t.key === '2026-10-26-audnzd-stop-1622');
   assert.ok(audLoss, 'closed AUD/NZD stop-loss evidence must be retained');
   assert.equal(audLoss.entry_price, 1.236);
   assert.equal(audLoss.exit_price, 1.2346);
   assert.equal(audLoss.realised_pnl_gbp, -7);
   assert.equal(audLoss.exit_reason, 'STOP_LOSS');
   assert.equal(audLoss.entry_classification, 'UNAPPROVED_RESEARCH_WATCH_EXECUTED');
   assert.equal(audLoss.execution_review.entry_deviation_pips, 4);
   const early = outcomes.trades.find(t => t.key === '2026-10-27-eurusd-closed-1739');
   assert.ok(early, '27 October EUR/USD close');
   assert.equal(early.entry_price, 1.1149);
   assert.equal(early.exit_price, 1.11408);
   assert.equal(early.realised_pnl_gbp, 9.02);
   assert.equal(early.signal_match, 'PENDING');
   assert.equal(outcomes.early_entry_study.original_plan_id, '20261027-1403-EURUSD-S-B03');
   assert.equal(outcomes.early_entry_study.planned_sell_retouch_observed_after_confirmation, false);
   assert.ok(outcomes.trades.length >= 7, 'new user-supplied evidence must not be silently dropped');
   assert.ok(closed.filter(t => t.realised_pnl_gbp > 0).length >= 6);
   assert.ok(closed.filter(t => t.realised_pnl_gbp < 0).length >= 1);
   assert.equal(Number(closed.slice(0, 7).reduce((s,t) => s + t.realised_pnl_gbp, 0).toFixed(2)), 136.21, 'original seven outcomes unchanged');
   assert.equal(Number(closed.filter(t => t.closed_at?.startsWith('2026-10-26')).reduce((s,t) => s + t.realised_pnl_gbp, 0).toFixed(2)), 9.95);
   assert.match(page, /id="todayNetPnl"/);
   assert.match(page, /id="closedRecord"/);
   assert.match(page, /Tracking began · /);
   assert.match(page, /Chart window: /);
   assert.match(page, /audit-chart-age/);

   assert.match(page, /LOSS REVIEW/);
   assert.match(page, /ANALYSIS GOOD\/RISKY\/MIXED/);
   assert.match(page, /ANALYSIS /);
   assert.match(page, /AVOID THIS TRADE/);
   assert.match(page, /M15 TRIGGER · CHECK BROKER/);
   assert.match(page, /CHECK STALE · NO ENTRY/);


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

 test('watch models cannot be labelled as approved conditional signals', () => {
  assert.match(page, /Technical watches · not approved/);
  assert.match(page, /WATCH-ONLY MODELS/);
  assert.doesNotMatch(page, /CURRENT CONDITIONAL PLANS/);
  assert.doesNotMatch(page, /M15 pullback with H1\/H4\/D1 trend alignment/);
 });

test('fast research and export-compaction metadata cannot imply delivery or broker execution', () => {
  const fast = feed.fast_entry_monitor;
  if (fast) {
    assert.equal(fast.research_only, true);
    assert.equal(fast.manual_pepperstone_check_required, true);
    assert.equal(fast.user_delivery_verified, false);
    assert.ok(Array.isArray(fast.observations));
    for (const row of fast.observations) {
      assert.equal(row.user_delivery_verified, false);
      assert.equal(row.requires_manual_pepperstone_check, true);
    }
  }
  if (feed.public_compaction) {
    assert.equal(feed.public_compaction.optional_pattern_details_omitted, true);
    for (const pair of Object.values(feed.pairs)) {
      for (const frame of Object.values(pair.frames)) {
        assert.ok(frame.candles.length >= 6);
        assert.ok(Number.isFinite(frame.indicators.ema20));
      }
    }
  }
});

test('monitored FX plan and directional watch ratings reuse priced early-opportunity logic without invented scores', () => {
  const helper=page.match(/function directionalTechnicalPotential\(t\)\{[\s\S]*?(?=function renderEarlyOpportunities)/)?.[0];
  assert.ok(helper, 'shared opportunity rating helper exists');
  const context = {
    stale:false,
    feed:{learning:{opportunity_audit:{recent:[{
      instrument:'EUR_USD',direction:'LONG',first_seen_at:'2026-10-29T08:00:00Z',
      expires_at:'2999-01-01T00:00:00Z',entry_low:1.10,entry_high:1.11,stop:1.09,tp1:1.14
    }]}},pairs:{USD_CAD:{
      quote:{time:new Date().toISOString(),tradeable:true,bid:1.3900,ask:1.3901,pip_size:.0001,spread_pips:1},
      frames:{M15:{indicators:{atr14:.001,ema20:1.3899,ema50:1.3890,
        plus_di14:23,minus_di14:14,macd_12_26_9:{histogram:.0001}}},
        H1:{indicators:{ema20:1.3898,ema50:1.3891,plus_di14:24,
          minus_di14:15,adx14:23,macd_12_26_9:{histogram:.0001}}}}
    }}},
    rankEarlyWatch: t => ({score:71,label:'HIGH POTENTIAL',reason:'priced structural test',priced:t})
  };
  new Script(helper+';this.probePotential=watchPotential;').runInNewContext(context);
  assert.equal(context.probePotential({instrument:'EUR_USD',direction:'LONG'}).score,71);
  const unpriced=context.probePotential({instrument:'USD_CAD',direction:'LONG'});
  assert.equal(unpriced.label,'TECHNICAL WATCH · NOT PRICED');
  assert.ok(unpriced.score>=0&&unpriced.score<=69);
  assert.match(unpriced.reason,/NO PRICED ENTRY\/STOP\/TARGET/);
  assert.equal(context.probePotential({instrument:'EUR_JPY',direction:'SHORT'}).score,null,
    'unpriced watch without fresh evidence must remain unrated');
  const direct=context.probePotential({instrument:'GBP_USD',direction:'SHORT',
    entry:1.30,stop:1.31,tp1:1.28});
  assert.equal(direct.priced.entry_low,1.30);
  assert.equal(direct.priced.entry_high,1.30);
  assert.match(page,/function renderCurrentScouts\(\)[\s\S]*?action\.append\(open\)/);
  assert.match(page,/function renderHourlyCohorts\(\)[\s\S]*?card\.append\(head,watchPotentialLine\(t\)\)/);
  assert.match(page,/function renderPaperAudit\(\)[\s\S]*?card\.append\(head,watchPotentialLine\(t\),make\("p","Assessed/);
  assert.match(page,/Heuristic, not entry approval or win probability/);
});

test('priced potential rating does not reward hindsight directional movement', () => {
  const helper=page.match(/function rankEarlyWatch\(t\)\{[\s\S]*?(?=function directionalTechnicalPotential)/)?.[0];
  assert.ok(helper);
  const context={stale:false,feed:{pairs:{GBP_USD:{
    quote:{time:new Date().toISOString(),tradeable:true,bid:1.3000,ask:1.3001,
      pip_size:.0001,spread_pips:1},
    frames:{M15:{indicators:{atr14:.001,ema20:1.2998,ema50:1.2980,
      plus_di14:25,minus_di14:15,macd_12_26_9:{histogram:.001}}},
      H1:{indicators:{ema20:1.2990,ema50:1.2975,plus_di14:26,minus_di14:14,
        macd_12_26_9:{histogram:.001}}}}
  }}}};
  new Script(helper+';this.probeRank=rankEarlyWatch;').runInNewContext(context);
  const plan={instrument:'GBP_USD',direction:'LONG',entry_low:1.3001,entry_high:1.3002,
    stop:1.2985,tp1:1.3040};
  const positive=context.probeRank({...plan,hypothetical_move_pct:9});
  const negative=context.probeRank({...plan,hypothetical_move_pct:-9});
  assert.ok(positive.score!=null);
  assert.equal(positive.score,negative.score,
    'later directional movement must not change a contemporaneous setup score');
});


test('today monitored trade and hourly watch cards offer honest, independent sorting', () => {
  assert.match(page, /id="hourlyCohortSort"/);
  assert.match(page, /id="paperSort"/);
  assert.match(page, /Highest setup rating/);
  assert.match(page, /Best tracked move · not P\/L/);
  assert.match(page, /Latest analysis/);
  assert.match(page, /function compareMonitored\(a,b,sort\)/);
  assert.match(page, /watchPotential\(t\)\.score/);
  assert.match(page, /tracking\?\.move_pct/);
  assert.match(page, /scope\.onchange=renderHourlyCohorts;/);
  assert.match(page, /sort\.onchange=renderHourlyCohorts;/);
  assert.match(page, /el\("paperSort"\)\.onchange=renderPaperAudit;/);
  assert.match(page, /compareMonitored\(a,b,el\("paperSort"\)\.value\)/);
  assert.match(page, /card\.append\(head,watchPotentialLine\(t\)/);
  assert.match(page, /card\.append\(head\);[\s\S]*?card\.append\(head,watchPotentialLine/);
});


test('best tracked move sort uses the same frozen baseline and current exit-side price shown on cards', () => {
  const helper=page.match(/function compareMonitored\(a,b,sort\)\{[\s\S]*?(?=function renderHourlyCohorts)/)?.[0];
  assert.ok(helper);
  const now=new Date().toISOString();
  const good={instrument:'EUR_USD',direction:'LONG',created_at:now,
    tracking:{reference_price:1.10,move_pct:-20}};
  const bad={instrument:'GBP_USD',direction:'LONG',created_at:now,
    tracking:{reference_price:1.20,move_pct:20}};
  const context={feed:{pairs:{
    EUR_USD:{quote:{time:now,bid:1.11,ask:1.1102}},
    GBP_USD:{quote:{time:now,bid:1.19,ask:1.1902}}
  },learning:{paper_audit:{candidates:[]}}},watchPotential:t=>({score:t.instrument==='GBP_USD'?80:40})};
  new Script(helper+';this.compareMonitored=compareMonitored;').runInNewContext(context);
  assert.ok(context.compareMonitored(good,bad,'PERFORMANCE')<0,
    'live observed +0.91% must beat -0.83%, irrespective of stale tracker percentages');
  assert.ok(context.compareMonitored(good,bad,'POTENTIAL')>0,
    'prospective rating must remain independent from observed price movement');
});


test('monitored popups present a decision, not generated entry prices', () => {
  assert.match(page, /function buildMonitoredScenario\(t\)/);
  assert.match(page, /function monitoredDecision\(t\)/);
  assert.match(page, /function monitoredSetupPanel\(t\)/);
  assert.match(page, /No original priced entry\/stop\/target plan was admitted/);
  assert.match(page, /No trade on this pair/);
  assert.match(page, /YOUR ACTION:/);
  assert.match(page, /ENTRY.*PROVISIONAL/);
  assert.match(page, /STOP/);
  assert.match(page, /TARGET/);
  assert.match(page, /\.monitored-setup-dialog \.monitored-setup-panel/);
  assert.match(page, /grossRR>=1\.50&&s\.netRR>=1\.35/);
});

test('a short directional watch with no frozen plan cannot invent entry, stop or TP', () => {
  const helper=page.match(/function buildMonitoredScenario\(t\)\{[\s\S]*?(?=function openMonitoredSetupPopup)/)?.[0];
  assert.ok(helper);
  const now=Date.now(),floor=Math.floor(now/900000)*900000;
  const bars=[60,45,30].map((mins,i)=>({
    t:new Date(floor-mins*60000).toISOString(),
    o:11.051-i*.007,h:11.052-i*.007,
    l:11.045-i*.007,c:11.047-i*.007
  }));
  const context={feed:{news_status:'PARTIAL',calendar:[],pairs:{EUR_SEK:{
    quote:{time:new Date(now).toISOString(),bid:11.0235,ask:11.0267,
      pip_size:.0001,spread_pips:32,tradeable:true},
    frames:{M15:{indicators:{ema20:11.04352,atr14:.00483},candles:bars},
      H1:{indicators:{adx14:52}}}
  }}}};
  new Script(helper+';this.scenario=buildMonitoredScenario;').runInNewContext(context);
  const scenario=context.scenario({instrument:'EUR_SEK',direction:'SHORT',created_at:new Date(now).toISOString()});
  assert.equal(scenario.status,'NO PRICED SIGNAL');
  assert.equal(scenario.route,'NONE');
  assert.equal(scenario.entry,null);
  assert.equal(scenario.stop,null);
  assert.equal(scenario.tp1,null);
  assert.equal(scenario.spreadPips,32);
});

test('incomplete watched pair cannot fabricate a priced setup', () => {
  const helper=page.match(/function buildMonitoredScenario\(t\)\{[\s\S]*?(?=function monitoredSetupPanel)/)?.[0];
  assert.ok(helper);
  const context={feed:{pairs:{EUR_USD:{quote:{tradeable:true,bid:1.1,ask:1.1001},frames:{}}}}};
  new Script(helper+';this.scenario=buildMonitoredScenario;').runInNewContext(context);
  const s=context.scenario({instrument:'EUR_USD',direction:'LONG'});
  assert.equal(s.route,'NONE');
  assert.equal(s.entry,null);
  assert.equal(s.stop,null);
  assert.equal(s.tp1,null);
});

test('monitored setup opens a real keyboard-dismissable modal on tap, without approving a trade', () => {
  assert.match(page, /function openMonitoredSetupPopup\(t\)/);
  assert.match(page, /open\.type="button"/);
  assert.match(page, /open\.setAttribute\("aria-label","Open "\+name\.replace/);
  assert.match(page, /open\.addEventListener\("click",\(\)=>openMonitoredSetupPopup\(scoutContext\)/);
  assert.match(page, /const researchByPair=new Map/);
  assert.match(page, /const scenario=fresh\?buildMonitoredScenario\(scoutContext\):null/);
  assert.match(page, /scout_plan:plan&&fresh\?plan:null/);
  assert.match(page, /const dialog=make\("dialog",undefined,"monitored-setup-dialog"\)/);
  assert.match(page, /dialog\.showModal\(\)/);
  assert.match(page, /close\.addEventListener\("click",\(\)=>dialog\.close\(\)\)/);
  assert.match(page, /dialog\.addEventListener\("close",\(\)=>dialog\.remove\(\)/);
  assert.match(page, /const detail=monitoredSetupPanel\(t\)/);
  assert.match(page, /\.monitored-setup-dialog::backdrop/);
  assert.match(page, /VIEW SIMPLE TRADE RECOMMENDATION/);
  assert.match(page, /WATCH — WAIT/);
  assert.match(page, /SKIP .*NO TRADE/);
});

test('extended GBP/USD BUY is a non-chasing retest watch with frozen source levels', () => {
  assert.match(page, /EXTENDED_WAIT_RETEST:"🟠 RETEST ONLY · NOT APPROVED"/);
  assert.match(page, /BREAKOUT_OBSERVED_REVIEW:"🟡 BREAKOUT SEEN · REVIEW"/);
  assert.match(page, /NEXT ACTION:/);
  assert.match(page, /scout_phase:item.entry_phase/);
  const helper=page.match(/function buildMonitoredScenario\(t\)\{[\s\S]*?(?=function monitoredSetupPanel)/)?.[0];
  assert.ok(helper);
  const now=Date.now();
  const context={feed:{pairs:{GBP_USD:{quote:{
    tradeable:true,bid:1.34051,ask:1.34065,time:new Date(now).toISOString(),
    pip_size:.0001,spread_pips:1.4},frames:{M15:{indicators:{atr14:.00068,ema20:1.33939}}}}}}};
  new Script(helper+';this.scenario=buildMonitoredScenario;').runInNewContext(context);
  const s=context.scenario({instrument:'GBP_USD',direction:'LONG',
    created_at:new Date(now).toISOString(),
    scout_action:'WAIT FOR NEW M15 EMA20 RETEST',
    scout_plan:{requires_future_retest:true,source_quote_at:new Date(now).toISOString(),
      entry_zone_low:1.33929,entry_zone_high:1.33949,
      stop:1.33883,tp1:1.34074,net_rr_estimate:1.39,
      trigger_rule:'A FUTURE completed M15 bullish retest is required'}});
  assert.equal(s.status,'RETEST PENDING · NOT APPROVED');
  assert.equal(s.route,'M15 EMA20 RETEST · PAPER');
  assert.equal(s.entryZoneLow,1.33929);
  assert.equal(s.stop,1.33883);
  assert.equal(s.tp1,1.34074);
  assert.equal(s.netRR,1.39);
  assert.ok(s.reasons.some(x=>/WAIT FOR NEW M15/.test(x)));
  assert.equal(s.trigger,null);
});

test('single FX desk decision shows green only for a fresh canonical confirmed trigger', () => {
  const helper=page.match(/function renderFastEntry\(\)\{[\s\S]*?(?=function renderPlans)/)?.[0];
  assert.ok(helper,'decision renderer present');
  const now=Date.now(),iso=m=>new Date(now+m*60000).toISOString();
  const plan={id:'CANONICAL',instrument:'GBP_USD',direction:'LONG',
    created_at:iso(-10),expires_at:iso(45),planned_entry:1.34,
    stop:1.338,tp1:1.345,net_rr_at_spread_cap:1.7};
  const event={id:'CANONICAL',pair:'GBP_USD',direction:'LONG',
    entry:1.34,stop:1.338,tp1:1.345,expires_at:iso(45),
    status:'PRICE_REASSESSMENT_ALERT_READY',alert_detected_at:iso(-2)};
  const pair={quote:{time:iso(-1),tradeable:true,spread_pips:1.2}};
  function run({eventRow=event,planRow=plan,quote=pair.quote,age=2,freshness='CURRENT',stale=false}={}){
    const nodes={};
    const make=(tag,value,cls)=>({tag,textContent:value,className:cls,style:{},children:[],
      append(...parts){this.children.push(...parts)}});
    const el=k=>nodes[k]||(nodes[k]={textContent:'',children:[],
      replaceChildren(...parts){this.children=parts},
      append(...parts){this.children.push(...parts)},
      classList:{remove(){},add(){}}});
    const ctx={el,make,stale,visiblePair:p=>p!=='GBP_ZAR',money:x=>String(x),uk:x=>x,n:x=>String(x),
      feed:{fast_entry_monitor:{freshness,checked_at:iso(-age),
        observations:eventRow?[eventRow]:[]},
        signals:planRow?[planRow]:[],news_status:'OK',pairs:{GBP_USD:{quote}}}};
    new Script(helper+';this.render=renderFastEntry;').runInNewContext(ctx);
    ctx.render();
    return {headline:nodes.fastEntryHeadline.textContent,cards:nodes.fastEntryCards.children};
  }
  assert.match(run().headline,/GREEN/);
  assert.equal(run().cards.length,1);
  assert.match(run({eventRow:null}).headline,/AMBER/);
  assert.match(run({eventRow:null,planRow:null}).headline,/RED/);
  assert.doesNotMatch(run({age:25}).headline,/GREEN/);
  assert.doesNotMatch(run({freshness:'STALE'}).headline,/GREEN/);
  assert.doesNotMatch(run({quote:{...pair.quote,time:iso(-10)}}).headline,/GREEN/);
  assert.doesNotMatch(run({eventRow:{...event,id:'UNREGISTERED'}}).headline,/GREEN/);
  assert.doesNotMatch(run({stale:true}).headline,/GREEN/);
  assert.doesNotMatch(run({eventRow:{...event,expires_at:iso(-1)}}).headline,/GREEN/);
});

test('scout setup popup uses the original priced paper preview instead of silently repricing it', () => {
  const helper=page.match(/function buildMonitoredScenario\(t\)\{[\s\S]*?(?=function monitoredSetupPanel)/)?.[0];
  assert.ok(helper);
  const now=Date.now();
  const context={feed:{pairs:{USD_MXN:{quote:{
    tradeable:true,bid:18.7851,ask:18.7928,time:new Date(now).toISOString(),
    pip_size:.0001,spread_pips:77},frames:{M15:{indicators:{atr14:.042,ema20:18.78}}}}}}};
  new Script(helper+';this.scenario=buildMonitoredScenario;').runInNewContext(context);
  const s=context.scenario({instrument:'USD_MXN',direction:'LONG',
    created_at:new Date(now).toISOString(),scout_reference_rule:'New M15 close required',
    scout_plan:{entry_zone_low:18.77,entry_zone_high:18.78,stop:18.71,tp1:18.86}});
  assert.equal(s.route,'SCOUT PROVISIONAL PLAN');
  assert.equal(s.status,'PAPER WATCH · NOT APPROVED');
  assert.equal(s.entryZoneLow,18.77);
  assert.equal(s.tp1,18.86);
  assert.ok(Number.isFinite(s.netRR),'priced scout must show calculated net RR');
  assert.ok(Number.isFinite(Date.parse(s.expiry)),'priced scout must show expiry');
  assert.match(s.reasons.join(' '),/New M15 close required/);
});
