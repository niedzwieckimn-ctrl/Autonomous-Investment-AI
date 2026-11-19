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
      $('lab-status').textContent=data.status === 'FORWARD' ? 'PAPER LIVE' : (data.status === 'WAITING' ? 'OCZEKIWANIE' : 'NIEURUCHOMIONY');
      $('lab-note').textContent=data.status === 'FORWARD'
        ? `50 niezależnych portfeli · bieżące świece 15m · tylko wirtualne środki`
        : data.message;
      const body=$('lab-ranking'); body.replaceChildren();
      const list=[...(data.strategies||[])].sort((a,b)=>Number(b.return_pct ?? -999)-Number(a.return_pct ?? -999));
      if (!list.length) {const r=document.createElement('tr');td(r,'Brak wyników. Najpierw uruchom osobny worker laboratorium.');body.appendChild(r);return;}
      list.forEach((x,i)=>{const r=document.createElement('tr');td(r,i+1);td(r,x.strategy);td(r,x.family);td(r,(x.final_usdt == null ? '—' : num(x.final_usdt)+' USDT'));td(r,(x.return_pct==null?'—':(x.return_pct>=0?'+':'')+num(x.return_pct)+'%'),x.return_pct<0?'negative':'');td(r,num(x.max_drawdown_pct)+'%');td(r,x.closed_trades);td(r,x.win_rate_pct==null?'—':num(x.win_rate_pct)+'%');body.appendChild(r);});
    } catch (e) { $('lab-status').textContent='BŁĄD'; $('lab-note').textContent=e.message; }
  }
  refreshLab();setInterval(refreshLab,60000);
})();
