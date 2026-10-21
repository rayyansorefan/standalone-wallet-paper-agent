// Browser-free functional smoke tests: no third-party dependencies or live APIs.
import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";

const html=fs.readFileSync("docs/index.html","utf8");
const feed=JSON.parse(fs.readFileSync("docs/fx-feed.json","utf8"));
assert.equal(feed.schema,1);
const script=html.split("<script>")[1]?.split("</script>")[0];
assert.ok(script, "Dashboard JavaScript is present");
new vm.Script(script);

const saved={};
class MockNode{
  constructor(tag,id){this.tagName=tag;this.id=id;this.children=[];this.listeners={};this.textContent="";this.value="";this.className="";this.style={};this.attributes={};this.options=[];this.disabled=false;}
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
  localStorage,console,fetch:async()=>({ok:true,json:async()=>feed}),
  setInterval:(fn)=>timers.push(fn)};
vm.runInNewContext(script,ctx);
await new Promise(resolve=>setImmediate(resolve));
const $=id=>map.get(id);
assert.equal($("screened").textContent,feed.coverage.screened+" / "+feed.coverage.total);
assert.equal($("rows").children.length,Object.keys(feed.pairs).length);
assert.equal($("picks").children.length,Math.min(4,feed.priorities.length));
assert.ok($("chart").children.length>30,"Completed candlesticks should render");
assert.equal($("indicators").children.length,9);
assert.equal($("headlines").children.length,Math.min(10,feed.headlines.length));
assert.ok($("events").children.length>=1,"Calendar must render actual upcoming releases or an explicit no-events caveat");
const approvedCount=feed.signals.filter(s=>Date.parse(s.expires_at)>at.now).length;
assert.equal($("verdict").textContent,approvedCount?"REVIEW":"WAIT");
assert.equal(String($("approved").textContent),String(approvedCount));
assert.equal($("entryState").textContent,feed.signals.some(s=>s.instrument===$("pair").value&&Date.parse(s.expires_at)>at.now)?"REVIEW":"WAIT");
assert.ok($("pair").options.length>=1,"At least one genuinely available detailed chart must be selectable");
assert.equal($("pair").options.length,Object.values(feed.pairs).filter(p=>p.deep).length);
const priorPair=$("pair").value;
$("pair").listeners.change({target:{value:"EUR_USD"}});
assert.match($("chartName").textContent,/EUR\/USD/);
assert.equal($("frames").children.length,5);
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
assert.match($("alert").children[0].textContent,/NO LIVE ENTRY/);
console.log("FX dashboard passed: variable shortlist/deep pair counts, scanner, charts, news, local journal, stale fail-closed.");
