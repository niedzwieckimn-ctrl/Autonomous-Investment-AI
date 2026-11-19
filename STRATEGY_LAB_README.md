# Strategy Lab — wersja prototypowa (backtesting)

Ta wersja jest **oddzielna od działającego bota**. Nie wysyła zleceń i nie zmienia jego bazy danych. Zawiera 50 konfiguracji pięciu rodzin strategii (nie 50 niezależnie wynalezionych algorytmów).

## Uruchomienie

Przygotuj historyczny CSV z kolumnami `timestamp,open,high,low,close,volume`, w porządku chronologicznym. Znacznik czasu: ISO UTC lub Unix w milisekundach. Minimum 150 świec.

```bash
python strategy_lab.py --csv history.csv --output strategy_lab_results
python -m unittest discover -s tests -p 'test_strategy_lab.py' -v
```

Wyniki: `ranking.csv` i `results.json` (z przebiegami wartości portfeli).

## Istotne ograniczenia prototypu

- Jeden rynek i jeden interwał na przebieg. Wiele par wymaga osobnego rozszerzenia.
- Model wejścia: sygnał na zamkniętej świecy, wykonanie na otwarciu następnej.
- Symulowane prowizje 0,1% i poślizg 0,05% na stronę. Nie ma rzeczywistych danych bid/ask ani głębokości arkusza.
- Nie ma egzekwowania giełdowych MIN_NOTIONAL, LOT_SIZE; przy 50 USDT wyniki mogą być niewykonalne na realnej giełdzie.
- Stop-loss na danych OHLC jest przybliżeniem, nie dokładną symulacją kolejności zdarzeń wewnątrz świecy.
- Nie wykonano jeszcze backtestu na rzeczywistych danych giełdowych ani 30-dniowego paper tradingu.
- Strategie są hipotezami badawczymi. Nie należy wybierać zwycięzcy tylko po najlepszym wyniku z próby historycznej.

Kolejne kroki: pobieranie i walidacja danych, podział train/validation/out-of-sample, walidacja walk-forward, realistyczne filtry giełdowe, wielorynkowe portfele i niezależny moduł live paper trading.

## Automatyczne pobieranie historii — v2

Nie trzeba ręcznie przygotowywać CSV. Uruchom w katalogu projektu:

```bash
python download_history.py --symbol BTCUSDT --interval 15m --start 2024-01-01 --end 2026-11-01
python strategy_lab.py --csv data/history/BTCUSDT_15m_2024-01-01_2026-11-01.csv --output strategy_lab_results/BTCUSDT
python -m unittest discover -s tests -p 'test_*.py' -v
```

`--end` oznacza wyłączną datę końcową UTC. Pobieranie odbywa się stronicowo (maks. 1000 świec na żądanie), bez kluczy API. Downloader odrzuca duplikaty i przerwy w danych, nie dopisuje niezamkniętych świec. Może wystąpić blokada regionalna HTTP 451; wtedy pobierz dane z dozwolonej lokalizacji lub skorzystaj z oficjalnego archiwum Binance Data Vision.

**Nowy plik:** `download_history.py` w katalogu głównym; `tests/test_download_history.py` w `tests/`. Pozostałe pliki z v1 bez zmian. Nie zmieniać `bot.py`, `web_app.py`, `render.yaml`, `mirror.py` ani bazy istniejącego bota. To nadal tylko backtest pojedynczego rynku; brak 30-dniowego paper tradingu i ograniczeń minimalnych zleceń Binance.
