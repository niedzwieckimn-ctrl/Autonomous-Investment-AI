# Panel na Render — wdrożenie bez resetowania portfela

Źródłem prawdy pozostaje istniejąca baza workera: `/var/data/paperbot.sqlite3`. Po każdym cyklu worker kopiuje aktualny stan do PostgreSQL. Panel odczytuje wyłącznie PostgreSQL. Kopia jest idempotentna i nie składa żadnych zleceń. Nie uruchamiaj `bot.py` jako Web Service ani drugiego Background Workera.

## Usługi i koszt

Potrzebne są: istniejący płatny Render Background Worker z dyskiem; istniejący projekt Supabase `niedzwieccy-restore-test-20261029` z osobnym schematem `paperbot`; jeden Render Web Service. Wariant `render.yaml` wybiera bezpłatny Web Service, który może zasypiać i wolniej odpowiadać po bezczynności. Nie twórz nowego projektu Supabase (użytkownik odrzucił dodatkowy koszt 10 USD/miesiąc). Aktualne stawki i limity istniejącego projektu oraz Render trzeba sprawdzić przed włączeniem.

## 1. Przygotuj PostgreSQL

1. Użyj projektu `niedzwieccy-restore-test-20261029`. Schemat i tabele `paperbot` zostały już utworzone. Zachowaj hasło bazy w menedżerze haseł.
2. W `Project Settings → Database → Connection string` skopiuj adres połączenia dla workera. Render obsługuje IPv4; jeśli adres bezpośredni wymaga IPv6, wybierz Session Pooler. Użyj połączenia TLS (`sslmode=require`).
3. Rola `paperbot_reader` z uprawnieniem wyłącznie do odczytu schematu `paperbot` została już utworzona jako `NOLOGIN`. W `SQL Editor` wykonaj poniższy skrypt, zastępując `TU_WLASNE_SILNE_HASLO` własnym długim hasłem. To konto służy wyłącznie panelowi. Nie zapisuj tego hasła w repozytorium.

```sql
ALTER ROLE paperbot_reader LOGIN PASSWORD 'TU_WLASNE_SILNE_HASLO';
```

Jeśli worker łączy się przez rolę inną niż `postgres`, wykonaj `ALTER DEFAULT PRIVILEGES FOR ROLE <rola_workera> ...` dla tej roli. Po pierwszej synchronizacji ponów `GRANT SELECT ON ALL TABLES IN SCHEMA paperbot TO paperbot_reader;`, jeśli konto panelu nie widzi tabel. Adres panelu to ten sam host/pooler i baza, z użytkownikiem `paperbot_reader` i jego hasłem. Hasło w adresie URL musi być zakodowane percent encoding, jeśli ma znaki specjalne.

## 2. Zabezpiecz dane przed pierwszą synchronizacją

1. W Render otwórz **istniejący Background Worker → Shell**. Nie uruchamiaj drugiego bota.
2. Zrób kopię SQLite przez API backup, które daje spójny obraz mimo działania bota:

```bash
python -c "import sqlite3; s=sqlite3.connect('/var/data/paperbot.sqlite3'); d=sqlite3.connect('/var/data/paperbot-before-mirror.sqlite3'); s.backup(d); d.close(); s.close()"
```

3. Zanotuj aktualne dane (bez ich modyfikowania):

```bash
python -c "import sqlite3; d=sqlite3.connect('/var/data/paperbot.sqlite3'); print(dict(d.execute('select key,value from meta'))); print('trades',d.execute('select count(*) from trades').fetchone()[0]); print('snapshots',d.execute('select count(*) from snapshots').fetchone()[0]); print('positions',d.execute('select count(*) from positions').fetchone()[0])"
```

Jeżeli plan Render nie udostępnia Shell, użyj **SSH** lub jednorazowej komendy administracyjnej w istniejącym workerze. Nie kopiuj pliku SQLite przez zwykłe `cp` podczas aktywnego zapisu.

## 3. Włącz replikację w istniejącym workerze

1. W **Environment** istniejącego workera dodaj `DATABASE_URL` z adresem zapisu PostgreSQL (rola `postgres`, TLS). Nie dodawaj tego adresu do GitHub.
2. Wdróż commit tego repozytorium do tego samego workera. Zachowaj obecny Start Command: `python bot.py --db /var/data/paperbot.sqlite3`, dysk `/var/data` i jedną instancję.
3. W Shell istniejącego workera wykonaj jednorazową kopię, bez uruchamiania bota:

```bash
python mirror.py --source /var/data/paperbot.sqlite3
```

4. Sprawdź w logach komunikat `Mirror updated`. Automatyczna aktualizacja odbywa się po każdym cyklu. Gdy PostgreSQL jest chwilowo niedostępny, bot nadal działa na SQLite; błąd synchronizacji trafia do logu i następny cykl ponawia pełną kopię.

## 4. Wdróż panel

1. Web Service `autonomous-investment-dashboard` został już utworzony na planie Free z gałęzi `feature/render-dashboard-mirror` i ma włączone automatyczne wdrażanie commitów. [Otwórz usługę w Render](https://dashboard.render.com/web/srv-dbvfjarl550s739kphr0). Po scaleniu PR zmień jej gałąź na `main`. Plik `render.yaml` służy jako odtwarzalna konfiguracja; nie twórz drugiej usługi z Blueprint.
2. W **Environment** tej usługi ustaw `DASHBOARD_DATABASE_URL` (konto `paperbot_reader`) i `DASHBOARD_PASSWORD` (silne, osobne hasło do panelu). `DASHBOARD_SESSION_SECRET` został wygenerowany losowo i ustawiony w Render. Nie ujawniaj żadnego z sekretów w kodzie ani publicznym widoku panelu.
3. W **Settings → Health Check Path** ustaw `/health`.
4. Po wdrożeniu odwiedź `/health`, potem `/login`. Zaloguj się i sprawdź, czy wartość portfela, liczba transakcji i otwarte pozycje odpowiadają stanowi SQLite z kroku 2. Panel pobiera dane co 15 sekund. Status ONLINE wymaga ostatniej wyceny i synchronizacji młodszych niż 180 sekund.

## Diagnostyka i wycofanie

- `503` w `/api/portfolio`: sprawdź `DASHBOARD_DATABASE_URL`, sieć/TLS, czy `paperbot_reader` ma `SELECT` na `paperbot.*`, oraz logi Web Service. Dane logowania nie trafiają do klienta.
- `OFFLINE`: sprawdź logi istniejącego workera i ostatni `snapshots.ts_ms` oraz `sync_status.synced_at`; panel nie uruchamia bota.
- Aby wyłączyć replikację, usuń `DATABASE_URL` z workera. SQLite i jego stan pozostają bez zmian. Możesz wyłączyć Web Service bez wpływu na transakcje.
- Nie przywracaj kopii SQLite bez sprawdzenia, czy nowsze transakcje nie powstały od czasu backupu.

Lokalny panel Streamlit (`dashboard.py`) pozostaje dostępny do pracy na lokalnej SQLite. Publiczny panel Render to `web_app.py`.

