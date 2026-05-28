"""
server/app.py
─────────────
Serveur privé de licences Eclipse Macro.
À déployer UNIQUEMENT chez toi — les utilisateurs n'y ont pas accès.

Lancement :
    uvicorn app:app --host 0.0.0.0 --port 443 --ssl-keyfile key.pem --ssl-certfile cert.pem

Dépendances :
    pip install fastapi uvicorn[standard] python-dotenv
"""

import os
import sqlite3
from datetime import datetime
from fastapi import FastAPI, HTTPException, Header, Depends
from pydantic import BaseModel

# ── Configuration ─────────────────────────────────────────────────────────────
API_SECRET = os.getenv("API_SECRET", "@Eclipse270107")  # ← même valeur que dans license_client.py
DB_PATH    = os.getenv("DB_PATH", "licenses.db")

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)  # désactive la doc publique


# ── Base de données ────────────────────────────────────────────────────────────

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS licenses (
                license_key TEXT PRIMARY KEY,
                device_id   TEXT,
                activated   INTEGER DEFAULT 0,
                created_at  TEXT
            )
        """)
        conn.commit()


init_db()


# ── Sécurité : vérification du secret partagé ─────────────────────────────────

def check_secret(x_api_secret: str = Header(...)):
    if x_api_secret != API_SECRET:
        raise HTTPException(status_code=403, detail="Accès refusé.")


# ── Modèles Pydantic ──────────────────────────────────────────────────────────

class LicenseRequest(BaseModel):
    license_key: str
    device_id: str


# ── Routes ────────────────────────────────────────────────────────────────────

@app.post("/activate")
def activate(req: LicenseRequest, db: sqlite3.Connection = Depends(get_db), _=Depends(check_secret)):
    """
    Active une licence :
    - Licence inconnue          → 404
    - Jamais activée            → associe au device_id, retourne valid=True
    - Déjà activée, même device → retourne valid=True
    - Déjà activée, autre device→ retourne valid=False
    """
    key = req.license_key.strip().upper()
    row = db.execute("SELECT * FROM licenses WHERE license_key = ?", (key,)).fetchone()

    if not row:
        return {"valid": False, "message": "Clé de licence introuvable."}

    if not row["activated"]:
        # Première activation : lie la clé à ce device
        db.execute(
            "UPDATE licenses SET device_id = ?, activated = 1 WHERE license_key = ?",
            (req.device_id, key)
        )
        db.commit()
        return {"valid": True, "message": "Licence activée avec succès."}

    if row["device_id"] == req.device_id:
        return {"valid": True, "message": "Licence déjà activée sur cet appareil."}

    return {"valid": False, "message": "Cette licence est déjà utilisée sur un autre appareil."}


@app.post("/verify")
def verify(req: LicenseRequest, db: sqlite3.Connection = Depends(get_db), _=Depends(check_secret)):
    """
    Vérifie si une licence est valide pour ce device_id.
    Retourne uniquement valid=True ou valid=False.
    """
    key = req.license_key.strip().upper()
    row = db.execute("SELECT * FROM licenses WHERE license_key = ?", (key,)).fetchone()

    if not row:
        return {"valid": False}

    if row["activated"] and row["device_id"] == req.device_id:
        return {"valid": True}

    return {"valid": False}
