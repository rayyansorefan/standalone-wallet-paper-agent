import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import fs from 'node:fs';
const code = fs.readFileSync(new URL('./Code.gs', import.meta.url), 'utf8');
function harness(age = 500) {
  const calls = [], props = {GITHUB_ACTIONS_TOKEN: 'placeholder-not-real'}, logs = [], triggers = [];
  const context = vm.createContext({Date, JSON, isFinite, Error,
    console: {log: x => logs.push(x)},
    PropertiesService: {getScriptProperties: () => ({getProperty: k => props[k], setProperty: (k,v) => props[k]=v})},
    LockService: {getScriptLock: () => ({tryLock: () => true, releaseLock() {}})},
    ScriptApp: {getProjectTriggers: () => triggers, newTrigger: handler => ({timeBased() {return this;}, everyMinutes(n) {assert.equal(n,5); return this;}, create() {triggers.push({getHandlerFunction: () => handler, getUniqueId: () => 'uid'});}})},
    UrlFetchApp: {fetch: (url,options) => {calls.push({url,options}); return calls.length===1 ? {getResponseCode: () => 200, getContentText: () => JSON.stringify({paper_only:true,starting_gbp:2000,last_run:new Date(Date.now()-age*1000).toISOString()})} : {getResponseCode: () => 204};}}
  });
  vm.runInContext(code,context);
  return {context,calls,logs,triggers,props};
}
test('time trigger sends provenance and only repository-specific dispatch', () => {
  const h=harness(); h.context.paperTick({triggerUid:'clock-1'});
  assert.equal(h.calls.length,2);
  const body=JSON.parse(h.calls[1].options.payload);
  assert.equal(body.ref,'main'); assert.equal(body.inputs.trigger_uid,'clock-1');
  assert.equal(body.inputs.scheduler,'google-apps-script');
  assert.ok(h.logs.every(x=>!x.includes('placeholder-not-real')));
});
test('recent native run prevents duplicate dispatch', () => {
  const h=harness(40); h.context.paperTick({triggerUid:'clock-1'});
  assert.equal(h.calls.length,1); assert.equal(JSON.parse(h.props.LAST_DISPATCH).result,'recent-cycle-skip');
});
test('manual execution cannot impersonate a clock run', () => {
  const h=harness(); assert.throws(()=>h.context.paperTick(), /genuine time-driven/); assert.equal(h.calls.length,0);
});
test('installation is idempotent and does not manually dispatch', () => {
  const h=harness(); h.context.installScheduler(); h.context.installScheduler();
  assert.equal(h.triggers.length,1); assert.equal(h.calls.length,0);
});
