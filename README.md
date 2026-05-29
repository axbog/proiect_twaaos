# Proiect: Gestionar Sarcini & Inventar

Pași rapizi pentru dezvoltare:

1. Creează un mediu virtual:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

2. Instalează dependențele:

```bash
pip install -r requirements.txt
```

3. Rulează serverul în modul de dezvoltare:

```bash
uvicorn main:app --reload --port 8000
```

Endpoint-uri principale:
- `POST /inregistrare` - înregistrare utilizator
- `POST /autentificare` - obținere token
- `GET /sarcini`, `POST /sarcini`, `PUT /sarcini/{id}`, `PATCH /sarcini/{id}/finaliza`, `DELETE /sarcini/{id}`

Fișiere importante:
- `main.py` - API FastAPI
- `sarcini.db` - baza de date SQLite (se creează automat)

Notă: Schimbați `SECRET_KEY` din `main.py` înainte de a folosi în producție.
