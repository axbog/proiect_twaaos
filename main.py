import sqlite3
import jwt
import os
from dotenv import load_dotenv
from datetime import datetime, timedelta, timezone
from typing import Optional, List
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Depends, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from passlib.context import CryptContext
from pydantic import BaseModel, Field

# Incarca variabilele din .env
load_dotenv()

# ---------------------------------------------------------------------------
# 1. Configurare și Securitate (Actualizat cu variabile de mediu)
# ---------------------------------------------------------------------------
SECRET_KEY = os.environ.get("SECRET_KEY", "cheie-dev-de-inlocuit")
ALGORITHM = os.environ.get("ALGORITHM", "HS256")
EXPIRARE_TOKEN_MINUTE = int(os.environ.get("EXPIRARE_TOKEN_MINUTE", "30"))
DATABASE_PATH = "sarcini.db"

context_parola = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_schema = OAuth2PasswordBearer(tokenUrl="autentificare")

# ---------------------------------------------------------------------------
# 2. Funcții Utilitare Parole & Token
# ---------------------------------------------------------------------------
def hasheaza_parola(parola: str) -> str:
    # Taiem parola la primele 72 de caractere pentru a evita eroarea bcrypt
    return context_parola.hash(parola[:72])

def verifica_parola(parola: str, hash_parola: str) -> bool:
    # Verificam doar primele 72 de caractere
    return context_parola.verify(parola[:72], hash_parola)

def creeaza_token(date: dict) -> str:
    date_copie = date.copy()
    expirare = datetime.now(timezone.utc) + timedelta(minutes=EXPIRARE_TOKEN_MINUTE)
    date_copie.update({"exp": expirare})
    return jwt.encode(date_copie, SECRET_KEY, algorithm=ALGORITHM)

# ---------------------------------------------------------------------------
# 3. Gestiune Bază de Date
# ---------------------------------------------------------------------------
def initializeaza_db():
    conn = sqlite3.connect(DATABASE_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS utilizatori (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            parola_hash TEXT NOT NULL
        )
    """)
    # Modificat: Am adăugat coloana data_crearii
    conn.execute("""
        CREATE TABLE IF NOT EXISTS sarcini (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            titlu TEXT NOT NULL,
            descriere TEXT,
            finalizata INTEGER DEFAULT 0,
            data_crearii TEXT,
            utilizator_id INTEGER NOT NULL,
            FOREIGN KEY (utilizator_id) REFERENCES utilizatori(id)
        )
    """)
    conn.commit()
    conn.close()

def get_db():
    conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        yield conn
    finally:
        conn.close()

@asynccontextmanager
async def lifespan(app: FastAPI):
    initializeaza_db()
    yield

app = FastAPI(title="Gestionar Sarcini & Inventar", version="1.1.0", lifespan=lifespan)

# ---------------------------------------------------------------------------
# CONFIGURARE CORS
# ---------------------------------------------------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5500",  
        "http://127.0.0.1:5500",  
        "null",                   
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# 4. Modele Pydantic
# ---------------------------------------------------------------------------
class UtilizatorInregistrare(BaseModel):
    email: str
    parola: str

class SarcinaBase(BaseModel):
    titlu: str = Field(..., min_length=1, max_length=200)
    descriere: Optional[str] = None

class SarcinaActualizare(BaseModel):
    titlu: Optional[str] = None
    descriere: Optional[str] = None
    finalizata: Optional[bool] = None

class Produs(BaseModel):
    id: int
    nume: str
    pret: float
    stoc: int = 0
    descriere: Optional[str] = None

# ---------------------------------------------------------------------------
# 5. Dependență: Obținere Utilizator Curent
# ---------------------------------------------------------------------------
def get_utilizator_curent(token: str = Depends(oauth2_schema), db: sqlite3.Connection = Depends(get_db)):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        email: str = payload.get("sub")
        if email is None:
            raise HTTPException(status_code=401, detail="Token invalid")
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Token invalid sau expirat")
    
    utilizator = db.execute("SELECT * FROM utilizatori WHERE email = ?", (email,)).fetchone()
    if utilizator is None:
        raise HTTPException(status_code=401, detail="Utilizator inexistent")
    return utilizator

# ---------------------------------------------------------------------------
# 6. Endpoint-uri Autentificare & Utilizatori
# ---------------------------------------------------------------------------
@app.post("/inregistrare", status_code=201)
def inregistrare(u: UtilizatorInregistrare, db: sqlite3.Connection = Depends(get_db)):
    hash_p = hasheaza_parola(u.parola)
    try:
        db.execute("INSERT INTO utilizatori (email, parola_hash) VALUES (?, ?)", (u.email, hash_p))
        db.commit()
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=400, detail="Email deja înregistrat")
    return {"mesaj": "Cont creat cu succes"}

@app.post("/autentificare")
def autentificare(form: OAuth2PasswordRequestForm = Depends(), db: sqlite3.Connection = Depends(get_db)):
    user = db.execute("SELECT * FROM utilizatori WHERE email = ?", (form.username,)).fetchone()
    if not user or not verifica_parola(form.password, user["parola_hash"]):
        raise HTTPException(status_code=401, detail="Date incorecte (email sau parola)")
    
    token = creeaza_token(date={"sub": user["email"]})
    return {"access_token": token, "token_type": "bearer"}

# --- NOU: Cerința Bonus - Obținere date utilizator curent ---
@app.get("/utilizatori/eu")
def obtine_date_utilizator(utilizator_curent = Depends(get_utilizator_curent)):
    # Transformăm rândul din baza de date în dicționar
    date_utilizator = dict(utilizator_curent)
    # Eliminăm hash-ul parolei pentru securitate
    date_utilizator.pop("parola_hash", None)
    return date_utilizator

# ---------------------------------------------------------------------------
# 7. Endpoint-uri Sarcini (SQLite & JWT)
# ---------------------------------------------------------------------------
@app.get("/sarcini")
def obtine_sarcini(
    doar_nefinalizate: bool = False,
    db: sqlite3.Connection = Depends(get_db),
    utilizator_curent = Depends(get_utilizator_curent)
):
    query = "SELECT * FROM sarcini WHERE utilizator_id = ?"
    if doar_nefinalizate:
        query += " AND finalizata = 0"
    
    sarcini = db.execute(query, (utilizator_curent["id"],)).fetchall()
    return [dict(s) for s in sarcini]

@app.post("/sarcini", status_code=201)
def adauga_sarcina(
    sarcina: SarcinaBase, 
    db: sqlite3.Connection = Depends(get_db),
    utilizator_curent = Depends(get_utilizator_curent)
):
    # Modificat: Generăm data curentă la inserare
    data_crearii = datetime.now().isoformat()
    
    cursor = db.execute(
        "INSERT INTO sarcini (titlu, descriere, utilizator_id, data_crearii) VALUES (?, ?, ?, ?)",
        (sarcina.titlu, sarcina.descriere, utilizator_curent["id"], data_crearii)
    )
    db.commit()
    res = db.execute("SELECT * FROM sarcini WHERE id = ?", (cursor.lastrowid,)).fetchone()
    return dict(res)

@app.put("/sarcini/{sarcina_id}")
def editeaza_sarcina(
    sarcina_id: int,
    sarcina_actualizata: SarcinaActualizare,
    db: sqlite3.Connection = Depends(get_db),
    utilizator_curent = Depends(get_utilizator_curent)
):
    sarcina = db.execute("SELECT * FROM sarcini WHERE id = ? AND utilizator_id = ?", 
                          (sarcina_id, utilizator_curent["id"])).fetchone()
    if not sarcina:
        raise HTTPException(status_code=404, detail="Sarcina nu există sau nu vă aparține.")

    campuri = []
    valori = []
    
    if sarcina_actualizata.titlu is not None:
        campuri.append("titlu = ?")
        valori.append(sarcina_actualizata.titlu)
    if sarcina_actualizata.descriere is not None:
        campuri.append("descriere = ?")
        valori.append(sarcina_actualizata.descriere)
    if sarcina_actualizata.finalizata is not None:
        campuri.append("finalizata = ?")
        valori.append(1 if sarcina_actualizata.finalizata else 0)

    if campuri:
        query = f"UPDATE sarcini SET {', '.join(campuri)} WHERE id = ?"
        valori.append(sarcina_id)
        db.execute(query, tuple(valori))
        db.commit()

    res = db.execute("SELECT * FROM sarcini WHERE id = ?", (sarcina_id,)).fetchone()
    return dict(res)

# Modificat: Redenumit exact cum cere documentația (finalizeaza)
@app.patch("/sarcini/{sarcina_id}/finalizeaza")
def finalizeaza_sarcina(
    sarcina_id: int,
    db: sqlite3.Connection = Depends(get_db),
    utilizator_curent = Depends(get_utilizator_curent)
):
    sarcina = db.execute("SELECT * FROM sarcini WHERE id = ? AND utilizator_id = ?", 
                          (sarcina_id, utilizator_curent["id"])).fetchone()
    if not sarcina:
        raise HTTPException(status_code=404, detail="Sarcina nu există sau nu vă aparține.")

    db.execute("UPDATE sarcini SET finalizata = 1 WHERE id = ?", (sarcina_id,))
    db.commit()
    
    res = db.execute("SELECT * FROM sarcini WHERE id = ?", (sarcina_id,)).fetchone()
    return dict(res)

@app.delete("/sarcini/{sarcina_id}")
def sterge_sarcina(
    sarcina_id: int, 
    db: sqlite3.Connection = Depends(get_db),
    utilizator_curent = Depends(get_utilizator_curent)
):
    sarcina = db.execute("SELECT * FROM sarcini WHERE id = ? AND utilizator_id = ?", 
                          (sarcina_id, utilizator_curent["id"])).fetchone()
    if not sarcina:
        raise HTTPException(status_code=404, detail="Sarcina nu a fost găsită.")
    
    db.execute("DELETE FROM sarcini WHERE id = ?", (sarcina_id,))
    db.commit()
    return {"mesaj": "Sarcina a fost ștearsă."}

# ---------------------------------------------------------------------------
# 8. Endpoint-uri Produse (In-Memory)
# ---------------------------------------------------------------------------
inventar: List[Produs] = []

# Am comentat radacina veche care returna JSON, 
# pentru ca vrem sa afiseze HTML-ul (index.html) cand accesam radacina "/"
# @app.get("/")
# def radacina():
#     return {"status": "activ", "mesaj": "Bun venit la API!"}

@app.get("/produse")
def obtine_produse(stoc_minim: Optional[int] = None):
    if stoc_minim is not None:
        return [p for p in inventar if p.stoc < stoc_minim]
    return inventar

@app.post("/produse", status_code=201)
def adauga_produs(p: Produs):
    if any(item.id == p.id for item in inventar):
        raise HTTPException(status_code=400, detail="ID produs deja existent")
    inventar.append(p)
    return p

@app.delete("/produse/{produs_id}")
def sterge_produs(produs_id: int):
    for i, p in enumerate(inventar):
        if p.id == produs_id:
            produs_sters = inventar.pop(i)
            return produs_sters
            
    raise HTTPException(status_code=404, detail="Produsul nu a fost găsit.")

@app.put("/produse/{produs_id}")
def actualizeaza_produs(produs_id: int, produs_actualizat: Produs):
    for i, p in enumerate(inventar):
        if p.id == produs_id:
            if produs_actualizat.id != produs_id:
                raise HTTPException(status_code=400, detail="ID-ul din URL nu corespunde cu cel din body.")
            
            inventar[i] = produs_actualizat
            return inventar[i]
            
    raise HTTPException(status_code=404, detail="Produsul pe care doriți să-l actualizați nu a fost găsit.")

# ---------------------------------------------------------------------------
# 9. Health Check (Bonus)
# ---------------------------------------------------------------------------
@app.get("/healthz")
def health_check():
    return {"status": "ok"}

# ---------------------------------------------------------------------------
# 10. Servirea fișierelor statice (Frontend-ul)
# ---------------------------------------------------------------------------
# IMPORTANT: Trebuie să fie ULTIMUL rând din fișier!
app.mount("/", StaticFiles(directory="static", html=True), name="static")