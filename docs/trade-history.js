/* Trade History · paper-ledger-only, account-isolated and dependency-free.
   This view reads existing persisted records; it never creates or changes trades.
   The pure helpers are CommonJS-exported for deterministic Node regression tests.
*/
(function (root) {
  'use strict';
  const PAGE_SIZE = 15;
  const isNumber = x => x !== null && x !== undefined && x !== '' && Number.isFinite(Number(x));
  const number = x => isNumber(x) ? Number(x) : null;
  const records = x => Array.isArray(x) ? x : [];
  const validTime = value => {
    if (!value) return null;
    const epoch = Date.parse(String(value));
    return Number.isFinite(epoch) ? epoch : null;
  };
  const fmtTime = value => {
    const stamp = validTime(value);
    if (stamp === null) return '—';
    return new Intl.DateTimeFormat('en-GB', {
      timeZone:'Europe/London',day:'2-digit',month:'short',year:'numeric',
      hour:'2-digit',minute:'2-digit',hour12:false
    }).format(new Date(stamp));
  };
  const amount = (value, currency) => {
    if (!isNumber(value)) return '—';
    const n = Number(value);
    return (n < 0 ? '−' : n > 0 ? '+' : '') + (currency === 'GBP' ? '£' : '$') +
      Math.abs(n).toLocaleString('en-GB',{minimumFractionDigits:2,maximumFractionDigits:2});
  };
  const price = value => {
    if (!isNumber(value)) return '—';
    return '$' + Number(value).toLocaleString('en-GB',{maximumSignificantDigits:8});
  };
  const pct = value => isNumber(value) ? Number(value).toFixed(2)+'%' : '—';

  function tradeRows(state, account) {
    const original = account !== 'usd';
    const futures = (state?.research || {}).strategies_v1 || {};
    const closed = original ? records(state?.closed) : records(futures.closed);
    const open = original ? records(state?.positions) : (futures.position ? [futures.position] : []);
    function normalise(t, isClosed, i) {
      if (!t || typeof t !== 'object') return null;
      const direction = original ? 'LONG' : Number(t.direction) === -1 ? 'SHORT' : 'LONG';
      const opened = t.opened_at || null;
      const exit = isClosed ? (t.exit_at || null) : null;
      const net = isClosed ? number(original ? t.net_pnl_gbp : t.net_usd) : null;
      const notional = number(original ? t.notional_gbp : t.entry_notional);
      const roi = isClosed ? (original ? number(t.roi_pct)
        : notional && net !== null ? 100 * net / notional : null) : null;
      const adds=original ? records(t.additions) : [];
      const addNotional=original ? adds.reduce((total,item)=>total+(number(item?.notional_gbp)||0),0) : null;
      return {
        id: (original ? 'gbp' : 'usd')+'-'+(isClosed ? 'closed' : 'open')+'-'+i,
        account:original ? 'gbp' : 'usd',currency:original ? 'GBP' : 'USD',
        status:isClosed ? 'CLOSED' : 'OPEN',
        market:String(original ? (t.pool_name || t.token || 'Unknown pool') : (t.symbol || 'Unknown symbol')),
        direction, opened,exit,
        notional,entry:number(original ? t.entry_price_usd : t.entry),
        exitPrice:isClosed ? number(original ? t.exit_price_usd : t.exit_price) : null,
        net,roi,additionCount:original ? adds.length : null,
        addedNotional:addNotional,
        reason:isClosed ? String((original ? t.exit_reason : t.reason) || 'Not recorded') : 'Position still open',
        sender:String(t.wallet || ''),
        sortTime:validTime(exit || opened) ?? -1
      };
    }
    const all = closed.map((t,i) => normalise(t,true,i))
      .concat(open.map((t,i) => normalise(t,false,i))).filter(Boolean);
    return all.sort((a,b)=>b.sortTime-a.sortTime || a.id.localeCompare(b.id));
  }

  function summary(rows) {
    const closed=rows.filter(x=>x.status==='CLOSED');
    const priced=closed.filter(x=>x.net!==null);
    return {closed:closed.length,open:rows.length-closed.length,
      wins:priced.filter(x=>x.net>0).length,
      losses:priced.filter(x=>x.net<0).length,
      net:priced.reduce((a,x)=>a+x.net,0),unknown:closed.length-priced.length};
  }

  function filterRows(rows, mode, query) {
    const q=String(query||'').trim().toLowerCase();
    return rows.filter(t=>{
      const hit=mode==='all' || (mode==='open' && t.status==='OPEN') ||
        (mode==='closed' && t.status==='CLOSED') ||
        (mode==='wins' && t.status==='CLOSED' && t.net!==null && t.net>0) ||
        (mode==='losses' && t.status==='CLOSED' && t.net!==null && t.net<0);
      return hit && (!q || [t.market,t.direction,t.reason,t.sender,t.status]
        .some(v=>String(v).toLowerCase().includes(q)));
    });
  }

  function csvCell(value) {
    let text=String(value===null || value===undefined ? '' : value);
    // Avoid spreadsheet formula injection when a CSV is opened in Excel.
    if (/^[\s]*[=+\-@]/.test(text)) text="'"+text;
    return '"'+text.replace(/"/g,'""')+'"';
  }

  function exportCsv(rows) {
    const headings=['Account','Status','Market or pool','Direction','Opened UTC',
      'Closed UTC','Notional','Notional currency','Entry price USD','Exit price USD',
      'Net profit or loss','P&L currency','ROI on entry notional (%)',
      'Exit reason','Observed sender (unverified)',
      'Winner additions','Added notional GBP'];
    const values=rows.map(t=>[
      t.account==='gbp'?'Original paper wallet':'Futures challenger',t.status,
      t.market,t.direction,t.opened,t.exit,t.notional,t.currency,t.entry,
      t.exitPrice,t.net,t.currency,t.roi,t.reason,t.sender,
      t.additionCount,t.addedNotional
    ]);
    return [headings,...values].map(row=>row.map(csvCell).join(',')).join('\r\n')+'\r\n';
  }

  const api={tradeRows,summary,filterRows,exportCsv};
  if (typeof module !== 'undefined' && module.exports) module.exports=api;
  if (!root || !root.document) return;

  const $=id=>root.document.getElementById(id);
  const ui={account:'gbp',mode:'all',query:'',limit:PAGE_SIZE,state:null};
  function cell(tr,text,className) {
    const td=root.document.createElement('td');
    td.textContent=String(text ?? '—');
    if (className) td.className=className;
    tr.appendChild(td);
    return td;
  }
  function render() {
    if (!ui.state || ui.state.paper_only!==true) return;
    const rows=tradeRows(ui.state,ui.account),stats=summary(rows);
    const filtered=filterRows(rows,ui.mode,ui.query);
    const body=$('history-rows');
    if (!body) return;
    const currency=ui.account==='gbp'?'GBP':'USD';
    $('history-summary').textContent=stats.closed+' closed · '+stats.wins+' wins · '+
      stats.losses+' losses · '+stats.open+' open · Realised '+amount(stats.net,currency)+
      (stats.unknown ? ' · '+stats.unknown+' missing P&L' : '');
    $('history-count').textContent='Showing '+Math.min(ui.limit,filtered.length)+' of '+
      filtered.length+' matching trades · '+rows.length+' recorded positions';
    body.replaceChildren();
    if (!filtered.length) {
      const tr=root.document.createElement('tr');
      const td=cell(tr,'No matching paper trades in this account.');td.colSpan=10;
      body.appendChild(tr);
    }
    filtered.slice(0,ui.limit).forEach(t=>{
      const tr=root.document.createElement('tr');
      cell(tr,t.market);
      cell(tr,t.direction);
      cell(tr,fmtTime(t.opened));
      cell(tr,fmtTime(t.exit));
      cell(tr,isNumber(t.notional) ? amount(t.notional,t.currency).replace(/^\+/,'') : '—');
      cell(tr,price(t.entry)+' → '+price(t.exitPrice));
      cell(tr,t.status);
      cell(tr,t.additionCount===null?'—':t.additionCount?
        t.additionCount+' · +'+amount(t.addedNotional,'GBP').replace(/^\\+/,''):'None');
      cell(tr,amount(t.net,t.currency)+(t.net!==null?' ('+pct(t.roi)+')':''),t.net===null?'':t.net<0?'negative':t.net>0?'positive':'');
      cell(tr,t.reason);
      body.appendChild(tr);
    });
    $('history-more').hidden=filtered.length<=ui.limit;
    $('history-export').disabled=!filtered.length;
    root.document.querySelectorAll('[data-history-account]').forEach(btn=>{
      const active=btn.dataset.historyAccount===ui.account;
      btn.classList.toggle('sel',active);
      btn.setAttribute('aria-pressed',String(active));
    });
    root.document.querySelectorAll('[data-history-mode]').forEach(btn=>{
      const active=btn.dataset.historyMode===ui.mode;
      btn.classList.toggle('sel',active);
      btn.setAttribute('aria-pressed',String(active));
    });
  }
  function bind() {
    root.document.querySelectorAll('[data-history-account]').forEach(btn=>{
      btn.addEventListener('click',()=>{
        ui.account=btn.dataset.historyAccount;ui.limit=PAGE_SIZE;render();
      });
    });
    root.document.querySelectorAll('[data-history-mode]').forEach(btn=>{
      btn.addEventListener('click',()=>{
        ui.mode=btn.dataset.historyMode;ui.limit=PAGE_SIZE;render();
      });
    });
    const search=$('history-search');
    if (search) search.addEventListener('input',()=>{
      ui.query=search.value;ui.limit=PAGE_SIZE;render();
    });
    const more=$('history-more');
    if (more) more.addEventListener('click',()=>{ui.limit+=PAGE_SIZE;render();});
    const csv=$('history-export');
    if (csv) csv.addEventListener('click',()=>{
      if (!ui.state) return;
      const rows=filterRows(tradeRows(ui.state,ui.account),ui.mode,ui.query);
      if (!rows.length) return;
      const data=exportCsv(rows);
      const blob=new Blob([data],{type:'text/csv;charset=utf-8'});
      const url=URL.createObjectURL(blob);
      const link=root.document.createElement('a');
      link.href=url;
      link.download='paper-trades-'+ui.account+'-'+new Date().toISOString().slice(0,10)+'.csv';
      root.document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
    });
  }
  // Script sits after its markup and before the canonical state polling script.
  bind();
  root.unifiedTradeHistoryRender=function (state) {
    ui.state=state;
    render();
  };
})(typeof window !== 'undefined' ? window : globalThis);
