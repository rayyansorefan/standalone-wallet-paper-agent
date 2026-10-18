/* Read-only visual position monitor. Real recorded marks only. */
(function(root){
'use strict';
const num=v=>v!==null&&v!==undefined&&v!==''&&Number.isFinite(Number(v))?Number(v):null;
const rows=v=>Array.isArray(v)?v:[];
const money=(v,c)=>num(v)===null?'UNPRICED':(v<0?'−':v>0?'+':'')+(c==='USD'?'$':'£')+Math.abs(v).toFixed(2);
const percent=v=>num(v)===null?'UNPRICED':(v>0?'+':'')+v.toFixed(2)+'%';
const uk=v=>v&&Number.isFinite(Date.parse(v))?new Date(v).toLocaleString('en-GB',{timeZone:'Europe/London',day:'numeric',month:'short',hour:'2-digit',minute:'2-digit'}):'—';
const fresh=v=>v&&Number.isFinite(Date.parse(v))&&Date.now()-Date.parse(v)>=-60000&&Date.now()-Date.parse(v)<=900000;
const node=(tag,cls,txt)=>{const n=document.createElement(tag);if(cls)n.className=cls;if(txt!==undefined)n.textContent=String(txt);return n;};
const set=(id,txt)=>{const n=document.getElementById(id);if(n)n.textContent=txt;};
function chart(box,points,label,unit){
 box.replaceChildren();
 const a=points.filter(p=>num(p.y)!==null&&Number.isFinite(Date.parse(p.at))).slice(-144);
 if(a.length<2){box.append(node('p','owner-muted','Awaiting more recorded observations.'));return;}
 const w=740,h=200,l=48,r=12,t=12,b=31;
 const min=Math.min(...a.map(p=>p.y)),max=Math.max(...a.map(p=>p.y)),pad=Math.max(unit==='%'?.5:1,(max-min)*.15),lo=min-pad,hi=max+pad;
 const start=Date.parse(a[0].at),end=Date.parse(a.at(-1).at);
 const x=(p,i)=>l+(end===start?i/(a.length-1):(Date.parse(p.at)-start)/(end-start))*(w-l-r);
 const y=v=>t+(hi-v)/(hi-lo)*(h-t-b);
 const ns='http://www.w3.org/2000/svg',svg=document.createElementNS(ns,'svg');svg.setAttribute('viewBox','0 0 '+w+' '+h);svg.setAttribute('role','img');svg.setAttribute('aria-label',label);svg.classList.add('owner-svg');
 const el=(tag,attrs,txt)=>{const e=document.createElementNS(ns,tag);for(const [k,v] of Object.entries(attrs))e.setAttribute(k,v);if(txt!==undefined)e.textContent=txt;svg.append(e);};
 for(let i=0;i<4;i++){const v=lo+(hi-lo)*i/3;el('line',{x1:l,y1:y(v),x2:w-r,y2:y(v),stroke:'#354a65','stroke-dasharray':'4 5'});el('text',{x:l-6,y:y(v)+4,'text-anchor':'end',fill:'#aac0dc','font-size':11},(unit==='£'?'£':'')+v.toFixed(unit==='%'?1:0)+(unit==='%'?'%':''));}
 if(lo<0&&hi>0)el('line',{x1:l,y1:y(0),x2:w-r,y2:y(0),stroke:'#ffcc72','stroke-dasharray':'3 5'});
 const colour=a.at(-1).y>=a[0].y?'#34e7a5':'#ff617a';
 el('polyline',{points:a.map((p,i)=>x(p,i).toFixed(1)+','+y(p.y).toFixed(1)).join(' '),fill:'none',stroke:colour,'stroke-width':3.5,'stroke-linecap':'round','stroke-linejoin':'round'});
 el('circle',{cx:x(a.at(-1),a.length-1),cy:y(a.at(-1).y),r:5,fill:colour});
 el('text',{x:l,y:h-7,fill:'#a6b9d5','font-size':11},uk(a[0].at));el('text',{x:w-r,y:h-7,'text-anchor':'end',fill:'#a6b9d5','font-size':11},uk(a.at(-1).at));
 box.append(svg);
}
function position(p,usd,book){
 const name=usd?p.symbol:(p.pool_name||p.token),currency=usd?'USD':'GBP',last=p.last_mark_at||(usd?book.last_run:null);
 const entry=num(usd?p.entry:p.entry_price_usd),mark=num(usd?(p.mark||p.last_price):p.last_mark_price_usd),notional=num(usd?p.entry_notional:p.notional_gbp),paid=num(p.cost_gbp);
 const valid=fresh(last)&&(usd?num(p.net_usd)!==null&&notional>0:entry>0&&mark>0&&notional>0&&paid>0);
 const net=!valid?null:usd?num(p.net_usd):notional*mark/entry*.99-paid;
 const roi=net===null?null:100*net/(usd?notional:paid);
 const card=node('article','owner-position '+(net===null?'owner-unpriced':net>=0?'owner-positive':'owner-negative'));
 const header=node('div','owner-position-head');const title=node('div');title.append(node('h3','',name||'Unknown market'),node('small','owner-muted',currency+' · '+(usd?(p.direction===-1?'SHORT':'LONG'):'LONG')+' · opened '+uk(p.opened_at)));
 header.append(title,node('span','owner-pill',net===null?'QUOTE STALE':net>=0?'GAIN':'LOSS'));card.append(header);
 const gain=node('div','owner-gain '+(net===null?'':net>=0?'owner-green':'owner-red'));gain.append(node('strong','',percent(roi)),node('span','',money(net,currency)+' estimated net'));card.append(gain);
 const detail=node('div','owner-detail-grid');
 const items=[['Invested',money(notional,currency)],['Entry',entry===null?'—':'$'+entry.toPrecision(6)],['Last mark',mark===null?'—':'$'+mark.toPrecision(6)],['Last quote',uk(last)],['Best net ROI',num(p.highest_net_roi_pct)===null?'—':percent(num(p.highest_net_roi_pct))],['Added to winner',rows(p.additions).length+' times'],['Action',p.position_action||p.setup||'Monitoring'],['Protective stop',num(usd?p.stop:p.trailing_stop_price_usd)===null?'None':'$'+num(usd?p.stop:p.trailing_stop_price_usd).toPrecision(6)]];
 for(const [label,value] of items){const d=node('div');d.append(node('small','owner-muted',label),node('b','',value));detail.append(d);}card.append(detail);
 if(!valid)card.append(node('p','owner-warning','Fresh quote unavailable: current % gain/loss cannot be verified.'));
 card.append(node('h4','','Recorded position history'));
 const graph=node('div','owner-chart');card.append(graph);
 const marks=rows(p.mark_history).length?rows(p.mark_history):rows(p.recent_marks);
 chart(graph,marks.map(m=>({at:m.at,y:num(m.net_roi_pct)??(entry&&paid&&notional&&num(m.price_usd)?100*(notional*num(m.price_usd)/entry*.99-paid)/paid:null)})),name+' recorded net return','%');
 card.append(node('p','owner-muted','Real five-minute observations only; older marks cannot be reconstructed.'));return card;
}
function render(s){
 const book=s.research?.strategies_v1||{},open=rows(s.positions).map(p=>position(p,false,book));
 if(book.position)open.push(position(book.position,true,book));
 set('owner-open-count',open.length+' open');const holder=document.getElementById('owner-open-list');holder.replaceChildren();
 if(open.length)open.forEach(c=>holder.append(c));else holder.append(node('p','owner-muted','No open positions at this cycle.'));
 chart(document.getElementById('owner-equity'),rows(s.snapshots).filter(p=>num(p.equity_gbp)!==null).map(p=>({at:p.at,y:num(p.equity_gbp)})),'GBP paper equity','£');
 const closed=rows(s.closed),w=closed.filter(t=>num(t.net_pnl_gbp)>0).length,l=closed.filter(t=>num(t.net_pnl_gbp)<0).length,rate=w+l?100*w/(w+l):0;
 set('owner-win-rate',(w+l?rate.toFixed(1)+'%':'—')+' win rate');document.getElementById('owner-win-bar').style.width=rate+'%';set('owner-win-detail',w+' wins · '+l+' losses');
 const history=[...closed.map(t=>({...t,account:'GBP',pnl:num(t.net_pnl_gbp),roi:num(t.roi_pct)})),...rows(book.closed).map(t=>({...t,account:'USD',pnl:num(t.net_usd),roi:num(t.entry_notional)>0?num(t.net_usd)/num(t.entry_notional)*100:null}))].sort((a,b)=>Date.parse(b.exit_at||0)-Date.parse(a.exit_at||0)).slice(0,12);
 const h=document.getElementById('owner-position-history');h.replaceChildren();
 if(!history.length)h.append(node('p','owner-muted','No closed positions yet.'));
 for(const t of history){const d=node('details','owner-history-item'),head=node('summary','owner-history-head'),left=node('div');left.append(node('b','',t.pool_name||t.symbol||t.token||'Unknown'),node('small','owner-muted',t.account+' · '+uk(t.exit_at)));
 head.append(left,node('strong',t.pnl===null?'':t.pnl>=0?'owner-green':'owner-red',money(t.pnl,t.account)+' · '+percent(t.roi)));d.append(head);
 const body=node('div','owner-history-body');body.append(node('p','', 'Opened: '+uk(t.opened_at)+' · Closed: '+uk(t.exit_at)),node('p','', 'Reason: '+(t.exit_reason||t.reason||'Not recorded')),node('p','', 'Additions: '+rows(t.additions).length));d.append(body);
 if(rows(t.mark_history).length>1){const graph=node('div','owner-chart');d.append(graph);chart(graph,t.mark_history.map(m=>({at:m.at,y:num(m.net_roi_pct)})),'Closed position return','%');}
 h.append(d);}
}
root.ownerVisualRender=render;
})(typeof window!=='undefined'?window:undefined);
