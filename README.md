# Zelva

Webovy projekt postaveny na Flask + HTML/CSS/JavaScript pro zelvi grafiku v prohlizeci.

## Struktura

- `src/zelva/app.py` Flask aplikace a routy
- `src/zelva/templates/` HTML sablony
- `src/zelva/static/` frontend skripty a styly
- `tests/` automaticke testy

## Spusteni

### Linux (doporučeno)

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install -e .

# dev server
python -m zelva
```

Pak otevrite `http://127.0.0.1:5000`.

Volitelne muzete nastavit prostredi pro dev server:

```bash
export HOST=0.0.0.0
export PORT=5000
export DEBUG=1
```

## Produkcni beh na Linux serveru

Bez EXE, pres standardni WSGI server `gunicorn`:

```bash
source .venv/bin/activate
gunicorn -w 3 -b 0.0.0.0:8000 zelva.wsgi:application
```

Pak aplikaci vystavte pres reverse proxy (napr. Nginx).

## Kratky systemd priklad

Soubor `/etc/systemd/system/zelva.service`:

```ini
[Unit]
Description=Zelva Flask App
After=network.target

[Service]
User=www-data
Group=www-data
WorkingDirectory=/opt/zelva
Environment="PATH=/opt/zelva/.venv/bin"
ExecStart=/opt/zelva/.venv/bin/gunicorn -w 3 -b 127.0.0.1:8000 zelva.wsgi:application
Restart=always

[Install]
WantedBy=multi-user.target
```

Aktivace:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now zelva
sudo systemctl status zelva
```

## Podporovane prikazy

- `forward(cislo)`
- `left(cislo)`
- `right(cislo)`
- `penup()`
- `pendown()`
- `goto(x, y)`

## Testy

```bash
source .venv/bin/activate
pytest
```
