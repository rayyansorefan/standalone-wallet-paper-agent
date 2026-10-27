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
assert.equal($("closedRecord").textContent,closedEvidence.filter(t=>t.realised_pnl_gbp>0).length+" wins / "+closedEvidence.filter(t=>t.realised_pnl_gbp<0).length+" loss");
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
const earlyCard=$("earlyGrid").children[0];
assert.match(JSON.stringify(earlyCard.children),/GBP\/USD/);
assert.match(JSON.stringify(earlyCard.children),/Entry zone/);
assert.match(JSON.stringify(earlyCard.children),/Stop \/ invalidation/);
assert.match(JSON.stringify(earlyCard.children),/Target 1/);
assert.match(JSON.stringify(earlyCard.children),/Started/);
const chartAction=earlyCard.children.at(-1).children.at(-1);
chartAction.listeners.click();
assert.match($("chartTime").textContent,/EARLY WATCH since/);
assert.match($("chartFoot").textContent,/EARLY WATCH/);
assert.match(JSON.stringify($("chart").children),/EARLY ENTRY ZONE/);
assert.equal($("currentVisualStrip").children.length,3,
  "Dashboard must present current research counts ahead of archived plans");
assert.ok($("hourlyCohortCards").children.length>=1,
  "Timestamped hourly watches must render as separate graphical cards");
const visualCard=$("hourlyCohortCards").children[0];
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
  const origin=feed.learning.paper_audit.candidates.find(x=>x.id==="PRIORITY-20261026-CAD_CHF-LONG");
  assert.ok(cad.children.some(c=>String(c.className).includes("current-watch-start")&&
    c.children.some(n=>String(n.textContent).includes("17:39"))),
    "Repeated CAD/CHF snapshots must retain first directional watch timestamp");
  const move=cad.children.find(c=>String(c.className).includes("current-watch-move"));
  assert.ok(move&&Math.abs(Number.parseFloat(move.textContent))>0.001,
    "CAD/CHF later snapshot must not reset the original nonzero observed movement to 0%");
}
assert.ok(visualCard.children.some(c=>String(c.className).includes("current-watch-move")),
  "Hourly cards must clearly display hypothetical directional price movement");
assert.equal($("indicators").children.length,10);
assert.equal($("headlines").children.length,Math.min(10,feed.headlines.length));
assert.ok($("events").children.length>=1,"Calendar must render actual upcoming releases or an explicit no-events caveat");
const approvedCount=feed.signals.filter(s=>s.instrument!=="GBP_ZAR"&&Date.parse(s.expires_at)>at.now).length;
assert.equal($("verdict").textContent,approvedCount?"REVIEW":"WAIT");
assert.equal(String($("approved").textContent),String(approvedCount));
assert.equal($("entryState").textContent,feed.signals.some(s=>s.instrument===$("pair").value&&Date.parse(s.expires_at)>at.now)?"REVIEW":"WAIT");
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
