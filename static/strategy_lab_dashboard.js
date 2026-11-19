// Historical backtest results only. This view never implies live strategy execution.
(function () {
  const $ = id => document.getElementById(id);
  const num = (v, digits=2) => v == null ? '—' : Number(v).toLocaleString('pl-PL', {minimumFractionDigits: digits, maximumFractionDigits: digits});
  function td(row, value, cls) { const c=document.createElement('td'); c.textContent=value; if(cls)c.className=cls; row.appendChild(c); }
  async function refreshLab() {
    try {
      const response=await fetch('/api/strategy-lab', {cache:'no-store'});
      if (!response.ok) throw new Error('Błąd pobierania wyników');
      const data=await response.json();
      $('lab-status').textContent=data.status === 'BACKTEST' ? 'BACKTEST' : 'BRAK WYNIKÓW';
      $('lab-note').textContent=data.status === 'BACKTEST'
        ? `Dane historyczne · ${data.candles} świec · ${data.strategies.length} strategii · NIE handel na żywo`
        : data.message;
      const body=$('lab-ranking'); body.replaceChildren();
      const list=[...(data.strategies||[])].sort((a,b)=>Number(b.return_pct)-Number(a.return_pct));
      if (!list.length) {const r=document.createElement('tr');td(r,'Brak wyników. Najpierw wykonaj backtest.');body.appendChild(r);return;}
      list.forEach((x,i)=>{const r=document.createElement('tr');td(r,i+1);td(r,x.strategy);td(r,x.family);td(r,num(x.final_usdt)+' USDT');td(r,(x.return_pct>=0?'+':'')+num(x.return_pct)+'%',x.return_pct<0?'negative':'');td(r,num(x.max_drawdown_pct)+'%');td(r,x.closed_trades);td(r,x.win_rate_pct==null?'—':num(x.win_rate_pct)+'%');body.appendChild(r);});
    } catch (e) { $('lab-status').textContent='BŁĄD'; $('lab-note').textContent=e.message; }
  }
  refreshLab();setInterval(refreshLab,60000);
})();
