'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const {tradeRows,summary,filterRows,exportCsv} = require('../docs/trade-history.js');

const sample={
  paper_only:true,
  closed:[
    {wallet:'WALLET_A',token:'POOL_A',pool_name:'MEME / SOL',
      opened_at:'2026-10-17T08:00:00Z',exit_at:'2026-10-17T10:00:00Z',
      notional_gbp:10,entry_price_usd:1.5,exit_price_usd:2.1,
      net_pnl_gbp:3.72,roi_pct:36.83,exit_reason:'20% paper take profit'},
    {wallet:'WALLET_B',token:'POOL_B',pool_name:'LOSS / SOL',
      opened_at:'2026-10-17T09:00:00Z',exit_at:'2026-10-17T10:05:00Z',
      notional_gbp:12,entry_price_usd:.75,exit_price_usd:.65,
      net_pnl_gbp:-2.25,roi_pct:-18.56,exit_reason:'12% paper stop loss'}
  ],
  positions:[{wallet:'WALLET_C',token:'POOL_C',pool_name:'OPEN / SOL',
    opened_at:'2026-10-17T10:06:00Z',notional_gbp:14,
    entry_price_usd:.55,last_mark_price_usd:.60}],
  research:{
    // These hypothetical shadow wins must never enter funded paper history.
    shadow_closed:[{net_pnl_gbp:999999,token:'SHADOW'}],
    whale_v3:{shadow_closed:[{net_pnl_gbp:888888,token:'WHALE'}]},
    strategies_v1:{
      closed:[
        {symbol:'SOL-PERP',setup:'pump_fade',direction:-1,
          opened_at:'2026-10-17T07:00:00Z',exit_at:'2026-10-17T09:10:00Z',
          entry:200,exit_price:180,entry_notional:500,
          net_usd:22.25,reason:'momentum/fade ended'},
        {symbol:'BTC-PERP',setup:'momentum_long',direction:1,
          opened_at:'2026-10-17T09:00:00Z',exit_at:'2026-10-17T09:30:00Z',
          entry:70000,exit_price:69000,entry_notional:400,
          net_usd:-10.75,reason:'stop/trailing stop'}
      ],
      position:{symbol:'ETH-PERP',setup:'momentum_long',direction:1,
        opened_at:'2026-10-17T10:00:00Z',entry:2400,entry_notional:200,net_usd:7}
    }
  }
};

test('Original GBP paper ledger is independent of USD and shadow outcomes',()=>{
  const a=tradeRows(sample,'gbp');
  assert.equal(a.length,3);
  assert.deepEqual(new Set(a.map(x=>x.currency)),new Set(['GBP']));
  assert.deepEqual(new Set(a.map(x=>x.direction)),new Set(['LONG']));
  assert.equal(summary(a).closed,2);
  assert.equal(summary(a).open,1);
  assert.equal(summary(a).wins,1);
  assert.equal(summary(a).losses,1);
  assert.ok(Math.abs(summary(a).net-1.47)<1e-8);
  assert.ok(!JSON.stringify(a).includes('SHADOW'));
  assert.ok(!JSON.stringify(a).includes('SOL-PERP'));
});

test('Futures ledger includes historical shorts, longs and one current open position',()=>{
  const a=tradeRows(sample,'usd');
  assert.equal(a.length,3);
  assert.equal(a.find(x=>x.market==='SOL-PERP').direction,'SHORT');
  assert.equal(a.find(x=>x.market==='BTC-PERP').direction,'LONG');
  assert.equal(a.find(x=>x.market==='ETH-PERP').status,'OPEN');
  assert.equal(a.find(x=>x.market==='ETH-PERP').net,null,
    'An open mark-to-market must not be reported as realised profit');
  assert.equal(a.find(x=>x.market==='SOL-PERP').roi,22.25/500*100);
  assert.equal(summary(a).net,11.5);
  assert.equal(summary(a).wins,1);
  assert.equal(summary(a).losses,1);
});

test('Sort order is most recently exited or opened first',()=>{
  assert.deepEqual(tradeRows(sample,'gbp').map(x=>x.market),
    ['OPEN / SOL','LOSS / SOL','MEME / SOL']);
  assert.deepEqual(tradeRows(sample,'usd').map(x=>x.market),
    ['ETH-PERP','BTC-PERP','SOL-PERP']);
});

test('Filters only use realised closes for win and loss classifications',()=>{
  const a=tradeRows(sample,'gbp');
  assert.deepEqual(filterRows(a,'wins','').map(x=>x.market),['MEME / SOL']);
  assert.deepEqual(filterRows(a,'losses','').map(x=>x.market),['LOSS / SOL']);
  assert.deepEqual(filterRows(a,'open','').map(x=>x.market),['OPEN / SOL']);
  assert.equal(filterRows(a,'closed','').length,2);
  assert.equal(filterRows(a,'all','SOL').length,3);
  assert.deepEqual(filterRows(a,'all','take profit').map(x=>x.market),['MEME / SOL']);
  assert.deepEqual(filterRows(a,'all','wallet_b').map(x=>x.market),['LOSS / SOL']);
  assert.deepEqual(filterRows(a,'losses','not found'),[]);
});

test('CSV exports all account-filtered rows with consistent amounts and both timestamps',()=>{
  const csv=exportCsv(filterRows(tradeRows(sample,'usd'),'closed',''));
  assert.equal(csv.trim().split('\r\n').length,3);
  assert.ok(csv.includes('"Futures challenger"'));
  assert.ok(csv.includes('"SOL-PERP"'));
  assert.ok(csv.includes('"SHORT"'));
  assert.ok(csv.includes('"2026-10-17T09:10:00Z"'));
  assert.ok(csv.includes('"USD"'));
  assert.ok(csv.includes('"22.25"'));
  assert.ok(!csv.includes('OPEN / SOL'));
  assert.ok(!csv.includes('SHADOW'));
});

test('CSV escapes spreadsheet formulas and embedded delimiter/newline/quotes',()=>{
  const rows=tradeRows({closed:[{
    pool_name:'=HYPERLINK("bad","X"),\nformula',net_pnl_gbp:1,
    opened_at:'2026-10-17T05:00:00Z',exit_at:'2026-10-17T06:00:00Z'
  }],positions:[]},'gbp');
  const csv=exportCsv(rows);
  assert.ok(csv.includes("\"'=HYPERLINK(\"\"bad\"\",\"\"X\"\"),\nformula\""));
  assert.ok(!csv.includes('"=HYPERLINK'));
});

test('Missing records and values are explicitly unknown, not fabricated zero-P&L wins',()=>{
  const a=tradeRows({closed:[{exit_at:'2026-10-17T12:00:00Z'}],
    positions:[{token:'NO_QUOTE',opened_at:'2026-10-17T12:01:00Z'}]},'gbp');
  assert.equal(a.length,2);
  assert.equal(summary(a).closed,1);
  assert.equal(summary(a).unknown,1);
  assert.equal(summary(a).wins,0);
  assert.equal(summary(a).net,0);
  assert.equal(a.find(x=>x.status==='OPEN').exitPrice,null);
  assert.equal(a.find(x=>x.status==='CLOSED').net,null);
  assert.deepEqual(tradeRows({},'usd'),[]);
});

test('Supports retained older trades without rewriting or mutating source ledgers',()=>{
  const before=JSON.stringify(sample);
  const a=tradeRows(sample,'gbp'),b=tradeRows(sample,'usd');
  filterRows(a,'wins','');filterRows(b,'losses','');
  exportCsv(a);exportCsv(b);
  assert.equal(JSON.stringify(sample),before);
});

test('Source serves a readily visible interactive trade history on the main dashboard',()=>{
  const fs=require('node:fs');
  const html=fs.readFileSync(require('node:path').join(__dirname,'../docs/index.html'),'utf8');
  assert.ok(html.includes('id="trade-history"'));
  assert.ok(html.includes('href="#trade-history"'));
  assert.ok(html.includes('id="history-rows"'));
  assert.ok(html.includes('id="history-export"'));
  assert.ok(html.includes('id="history-search"'));
  assert.ok(html.includes('data-history-account="gbp"'));
  assert.ok(html.includes('data-history-account="usd"'));
  assert.ok(html.includes('window.unifiedTradeHistoryRender?.(s)'));
  assert.ok(html.indexOf('<script src="./trade-history.js"></script>') <
    html.indexOf('window.unifiedTradeHistoryRender?.(s)'));
});

test('Original trade history shows one added winner lot and preserves saved net P&L',()=>{
  const state=structuredClone(sample);
  state.closed[0].additions=[{
    at:'2026-10-17T08:30:00Z',notional_gbp:9.95,
    price_usd:1.68,modelled_entry_fee_gbp:.0995
  }];
  state.closed[0].notional_gbp=19.95;
  state.closed[0].entry_price_usd=1.58;
  state.closed[0].net_pnl_gbp=5.5;
  const before=JSON.stringify(state);
  const wallet=tradeRows(state,'gbp');
  const winner=wallet.find(x=>x.market==='MEME / SOL');
  assert.equal(winner.additionCount,1);
  assert.equal(winner.addedNotional,9.95);
  assert.equal(winner.notional,19.95);
  assert.equal(winner.net,5.5);
  const csv=exportCsv(wallet);
  assert.ok(csv.includes('"Winner additions"'));
  assert.ok(csv.includes('"Added notional GBP"'));
  assert.ok(csv.includes('"9.95"'));
  assert.equal(JSON.stringify(state),before);
  const futures=tradeRows(state,'usd');
  assert.ok(futures.every(x=>x.additionCount===null));
});
