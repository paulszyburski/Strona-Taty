# Strona konsultacji onkologicznych

Statyczna strona internetowa z systemem rezerwacji konsultacji. Frontend znajduje się w `public/`, a backend WSGI w `backend/`. Rezerwacje są zapisywane w SQLite, a worker tworzy wydarzenia w prywatnym Kalendarzu Google.

## Jak działa rezerwacja

1. Pacjent wybiera termin i wysyła formularz.
2. Backend sprawdza dane i ponownie sprawdza dostępność terminu.
3. Rezerwacja oraz zadanie dla workera są zapisywane w jednej transakcji SQLite.
4. Pacjent otrzymuje numer rezerwacji.
5. Worker tworzy wydarzenie w Kalendarzu Google.

Backend i worker są osobnymi procesami. Bez workera rezerwacja zostanie zapisana, ale wydarzenie Google nie powstanie.

## Wymagania produkcyjne

Poniższa konfiguracja zakłada serwer Ubuntu lub Debian z:

- dostępem SSH i uprawnieniami `sudo`;
- Pythonem 3.11 lub nowszym;
- Nginx i systemd;
- domeną wskazującą na serwer;
- włączonym Google Calendar API;
- kontem usługi Google z dostępem do kalendarza rezerwacji.

Zwykły hosting obsługujący wyłącznie statyczne HTML lub PHP nie uruchomi tego backendu.

## Docelowy układ plików

```text
/opt/strona-taty/                 kod aplikacji
/opt/strona-taty/.venv/           środowisko Pythona
/etc/strona-taty/app.env          konfiguracja i sekrety
/etc/strona-taty/google.json      klucz konta usługi Google
/var/lib/strona-taty/             baza SQLite i blokada workera
```

Katalog serwowany publicznie przez Nginx musi wskazywać wyłącznie na `/opt/strona-taty/public`.

## 1. Przygotowanie serwera

```bash
sudo apt update
sudo apt install python3-venv nginx certbot python3-certbot-nginx
sudo useradd --system --home /opt/strona-taty --shell /usr/sbin/nologin strona-taty
sudo mkdir -p /opt/strona-taty /etc/strona-taty /var/lib/strona-taty
```

Skopiuj repozytorium do `/opt/strona-taty`. Nie kopiuj lokalnych katalogów `.venv/`, `private/` ani pliku `.env` jako konfiguracji produkcyjnej.

```bash
cd /opt/strona-taty
sudo python3 -m venv .venv
sudo .venv/bin/pip install -r requirements.txt
sudo chown -R strona-taty:strona-taty /opt/strona-taty /var/lib/strona-taty
```

## 2. Istniejąca konfiguracja

Projekt zakłada, że gotowy plik `.env` oraz klucz konta usługi Google zostały już przygotowane. Skopiuj je na serwer jako `/etc/strona-taty/app.env` i `/etc/strona-taty/google.json`, a następnie ogranicz dostęp:

```bash
sudo chown strona-taty:strona-taty /etc/strona-taty/app.env /etc/strona-taty/google.json
sudo chmod 600 /etc/strona-taty/app.env /etc/strona-taty/google.json
```

Nie umieszczaj tych plików w `public/` ani w repozytorium.

## 3. Usługa backendu

Utwórz `/etc/systemd/system/strona-taty.service`:

```ini
[Unit]
Description=Strona Taty booking backend
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=strona-taty
Group=strona-taty
WorkingDirectory=/opt/strona-taty
EnvironmentFile=/etc/strona-taty/app.env
ExecStart=/opt/strona-taty/.venv/bin/gunicorn --workers 2 --bind 127.0.0.1:8010 backend.app:application
Restart=on-failure
RestartSec=5
PrivateTmp=true
NoNewPrivileges=true

[Install]
WantedBy=multi-user.target
```

Uruchom usługę:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now strona-taty.service
sudo systemctl status strona-taty.service
```

## 4. Worker i timer

Utwórz `/etc/systemd/system/strona-taty-worker.service`:

```ini
[Unit]
Description=Strona Taty booking worker
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
User=strona-taty
Group=strona-taty
WorkingDirectory=/opt/strona-taty
EnvironmentFile=/etc/strona-taty/app.env
ExecStart=/opt/strona-taty/.venv/bin/python -m backend.app worker
PrivateTmp=true
NoNewPrivileges=true
```

Utwórz `/etc/systemd/system/strona-taty-worker.timer`:

```ini
[Unit]
Description=Uruchamianie workera rezerwacji co minutę

[Timer]
OnBootSec=30
OnUnitActiveSec=60
Unit=strona-taty-worker.service

[Install]
WantedBy=timers.target
```

Włącz timer:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now strona-taty-worker.timer
sudo systemctl list-timers | grep strona-taty
```

## 5. Nginx

Utwórz `/etc/nginx/sites-available/strona-taty`:

```nginx
server {
    listen 80;
    listen [::]:80;

    server_name onkolog-szyburski.pl www.onkolog-szyburski.pl;

    root /opt/strona-taty/public;
    index index.html;
    client_max_body_size 20k;

    location / {
        try_files $uri $uri/ =404;
    }

    location ^~ /api/ {
        proxy_pass http://127.0.0.1:8010;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 40s;
    }

    location ~ /\. {
        deny all;
    }

    add_header X-Content-Type-Options nosniff always;
    add_header Referrer-Policy strict-origin-when-cross-origin always;
}
```

Włącz konfigurację:

```bash
sudo ln -s /etc/nginx/sites-available/strona-taty /etc/nginx/sites-enabled/strona-taty
sudo nginx -t
sudo systemctl reload nginx
```

Jeśli domyślna strona Nginx przechwytuje domenę, usuń `/etc/nginx/sites-enabled/default`, ponownie wykonaj `sudo nginx -t` i przeładuj Nginx.

## 6. HTTPS

Najpierw upewnij się, że rekordy DNS domeny wskazują na publiczny adres serwera. Następnie:

```bash
sudo certbot --nginx -d onkolog-szyburski.pl -d www.onkolog-szyburski.pl
```

Sprawdź stronę pod `https://onkolog-szyburski.pl`. Na tym etapie nadal powinna działać w trybie podglądu.

## 7. Test przed włączeniem rezerwacji

Uruchom testy kodu:

```bash
cd /opt/strona-taty
sudo -u strona-taty .venv/bin/python -m unittest discover -s tests -v
```

Sprawdź logi:

```bash
sudo journalctl -u strona-taty.service -n 100 --no-pager
sudo journalctl -u strona-taty-worker.service -n 100 --no-pager
```

Wykonaj ręcznie worker:

```bash
sudo systemctl start strona-taty-worker.service
sudo systemctl status strona-taty-worker.service
```

## 8. Test produkcyjny

Po uruchomieniu wszystkich usług:

```bash
sudo systemctl restart strona-taty.service
```

Wyślij jedną testową rezerwację przez publiczną stronę. Sprawdź, czy:

1. strona zwraca numer rezerwacji;
2. zajęty termin znika z listy;
3. wydarzenie pojawia się w Google Calendar po pracy workera;
4. anulowanie usuwa wydarzenie i zwalnia termin.

Lista rezerwacji:

```bash
sudo -u strona-taty bash -c 'set -a; source /etc/strona-taty/app.env; set +a; cd /opt/strona-taty; .venv/bin/python -m backend.manage list'
```

Anulowanie testu:

```bash
sudo -u strona-taty bash -c 'set -a; source /etc/strona-taty/app.env; set +a; cd /opt/strona-taty; .venv/bin/python -m backend.manage cancel NUMER_REZERWACJI'
```

## Aktualizacja aplikacji

Po skopiowaniu nowej wersji kodu:

```bash
cd /opt/strona-taty
sudo .venv/bin/pip install -r requirements.txt
sudo chown -R strona-taty:strona-taty /opt/strona-taty
sudo systemctl restart strona-taty.service
sudo systemctl start strona-taty-worker.service
```

Nie zastępuj `/etc/strona-taty/app.env`, `/etc/strona-taty/google.json` ani `/var/lib/strona-taty` podczas aktualizacji.

## Diagnostyka

Stan usług:

```bash
sudo systemctl status strona-taty.service
sudo systemctl status strona-taty-worker.timer
sudo systemctl status strona-taty-worker.service
sudo systemctl status nginx
```

Logi:

```bash
sudo journalctl -u strona-taty.service -f
sudo journalctl -u strona-taty-worker.service -f
```

Sprawdzenie API:

```bash
curl -sS https://onkolog-szyburski.pl/api/availability
```

Oczekiwana odpowiedź po włączeniu produkcji zawiera `"mode": "live"` oraz listę terminów.

## Kopie zapasowe

Kopia produkcyjna musi obejmować:

- `/var/lib/strona-taty/booking.sqlite`;
- `/etc/strona-taty/app.env`, szczególnie `BOOKING_ENCRYPTION_KEY`;
- `/etc/strona-taty/google.json` albo bezpieczną procedurę utworzenia nowego klucza.

Przechowuj kopie poza serwerem i ogranicz dostęp do nich. Sama baza bez właściwego klucza Fernet nie pozwoli odzyskać zaszyfrowanych danych.

## Test lokalny

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
PUBLIC_ORIGIN=http://127.0.0.1:8000 .venv/bin/python -m backend.dev
```

Otwórz `http://127.0.0.1:8000`. Po wysłaniu formularza uruchom w drugim terminalu:

```bash
.venv/bin/python -m backend.app worker
```

Szczegóły działania integracji i dodatkowe uwagi bezpieczeństwa znajdują się w `WDROZENIE.md`.
