# Strategy Lab — integracja z dashboardem

## Co jest zaimplementowane
- Osobny backtester 50 konfiguracji strategii (`strategy_lab.py`), pobieranie OHLCV (`download_history.py`).
- Read-only endpoint `/api/strategy-lab`, tabela rankingowa w istniejącym dashboardzie.
- Backtest i działający bot korzystają z osobnych danych; `bot.py`, `mirror.py` i baza istniejącego bota pozostają nietknięte.

## Uruchom lokalnie
```bash
pip install -r requirements.txt
python download_history.py --symbol BTCUSDT --interval 15m --start 2025-01-01 --end 2026-11-01
python strategy_lab.py --csv data/history/BTCUSDT_15m_2025-01-01_2026-11-01.csv --output strategy_lab_results
python -m unittest discover -s tests
```
Uruchom `web_app.py` lokalnie z konfiguracją bazy i sesji. `/api/strategy-lab` odczytuje `strategy_lab_results/results.json`.

## Render
Render Web Service i Background Worker mają **oddzielne systemy plików**. Samo uruchomienie backtestu na workerze nie pokaże wyników na stronie. Aby udostępnić historyczne wyniki dashboardowi, trzeba zapewnić `results.json` w środowisku usługi web (np. jako artefakt wdrożenia) i ustawić `STRATEGY_LAB_RESULTS` na jego ścieżkę.
**Ten pakiet NIE uruchamia 50 strategii live i nie synchronizuje ich do Supabase.** Nie zmieniaj start command istniejącego workera. Do 30-dniowego forward testu potrzebny jest osobny worker, trwałe przechowywanie i dostęp dashboardu do jego wyników.

## Ograniczenia badawcze
- Symulacja OHLCV, bez danych order-book i wymogów LOT_SIZE/MIN_NOTIONAL.
- Brak optymalizacji walk-forward, podziału in/out-of-sample oraz multi-asset portfolio.
- Każdy wariant używa całego wirtualnego portfela i stałych kosztów; wyniki nie przewidują przyszłych zwrotów.
