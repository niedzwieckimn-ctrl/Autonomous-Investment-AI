const $ = id => document.getElementById(id);
let state = null, chart = null, profitChart = null;
const money = n => n == null ? '—' : `${Number(n).toFixed(2)} USDT`;
const signed = n => n == null ? '—' : `${n >= 0 ? '+' : ''}${Number(n).toFixed(2)} USDT`;
const pct = n => `${n >= 0 ? '+' : ''}${Number(n).toFixed(2)}%`;
const dt = ms => new Date(ms).toLocaleString('pl-PL');
const n = (value, places=6) => Number(value).toLocaleString('pl-PL',{maximumFractionDigits:places});
const cutoff = period => ({'24h':86400000,'7d':604800000,'30d':2592000000,'all':Infinity})[period];
function cell(row, value, cls='') { const td=document.createElement('td'); td.textContent=value; if(cls)td.className=cls; row.append(td); }
function rows(table, items, render, empty) { table.replaceChildren(); if(!items.length){const tr=document.createElement('tr');cell(tr,empty);table.append(tr);return;} for(const item of items){const tr=document.createElement('tr');render(tr,item);table.append(tr);} }
function render(){if(!state || !state.snapshots)return; const s=state;if(s.status==='WAITING'){$('status').textContent='OCZEKIWANIE';$('error').textContent=s.message;$('error').hidden=false;return;}
  $('status').textContent=s.status; $('status').className='badge '+s.status.toLowerCase();
  $('equity').textContent=money(s.equity); $('total').textContent=`${signed(s.total_pnl)} (${pct(s.total_pct)})`; $('total').classList.toggle('negative',s.total_pnl<0);
  $('cash').textContent=money(s.cash); $('positionValue').textContent=money(s.position_value); $('daily').textContent=`${signed(s.day_pnl)} (${pct(s.day_pct)})`; $('alltime').textContent=`${signed(s.total_pnl)} (${pct(s.total_pct)})`;
  $('updated').textContent=dt(s.last_update_ms); $('source').textContent=s.source; $('count').textContent=`${s.trade_count} (${s.closed_count} zamkniętych)`;
  $('winrate').textContent=s.closed_count?`${s.win_rate.toFixed(1)}%`:'—'; $('realized').textContent=signed(s.realized_pnl); $('fees').textContent=money(s.fees); $('drawdown').textContent=`${s.max_drawdown.toFixed(2)}%`;
  $('best').textContent=s.best?`${s.best.symbol}: ${signed(s.best.pnl_usdt)}`:'—'; $('worst').textContent=s.worst?`${s.worst.symbol}: ${signed(s.worst.pnl_usdt)}`:'—';
  $('positionNote').textContent=s.positions.length?`${s.positions.length} otwarta pozycja`:'Bot nie ma otwartej pozycji';
  rows($('positions'),s.positions,(r,p)=>{cell(r,p.symbol);cell(r,n(p.qty,8));cell(r,money(p.cost_usdt));cell(r,n(p.entry_price,8));cell(r,n(p.stop_price,8));cell(r,dt(p.opened_ms));},'Brak otwartych pozycji');
  const tx=s.trades.filter(t=>Date.now()-t.ts_ms<=cutoff($('tradePeriod').value));
  rows($('trades'),tx,(r,t)=>{cell(r,dt(t.ts_ms));cell(r,t.symbol);cell(r,t.side,t.side.toLowerCase());cell(r,n(t.qty,8));cell(r,n(t.fill_price,8));cell(r,money(t.fee_usdt));cell(r,t.pnl_usdt==null?'—':signed(t.pnl_usdt),t.pnl_usdt<0?'negative':'');cell(r,t.reason,'reason');cell(r,money(t.equity_after_usdt));},'Brak transakcji w wybranym okresie');
  const points=s.snapshots.filter(x=>Date.now()-x.ts_ms<=cutoff($('period').value));
  if(chart)chart.destroy(); chart=new Chart($('equityChart'),{type:'line',data:{labels:points.map(x=>dt(x.ts_ms)),datasets:[{data:points.map(x=>Number(x.equity_usdt)),borderColor:'#52d9ae',backgroundColor:'rgba(82,217,174,.08)',fill:true,tension:.25,pointRadius:0,borderWidth:2}]},options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{display:false},tooltip:{callbacks:{label:c=>money(c.parsed.y)}}},scales:{x:{ticks:{color:'#8297b5',maxTicksLimit:7},grid:{color:'#25344a'}},y:{ticks:{color:'#8297b5'},grid:{color:'#25344a'}}}}});
  if(profitChart)profitChart.destroy(); profitChart=new Chart($('profitChart'),{type:'line',data:{labels:points.map(x=>dt(x.ts_ms)),datasets:[{data:points.map(x=>Number(x.equity_usdt)-s.initial),borderColor:'#87a7ff',backgroundColor:'rgba(135,167,255,.08)',fill:true,tension:.25,pointRadius:0,borderWidth:2}]},options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{display:false},tooltip:{callbacks:{label:c=>signed(c.parsed.y)}}},scales:{x:{ticks:{color:'#8297b5',maxTicksLimit:7},grid:{color:'#25344a'}},y:{ticks:{color:'#8297b5'},grid:{color:'#25344a'}}}}});
}
async function refresh(){try{const r=await fetch('/api/portfolio',{cache:'no-store'});if(r.status===401){location.href='/login';return;}if(!r.ok)throw new Error('Brak połączenia z bazą danych');state=await r.json();$('error').hidden=true;render();}catch(e){$('error').textContent=e.message;$('error').hidden=false;$('status').textContent='OFFLINE';$('status').className='badge offline';}}
$('period').addEventListener('change',render);$('tradePeriod').addEventListener('change',render);refresh();setInterval(refresh,15000);
