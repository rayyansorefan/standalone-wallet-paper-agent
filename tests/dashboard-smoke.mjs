// Browser-free functional smoke tests: no third-party dependencies or live APIs.
import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";

const html=fs.readFileSync("docs/index.html","utf8");
const feed=JSON.parse(fs.readFileSync("docs/fx-feed.json","utf8"));
const evidence=JSON.parse(fs.readFileSync("docs/trade-outcomes.json","utf8"));
assert.equal(feed.schema,1);
feed.research_setups=[{instrument:"EUR_JPY",direction:"SHORT",status:"CONDITIONAL_RESEARCH_NOT_TRIGGERED",entry_low:175.86,entry_high:175.94,stop:176.28,tp1:175.25,tp2:175.03,net_rr_estimate:1.47,source_quote_at:feed.snapshot_at,technical_checks_agree:5,timeframes_aligned:["M15","H1","H4","D"],trigger:"Wait for a completed M15 bearish rejection."}];
feed.research_setups.push({...feed.research_setups[0],instrument:"GBP_ZAR"}); // Simulate next publisher reintroducing the excluded symbol.
feed.signals.push({instrument:"GBP_ZAR",direction:"LONG",expires_at:new Date(Date.parse(feed.snapshot_at)+3600000).toISOString()});

feed.learning.opportunity_audit={updated_at:feed.snapshot_at,recent:[{
  id:"SMOKE-GBPUSD-EARLY-L",instrument:"GBP_USD",direction:"LONG",route:"EMA20_PULLBACK",
  first_seen_at:feed.snapshot_at,
  latest_quote_at:feed.snapshot_at,
  expires_at:new Date(Date.parse(feed.snapshot_at)+4*3600000).toISOString(),
  entry_low:1.33230,entry_high:1.33246,stop:1.33095,tp1:1.33550,tp2:1.3360,
  hypothetical_move_pct:0.04,
  tracking_status:"WATCH_ONLY_UNTRIGGERED",entry_confirmed:false,scored:false
}]};
const script=html.split("<script>")[1]?.split("</script>")[0];
assert.ok(script, "Dashboard JavaScript is present");
new vm.Script(script);

const saved={};
class MockNode{
  constructor(tag,id){this.tagName=tag;this.id=id;this.children=[];this.listeners={};this.textContent="";this.value="";this.className="";this.style={};this.attributes={};this.options=[];this.disabled=false;this.classList={add:(...items)=>{this.className=[...new Set([this.className,...items].filter(Boolean))].join(" ")},remove:(...items)=>{this.className=this.className.split(" ").filter(x=>!items.includes(x)).join(" ")}};}
  append(...elems){this.children.push(...elems);if(this.tagName==="select")this.options=this.children;return this}
  replaceChildren(...elems){this.children=elems;if(this.tagName==="select")this.options=this.children}
  addEventListener(event,handler){this.listeners[event]=handler}
  setAttribute(key,value){this.attributes[key]=value}
  scrollIntoView(){}
}
const ids=[...html.matchAll(/id="([^"]+)"/g)].map(x=>x[1]);
const map=new Map(ids.map(id=>[id,new MockNode(["pair","journalPair","outcome"].includes(id)?"select":"div",id)]));
const doc={
  getElementById:id=>map.get(id),
  createElement:tag=>new MockNode(tag),
  createElementNS:(ns,tag)=>new MockNode(tag),
};
const at={now:Date.parse(feed.snapshot_at)+30*60*1000};
class TestDate extends Date{
  constructor(...args){super(...(args.length?args:[at.now]))}
  static now(){return at.now}
}
const timers=[];
const localStorage={getItem:key=>saved[key]??null,setItem:(key,val)=>saved[key]=val};
const ctx={document:doc,Date:TestDate,Intl,Number,String,Math,Object,Array,URL,Promise,
  localStorage,console,fetch:async url=>({ok:true,json:async()=>(String(url).includes("trade-outcomes.json")?evidence:feed)}),
  setInterval:(fn)=>timers.push(fn)};
vm.runInNewContext(script,ctx);
await new Promise(resolve=>setImmediate(resolve));
const $=id=>map.get(id);
assert.equal($("screened").textContent,String(Object.keys(feed.pairs).filter(k=>k!=="GBP_ZAR").length));
const closedEvidence = evidence.trades.filter(t => t.status === "CLOSED");
const displayedRealised = closedEvidence.reduce((sum,t) => sum + t.realised_pnl_gbp, 0);
assert.equal($("completedCount").textContent,closedEvidence.length+" trades");
assert.equal($("realisedPnl").textContent,(displayedRealised>=0?"+":"−")+"£"+Math.abs(displayedRealised).toFixed(2));
const todayEvidence = closedEvidence.filter(t => t.closed_at?.startsWith(evidence.as_of.slice(0,10)));
const todayProfit = todayEvidence.reduce((sum,t) => sum + t.realised_pnl_gbp, 0);
assert.equal($("todayNetPnl").textContent,(todayProfit>=0?"+":"−")+"£"+Math.abs(todayProfit).toFixed(2));
const smokeLosses=closedEvidence.filter(t=>t.realised_pnl_gbp<0).length;
assert.equal($("closedRecord").textContent,closedEvidence.filter(t=>t.realised_pnl_gbp>0).length+" wins / "+smokeLosses+" loss"+(smokeLosses===1?"":"es"));
assert.equal($("outcomesRows").children.length,evidence.trades.length);
assert.match($("outcomesLearning").textContent,/PENDING/);
assert.equal($("rows").children.length,Object.keys(feed.pairs).filter(k=>k!=="GBP_ZAR").length);
assert.equal($("picks").children.length,Math.min(4,feed.priorities.filter(x=>x.pair!=="GBP_ZAR").length));
assert.equal($("researchCards").children.length,1,"A conditional setup must have its own level card even with zero approved signals");
assert.match($("researchCards").children[0].className,/setupcard/);
const diag=JSON.stringify($("researchCards").children[0].children);
assert.match(diag,/1\. Direction/);
assert.match(diag,/2\. Price vs plan/);
assert.match(diag,/3\. Completed M15 candle/);
assert.match(diag,/Historical only|inside zone|outside the planned|pips ABOVE|pips BELOW/i);
assert.ok(!$("pair").options.some(o=>o.value==="GBP_ZAR"),"Excluded pair must not be chart selectable");
assert.ok(!$("journalPair").options.some(o=>o.value==="GBP_ZAR"),"Excluded pair must not be in personal journal selector");
assert.ok(!$("rows").children.some(row=>row.children.some(c=>c.textContent==="GBP/ZAR")),"Excluded pair must not be in scanner");
assert.ok(!$("picks").children.some(card=>JSON.stringify(card.children).includes("GBP/ZAR")),"Excluded pair must not be a priority card");
assert.ok($("chart").children.length>30,"Completed candlesticks should render");
assert.equal($("earlyGrid").children.length,1,"Early opportunity card must render from prospective feed data");
assert.ok($("scoutGrid").children.length>=5,
  "Fresh research scouts must remain visible alongside live or expired watches");
const firstScout=$("scoutGrid").children[0];
assert.match(JSON.stringify(firstScout.children),/TECHNICAL WATCH|POTENTIAL UNRATED/);
assert.match(JSON.stringify(firstScout.children),/Entry zone/);
assert.match(JSON.stringify(firstScout.children),/Stop \/ target/);
assert.match(JSON.stringify(firstScout.children),/NOT PRICED|INCOMPLETE|PAPER-ONLY/,
  "Every scout shows priced research levels or an explicit reason they cannot be priced");
const earlyCard=$("earlyGrid").children[0];
assert.match(JSON.stringify(earlyCard.children),/GBP\/USD/);
assert.match(JSON.stringify(earlyCard.children),/Entry zone/);
assert.match(JSON.stringify(earlyCard.children),/Stop \/ invalidation/);
assert.match(JSON.stringify(earlyCard.children),/Target 1/);
assert.match(JSON.stringify(earlyCard.children),/Started/);
// A later recalibration must supersede the displayed plan for its currency pair.
// Prior levels remain in a collapsed audit, never at another top rank.
const older=feed.learning.opportunity_audit.recent[0];
const newest={...older,id:"SMOKE-GBPUSD-RECALIBRATED",
  first_seen_at:new Date(Date.parse(feed.snapshot_at)+10*60*1000).toISOString(),
  entry_low:1.33250,entry_high:1.33260};
feed.learning.opportunity_audit.recent.push(newest);
vm.runInNewContext("renderEarlyOpportunities()",ctx);
assert.equal($("earlyGrid").children.length,1,"One primary visible watch per currency pair");
const currentCard=JSON.stringify($("earlyGrid").children[0].children);
assert.match(currentCard,/1\.33250/,"Newest GBP\/USD zone is displayed as the primary");
assert.match(currentCard,/earlier version/,"Earlier watch remains available only in audit details");
feed.learning.opportunity_audit.recent.pop();
vm.runInNewContext("renderEarlyOpportunities()",ctx);
const chartAction=earlyCard.children.at(-1).children.at(-1);
chartAction.listeners.click();
assert.match($("chartTime").textContent,/EARLY WATCH since/);
assert.match($("chartFoot").textContent,/EARLY WATCH/);
assert.match(JSON.stringify($("chart").children),/EARLY ENTRY ZONE/);
assert.equal($("currentVisualStrip").children.length,3,
  "Dashboard must present current research counts ahead of archived plans");
assert.ok($("hourlyCohortCards").children.length>=1,
  "Timestamped hourly watches must render as separate graphical cards");
let visualCard=$("hourlyCohortCards").children[0];
// The simulated clock is 30 minutes after the real snapshot. Near midnight
// this is legitimately the next London day: empty TODAY is correct, while
// archived observations must still render when explicitly selected.
if(visualCard.className==="setupempty"){
  const londonDay=t=>new Intl.DateTimeFormat("en-GB",{timeZone:"Europe/London",year:"numeric",month:"2-digit",day:"2-digit"}).format(new Date(t));
  const currentDayRows=feed.learning.paper_audit.candidates.filter(t=>
    t.source==="AUTOMATED_RESEARCH_PRIORITY"&&t.instrument!=="GBP_ZAR"&&
    londonDay(t.created_at)===londonDay(at.now));
  assert.equal(currentDayRows.length,0,"A non-empty current cohort must never disappear");
  assert.match(visualCard.textContent,/No timestamped research observations/,
    "Empty current-day state must be explicit, without fabricating watches");
  $("hourlyCohortScope").value="ALL";
  $("hourlyCohortScope").onchange();
  visualCard=$("hourlyCohortCards").children[0];
}
assert.match(visualCard.className,/current-watch-card/);
assert.ok(visualCard.children.some(c=>c.tagName==="svg"&&c.attributes?.class==="current-watch-chart"),
  "Each hourly card must include an SVG chart");
const completedM15=visualCard.children.find(c=>c.tagName==="svg"&&c.attributes?.class==="current-watch-chart");
assert.ok(completedM15.children.some(c=>c.tagName==="path")||
  completedM15.children.filter(c=>c.tagName==="rect").length>=6,
  "Watched-price history must render as a movement line, or historical candles if fewer than 2 observations exist");
assert.ok(visualCard.children.some(c=>String(c.className).includes("current-watch-start")&&
  c.children.some(n=>String(n.textContent).startsWith("WATCH STARTED "))),
  "Every hourly visual card must show original watch start time and elapsed age");
const cad=$("hourlyCohortCards").children.find(c=>
  c.children.some(n=>n.tagName==="div"&&n.children.some(z=>z.textContent==="CAD/CHF")));
if(cad){
  // The public detailed window rolls forward. Do not hard-code an October 26
  // timestamp when that older candidate is no longer in the retained window.
  // Instead verify the rendered watch against the earliest retained same-day
  // directional observation and its immutable first-observed price.
  const londonDay=t=>new Intl.DateTimeFormat("en-GB",{
    timeZone:"Europe/London",year:"numeric",month:"2-digit",day:"2-digit"
  }).format(new Date(t));
  const direction=cad.children[0].children.some(n=>String(n.textContent).includes("SELL BIAS"))?"SHORT":"LONG";
  const retained=feed.learning.paper_audit.candidates.filter(x=>
    x.source==="AUTOMATED_RESEARCH_PRIORITY"&&x.instrument==="CAD_CHF"&&x.direction===direction)
    .sort((a,b)=>Date.parse(b.created_at)-Date.parse(a.created_at));
  assert.ok(retained.length,"CAD/CHF card must have a retained source observation");
  const latest=retained[0];
  const peers=retained.filter(x=>londonDay(x.created_at)===londonDay(latest.created_at));
  const origin=peers.filter(x=>Number(x.tracking?.reference_price)>0&&
    Number.isFinite(Date.parse(x.tracking?.reference_at))).at(-1)||latest;
  const expectedStart=new Intl.DateTimeFormat("en-GB",{
    timeZone:"Europe/London",hour:"2-digit",minute:"2-digit",hour12:false
  }).format(new Date(origin.created_at));
  assert.ok(cad.children.some(c=>String(c.className).includes("current-watch-start")&&
    c.children.some(n=>String(n.textContent).includes(expectedStart))),
    "CAD/CHF watch start must match earliest retained same-day directional observation");
  const move=cad.children.find(c=>String(c.className).includes("current-watch-move"));
  const base=Number(origin.tracking?.reference_price);
  const quote=feed.pairs?.CAD_CHF?.quote||{};
  const price=Number(direction==="SHORT"?quote.ask:quote.bid);
  const expectedPct=(direction==="SHORT"?base-price:price-base)/base*100;
  assert.ok(move&&Number.isFinite(expectedPct)&&
    Math.abs(Number.parseFloat(move.textContent)-expectedPct)<0.002,
    "CAD/CHF movement must use its frozen original quote, not reset on a later snapshot");
}
assert.ok(visualCard.children.some(c=>String(c.className).includes("current-watch-move")),
  "Hourly cards must clearly display hypothetical directional price movement");
assert.equal($("indicators").children.length,10);
assert.equal($("headlines").children.length,Math.min(10,feed.headlines.length));
assert.ok($("events").children.length>=1,"Calendar must render actual upcoming releases or an explicit no-events caveat");
const approvedCount=feed.signals.filter(s=>s.instrument!=="GBP_ZAR"&&Date.parse(s.expires_at)>at.now).length;
assert.ok(approvedCount ? ["🟡 WAIT","🟢 GREEN"].includes($("verdict").textContent) :
  ["🔴 NO TRADE"].includes($("verdict").textContent),
  "unapproved early watches must never be green signals");
assert.equal(String($("approved").textContent),String(approvedCount));
assert.ok(feed.signals.some(s=>s.instrument===$("pair").value&&Date.parse(s.expires_at)>at.now)
  ? ["WAIT FOR TRIGGER","🟢 GREEN"].includes($("entryState").textContent)
  : ["WAIT","NO APPROVED ENTRY"].includes($("entryState").textContent));
assert.ok($("pair").options.length>=40,"Every screened quoted FX pair must be chart-selectable");
assert.equal($("pair").options.length,Object.keys(feed.pairs).filter(k=>k!=="GBP_ZAR").length);
const priorPair=$("pair").value;
$("pair").listeners.change({target:{value:"EUR_USD"}});
assert.match($("chartName").textContent,/EUR\/USD/);
assert.equal($("frames").children.length,9);
$("filter").value="GBPUSD";
$("filter").listeners.input();
assert.equal($("rows").children.length,1);
$("journalPair").value="GBP_USD";
$("outcome").value="LOSS";
$("note").value="Stopped at original planned SL; unverified self-report";
$("journal").listeners.submit({preventDefault(){}});
assert.equal(JSON.parse(saved["fx-journal-local-v1"]).length,1);
assert.match($("learningSummary").textContent,/self-reported/);
// When all registered watches expire, current-ranked research must not disappear.
feed.learning.opportunity_audit.recent.forEach(t=>{
  t.expires_at=new Date(at.now-15*60*1000).toISOString();
});
$("earlyScope").listeners.change({target:{value:"ACTIVE"}});
assert.equal($("earlyGrid").children.length,1);
assert.match($("earlyGrid").children[0].textContent,/No active priced watches/);
assert.ok($("scoutGrid").children.length>=5,
  "Expired registered watches must not hide current unpriced scouts");
// Simulate delayed source collection: all entry-ready UI must fail closed.
at.now=Date.parse(feed.snapshot_at)+110*60*1000;
for(const fn of timers)fn();
assert.equal($("verdict").textContent,"NO DATA");
assert.equal($("entryState").textContent,"NO ENTRY");
assert.match($("health").textContent,/STALE DATA/);
assert.equal($("paperTodayCount").textContent, "0 / " + feed.learning.paper_audit.candidates.filter(t=>
    ["LIVE_SIGNAL","GITHUB_FORMAL_SIGNAL","SCHEDULED_MAIN_ASSESSMENT"].includes(t.source) &&
    t.created_at.slice(0,10)===feed.snapshot_at.slice(0,10) &&
    (!t.expires_at || Date.parse(t.expires_at)>at.now) &&
    Number(t.entry)>0 && Number(t.stop)>0 && Number(t.tp1)>0).length,
  "Only todays priced assessment plans are shown; stale quotes must not be treated as current");
assert.match($("researchCards").children[0].className,/setupstale|setupempty/,"Stale research cannot be presented as an actionable current setup");
assert.match($("alert").children[0].textContent,/NO LIVE ENTRY/);
console.log("FX dashboard passed: full-universe chart selector, 10 indicators, shortlist, scanner, news, local journal, stale fail-closed.");
