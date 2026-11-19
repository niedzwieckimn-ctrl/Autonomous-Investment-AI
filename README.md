# Bot inwestycyjny — symulacja Binance Spot

Lokalny bot z wirtualnym kapitałem początkowym **50 USD**, reprezentowanym jako **50 USDT** na rynku Binance Spot. USDT może odbiegać od 1 USD; wynik jest pokazywany w USDT, bez pozornej precyzji przeliczenia na dolary. Nie używa kluczy API i nie zawiera kodu do składania prawdziwych zleceń. Wybiera do 15 płynnych par USDT spośród listy 50 kryptowalut (`CRYPTO_BASES` w `bot.py`) według 24-godzinnego wolumenu. Lista wyklucza m.in. tokenizowane akcje i stablecoiny. Analizuje wyłącznie zamknięte świece 15-minutowe, a co 60 sekund podejmuje decyzję o zakupie, sprzedaży albo czekaniu. Sygnał wymaga jednocześnie trendu EMA, dodatniego MACD, odpowiedniego RSI, podwyższonego wolumenu i umiarkowanej zmienności ATR. Strategia jest eksperymentem, nie przewiduje zysków.

## Uruchomienie (Windows PowerShell)

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python bot.py
```

W drugim oknie:

```powershell
.venv\Scripts\python -m streamlit run dashboard.py
```

Panel: `http://localhost:8501`. Bot pracuje, dopóki działa terminal. Po ponownym uruchomieniu odczytuje saldo, pozycje i historię z `data/paperbot.sqlite3`. Nie uruchamiaj dwóch procesów bota na tej samej bazie. Jednorazowa analiza: `python bot.py --once`. Inna baza: `python bot.py --db ścieżka/do/bazy.sqlite3` (panel domyślnie czyta `data/paperbot.sqlite3`).

## Zasady rozliczania

- Początkowy nominalny kapitał 50 USD zapisuje się jako 50 USDT. Wynik pozostaje w USDT. To uproszczenie oznacza ryzyko odchylenia USDT od USD.
- Zakup wykorzystuje aktualną cenę ask, sprzedaż bid. Każdy fill zawiera konserwatywny poślizg 0,05% i prowizję 0,1%. Spread jest zawarty w bid/ask. Realna głębokość rynku, częściowe realizacje i zmienność między odczytem a transakcją nie są modelowane.
- Bot używa do 95% dostępnej gotówki. Pozostałość wynika z wielkości kroku zlecenia i rezerwy. Cały zysk ze sprzedaży wraca do dostępnego salda. Dopuszcza najwyżej jedną pozycję naraz. Respektuje `LOT_SIZE`, `MARKET_LOT_SIZE`, `MIN_NOTIONAL` i `NOTIONAL` z `exchangeInfo`, a także dostępną ilość na najlepszej cenie.
- Stop-loss jest ustawiany od 2,5% do 7% poniżej ceny zakupu (zależnie od ATR). Bot zamyka pozycję również po stracie 8% względem początku dnia UTC, 15% od maksimum portfela albo 20% względem 50 USDT; następnie blokuje nowe zakupy, dopóki limit nadal jest przekroczony. W razie zbyt małej pozycji lub braku płynności sprzedaż może być niemożliwa — zdarzenie trafia do logu.
- Stan jest zapisywany w SQLite po każdej transakcji i analizie. Ceny pozycji w panelu pochodzą z ostatniego zapisanego cyklu, nie z osobnego pobrania w panelu.

Źródła danych: publiczne REST `https://data-api.binance.vision/api/v3` oraz WebSocket `wss://stream.binance.com:9443/stream` (`@bookTicker`); przy braku świeżego kwotowania WS używany jest REST. API może być niedostępne w niektórych regionach. Bot ponawia połączenia i pomija cykl, gdy nie ma wiarygodnych danych.

## Testy

```powershell
python -m unittest discover -s tests -v
```

Testy używają sztucznych danych wyłącznie do sprawdzania obliczeń i trwałości zapisu. `--once` sprawdza osobno rzeczywisty dostęp do Binance.
