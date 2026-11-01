# Strona konsultacji online — paczka v2 z 1 listopada 2026 r.

> Pełna instrukcja instalacji produkcyjnej, systemd, Nginx, HTTPS i testu rezerwacji znajduje się w [`README.md`](README.md).

## Co jest w paczce
Strona oparta na oryginalnym projekcie premium: 600 zł, pełna analiza dokumentacji przed konsultacją, przygotowanie, 30 minut rozmowy i pisemne zalecenia.

Kalendarz na pięć tygodni: piątek 16:00 i 17:00 dostępne; piątek 15:00 oraz sobota 15:00, 16:00 i 17:00 niedostępne. Po rzeczywistej rezerwacji godzina znika z dostępnych. Pytania są opcjonalne. Telefon asystentki: 577 169 800, codziennie 8:00–17:00.

Nie ma panelu, PayU, uploadu dokumentów ani AI. Nie zmieniano oferty na ZnanymLekarzu.

## Oglądanie
Otwórz `public/index.html` po rozpakowaniu. W tym trybie formularz jest wyłącznie podglądem: nie zapisuje i nie wysyła danych. Podstrony, zdjęcia i style znajdują się w paczce. Wersję na telefon najlepiej oglądać na serwerze testowym.

## Poprawki po ocenie Claude'a
- Usunięto wzmiankę o pilnej konsultacji poniżej 24 godzin na stronie metod leczenia.
- Ujednolicono określenie „asystentka”.
- Wybrany termin ma etykietę „Wybrany”.
- Doprecyzowano osobną organizację wizyt stacjonarnych.
- Zmieniono zapisy regulaminu o rezerwacji, potwierdzaniu, płatności i ustalaniu kanału rozmowy.
- Usunięto instrukcję wysyłania dokumentacji na prywatny Gmail; kanał ustala asystentka.
- Zastąpiono obietnicę „najlepszej szansy” opisem oceny zasadności metod.
- Zachowano pole pytań, sobotę i jedną cenę 600 zł. Bez limitu podsumowania do jednej strony.

## Co może robić dołączone zaplecze po konfiguracji
1. Przyjmować zgłoszenia, zapisywać zaszyfrowane dane i blokować termin przed podwójną rezerwacją.
2. Opcjonalnie wysyłać e-maile do lekarza i asystentki oraz potwierdzenie zgłoszenia do pacjenta.
3. Wysyłać krótkie SMS-y organizacyjne przez SMSAPI, jeśli usługa zostanie skonfigurowana.
4. Dodawać rezerwację do prywatnego Kalendarza Google, z danymi kontaktowymi i pytaniami pacjenta w prywatnym opisie wydarzenia.
5. Odczytywać zajętość Google i synchronizować usunięcia lub przesunięcia utworzonych rezerwacji. Obsługa bez panelu: lekarz korzysta z własnego kalendarza, a asystentka ze zgłoszeń e-mail.

Tytuł wydarzenia zawiera numer zgłoszenia; ten sam numer jest w mailu. Dzięki temu można połączyć termin ze szczegółami. Opis wydarzenia zawiera imię i nazwisko, telefon, e-mail i pytania. Kalendarz nie jest udostępniany asystentce ani pacjentowi; techniczne konto usługi potrzebuje ograniczonego dostępu do integracji.

## Ważne: to nie jest aktywowane wdrożenie
Bez `BOOKING_MODE=live` aplikacja działa w trybie PODGLĄD. Konfigurację produkcyjną musi wykonać osoba obsługująca hosting. Testy lokalne nie zastępują testu usług na serwerze docelowym.

Do uruchomienia potrzebne są:
- hosting z Pythonem i możliwością uruchomienia usługi w tle (albo osobne małe zaplecze); zwykły hosting tylko HTML/PHP nie uruchomi dołączonego backendu;
- adresy e-mail lekarza i asystentki oraz konto SMTP, jeśli mają działać powiadomienia e-mail;
- numer/numery powiadomień i konto SMSAPI, jeśli włączamy SMS;
- prywatny kalendarz na własnym koncie Google lekarza oraz połączenie API (bez dostępu asystentki);
- ustalenie bezpiecznego kanału dostarczania dokumentacji i akceptacja końcowej treści regulaminu/polityki dla wybranych dostawców.

Nie trzeba kupować sprzętu GSM. SMS jest płatną usługą zewnętrzną. Kalendarza nie udostępniamy publicznie i nie osadzamy pełnej zawartości konta Google na stronie.

## Ocena przed uruchomieniem
Sprawdzić na docelowym serwerze zgłoszenie, blokadę terminu w dwóch przeglądarkach, wpis Google, odwołanie i zwolnienie terminu oraz ograniczenie dostępu do konta lekarza i niezbędnej integracji. Jeśli skonfigurowano e-mail lub SMS, sprawdzić również ich dostarczanie. Dopiero wtedy ustawić `BOOKING_MODE=live`. Nie publikować samego katalogu `public/` jako działającego systemu rezerwacji — pozostałby podglądem.

Szczegóły instalacji i obsługi: `WDROZENIE.md`.

## Czy trzeba znać Pythona?
Do jednorazowego wdrożenia tej wersji potrzebny jest administrator/deweloper umiejący uruchamiać usługi Python na serwerze i podłączyć Google Calendar. SMTP i SMS są opcjonalne. Do codziennego odbierania rezerwacji nie trzeba znać Pythona. Zwykły upload HTML na hosting PHP nie uruchamia rezerwacji. Przed wdrożeniem ustalić możliwości aktualnego hostingu; nie trzeba od razu przenosić całej strony.
