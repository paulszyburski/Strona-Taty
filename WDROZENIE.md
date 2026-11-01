# Instalacja i obsługa — dla administratora hostingu

## Architektura
`public/` to statyczna strona. `backend/` to aplikacja WSGI Python 3.11+ (SQLite, Fernet, SMTP TLS, SMSAPI i Google Calendar API). Brak dashboardu. `private/`/BOOKING_DATA_DIR oraz plik środowiska i klucz Google muszą znajdować się poza publicznym katalogiem serwera. Nie kopiować ich do public/.

To kod startowy do wdrożenia i testu integracji, nie certyfikowany system medyczny. Nie aktywować bez przeglądu konfiguracji, bezpieczeństwa i zasad przetwarzania danych. Podstrony medyczne są w większości materiałem źródłowym, nie nowym przeglądem naukowym.

## Instalacja
1. Skopiować paczkę np. do `/opt/onkolog`, założyć osobne konto usługi systemowej i venv.
2. `python3 -m venv .venv` i `.venv/bin/pip install -r requirements.txt`.
3. Skopiować config.example.env poza katalog publiczny, wypełnić; ograniczyć prawa pliku do właściciela usługi. Nie wpisywać sekretów do JS, HTML ani repozytorium.
4. Wygenerować klucz: `.venv/bin/python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`. Zapisać jako BOOKING_ENCRYPTION_KEY, zabezpieczyć również kopię klucza. Utrata klucza oznacza utratę możliwości odczytu danych.
5. Ustawić BOOKING_DATA_DIR poza public/. Prawa katalogu 0700, umask 0077. Zaszyfrowany jest ładunek danych pacjenta; termin, status i kolejka operacyjna są metadanymi, które również trzeba chronić.
6. Załadować zmienne przez EnvironmentFile systemd. Uruchomić gunicorn wyłącznie na loopback: `.venv/bin/gunicorn --workers 2 --bind 127.0.0.1:8010 backend.app:application`, WorkingDirectory=/opt/onkolog. Nie otwierać portu 8010 na zewnątrz.
7. Ustawić reverse proxy HTTPS. Patrz nginx.example.conf; dopasować domenę i ścieżki. Root wskazuje wyłącznie /opt/onkolog/public. X-Real-IP jest zaufany tylko dla połączeń z loopback; proxy musi nadpisywać go adresem klienta.
8. Uruchamiać `.venv/bin/python -m backend.app worker` co minutę, z tym samym środowiskiem, użytkownikiem i WorkingDirectory. Może być cron lub timer systemd; worker ma blokadę zapobiegającą równoległym wykonaniom. Bez tego zgłoszenia będą zapisane, ale powiadomienia nie zostaną wysłane.
9. Wykonać testy na środowisku testowym. `python -m unittest discover -s tests -v` sprawdza lokalną logikę bez wysyłania danych na zewnątrz.

## Google Calendar — automatyczne wpisy
Utworzyć OSOBNY prywatny kalendarz organizacyjny na koncie lekarza lub praktyki; nie udostępniać asystentce ani innym kontom użytkowników. W Google Cloud włączyć Calendar API i utworzyć konto usługi. Udostępnić ten konkretny kalendarz adresowi konta usługi z prawem zmiany wydarzeń. Nie potrzeba delegacji całej domeny ani konta usługi jako właściciela kalendarza. Nie dodajemy gości ani pacjentów do wydarzeń.

Plik klucza konta usługi przechowywać poza public/ (np. /etc/onkolog-booking/google-service-account.json), uprawnienia 0600. Wpisać jego ścieżkę i GOOGLE_CALENDAR_ID. Backend używa tylko HTTPS z walidacją certyfikatów.

- Nowy wpis pojawia się przez worker zwykle do minuty po zgłoszeniu.
- Tytuł: „Rezerwacja wstępna · NUMER”. W prywatnym opisie: imię i nazwisko, telefon, e-mail oraz pytania. Nie załączamy dokumentów. Pole visibility=private nie zastępuje kontroli udostępnień całego kalendarza; konto usługi i administratorzy usługi mogą mieć techniczny dostęp.
- Potwierdzenie: asystentka zaczyna tytuł od „POTWIERDZONA” albo „Konsultacja potwierdzona”. Synchronizacja ustawia status lokalny. Płatność nadal sprawdza człowiek.
- Odwołanie: usunięcie wydarzenia zwalnia lokalny termin przy następnej udanej synchronizacji. Nowe, jeszcze niewysłane do Google zgłoszenie może anulować administrator poleceniem poniżej.
- Przełożenie: przesunięcie wydarzenia aktualizuje lokalny termin; pierwotny wraca do puli, jeśli nadal mieści się w grafiku. Nie przesuwać na godzinę innej aktywnej rezerwacji. Konflikt trafia do logu operacyjnego i wymaga poprawienia wydarzenia przez obsługę; nie jest automatycznie rozwiązywany.
- Blokada prywatna: wydarzenie oznaczone jako „zajęty” w tym kalendarzu ukrywa pokrywającą się godzinę na stronie. Wydarzenia „wolny” nie blokują.
- Zmiany/anulowanie NIE wysyłają pacjentowi automatycznych instrukcji. Asystentka kontaktuje się z nim telefonicznie lub e-mailem.
- Synchronizacja nie zwalnia rezerwacji, jeśli API nie działa. Błąd sprawdzania dostępności przyjmuje zasadę zamkniętą: brak nowych zapisów online, widoczny telefon.
- Operacje Google i lokalna baza nie tworzą jednej transakcji. Kalendarz organizacyjny zmieniany ręcznie równocześnie z zapisem może wymagać interwencji obsługi. Nie kopiować, nie odtwarzać i nie zmieniać identyfikatorów wydarzeń rezerwacji.

Instrukcje dostawcy: https://developers.google.com/workspace/calendar/api/guides/create-events
Referencja: https://developers.google.com/workspace/calendar/api/v3/reference/events/insert

## Opcjonalny e-mail i SMS

Google Calendar może działać bez konfiguracji SMTP i SMS. Jeśli powiadomienia e-mail mają być włączone, trzeba podać pełny zestaw zmiennych SMTP oraz `STAFF_EMAILS`. Ustawienie tylko części zmiennych jest traktowane jako błąd konfiguracji.
SMTP musi obsługiwać TLS (STARTTLS albo SMTP_SSL), uwierzytelnianie oraz poprawną domenę nadawcy (SPF/DKIM/DMARC do konfiguracji u dostawcy). STAFF_EMAILS = rzeczywiste, zatwierdzone adresy lekarza i asystentki. Pocztę należy zabezpieczyć MFA i ustalić retencję.

Mail wewnętrzny zawiera kontakt i pytania pacjenta; może zawierać dane o zdrowiu. Wymagana jest ocena bezpieczeństwa wybranego dostawcy oraz umowy i uprawnienia. TLS SMTP nie oznacza szyfrowania end-to-end skrzynek odbiorczych. Nie aktywować na przypadkowej skrzynce ani nie przekazywać tych wiadomości osobom nieupoważnionym. Publiczne API nie udostępnia pytań i danych pacjenta.

STAFF_SMS = lista numerów. SMSAPI_TOKEN i zatwierdzony nadawca zgodnie z kontem SMSAPI. Puste numery wyłączają SMS. Wiadomość SMS jest tylko powiadomieniem organizacyjnym, bez danych pacjenta. https://www.smsapi.pl/docs/

Kolejka powiadomień ponawia błędy do 10 prób z odstępami. Nie gwarantuje „exactly once” dla SMTP/SMS: przerwanie po przyjęciu wiadomości przez dostawcę może spowodować duplikat. Identyfikator wydarzenia Google jest stały dla rezerwacji, co ogranicza duplikaty kalendarza. Należy monitorować nieudane wysyłki; samo przyjęcie rezerwacji nie potwierdza dostarczenia SMS/e-maila.

## Obsługa techniczna bez panelu
Polecenia przez uprawnione konto serwera, z tym samym środowiskiem:
- `python -m backend.manage list` — numery, daty i statusy.
- `python -m backend.manage show NUMER` — dane i pytania; wynik poufny, nie kopiować do publicznych logów.
- `python -m backend.manage confirm NUMER` — status potwierdzony.
- `python -m backend.manage cancel NUMER` — odwołanie, usunięcie wydarzenia Google i zwolnienie terminu; bez zwrotu pieniędzy i bez maila do pacjenta.
- `python -m backend.manage deliveries` — kolejka wymagająca sprawdzenia.
- `python -m backend.manage retry` — ponowienie oczekujących zadań po usunięciu przyczyny błędu.

Brak automatycznego zwalniania nieopłaconych zgłoszeń. Asystentka ustala termin płatności i zwalnia rezerwację po kontakcie z pacjentem. Nie kasować ręcznie bazy. Dokumentację konsultacji prowadzić w osobnym, właściwym systemie — ten rejestr nie zastępuje dokumentacji medycznej.

## Przed produkcją
Wymagane: przegląd aktualnych dostawców i dokumentów prawnych, test Google na rzeczywistym koncie testowym, ochrona antyspamowa na reverse proxy, monitoring workerów/błędów i zajętości dysku, aktualizacje pakietów, backup bazy wraz z kluczem w oddzielnym bezpiecznym miejscu i test odtworzenia. Jeśli włączono SMTP lub SMS, trzeba również przetestować ich dostarczanie. Parametry rate limit w kodzie (5 nowych prób / adres IP / godzinę) należy dopasować do rzeczywistego proxy i ruchu. Nie używać danych medycznych w analityce reklamowej ani logach.

Po poprawnych testach ustawić BOOKING_MODE=live i zrestartować usługę. Formularz sam pobierze dostępność API, usunie oznaczenia podglądu i zacznie przyjmować zgłoszenia. Sam upload public/ nie uruchamia zaplecza.

Nie wykonano testów dostarczania u dostawców ani audytu bezpieczeństwa. Kod nie ma zawartych sekretów i nie uruchamia sam żadnej usługi.

## Zmiana v2 — pytania w Google
Zgodnie z decyzją lekarza opis wydarzenia zawiera również dane pacjenta i pytania. Nie ma listy gości. Tytuł powiadomienia nie zawiera imienia ani rozpoznania. Kalendarz pozostaje prywatny na jednym koncie użytkownika lekarza; konto usługi jest dodatkowym dostępem technicznym koniecznym dla tej implementacji. Przed aktywacją sprawdzić typ konta Google, właściwe warunki i umowy, MFA, uprawnienia aplikacji oraz urządzenia synchronizujące kalendarz. Samo visibility=private nie stanowi potwierdzenia zgodności przetwarzania danych medycznych.
Zmiana dotyczy nowych wydarzeń. Nie uruchamia aktualizacji wpisów, które mogły już powstać z wcześniejszej wersji.
