"""
server/app.py
─────────────
Serveur privé de licences Eclipse Macro.
À déployer UNIQUEMENT chez toi — les utilisateurs n'y ont pas accès.
"""

import os
import secrets
import sqlite3
from datetime import datetime
from fastapi import FastAPI, HTTPException, Header, Depends
from pydantic import BaseModel

# ── Configuration ─────────────────────────────────────────────────────────────
API_SECRET = os.getenv("API_SECRET", "@Eclipse270107")
DB_PATH    = os.getenv("DB_PATH", "licenses.db")

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)


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


# ── Sécurité ──────────────────────────────────────────────────────────────────

def check_secret(x_api_secret: str = Header(...)):
    if x_api_secret != API_SECRET:
        raise HTTPException(status_code=403, detail="Accès refusé.")


# ── Génération de clé ─────────────────────────────────────────────────────────

def _generate_key() -> str:
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    segments = []
    for _ in range(4):
        segment = "".join(secrets.choice(alphabet) for _ in range(4))
        segments.append(segment)
    return "-".join(segments)


# ── Modèles ───────────────────────────────────────────────────────────────────

class LicenseRequest(BaseModel):
    license_key: str
    device_id: str

class GenerateRequest(BaseModel):
    count: int = 1


# ── Routes ────────────────────────────────────────────────────────────────────

@app.post("/admin/generate")
def generate(req: GenerateRequest, db: sqlite3.Connection = Depends(get_db), _=Depends(check_secret)):
    """Génère N nouvelles clés de licence (admin uniquement)."""
    if req.count < 1 or req.count > 100:
        raise HTTPException(status_code=400, detail="count doit être entre 1 et 100.")
    generated = []
    attempts = 0
    while len(generated) < req.count and attempts < req.count * 10:
        key = _generate_key()
        try:
            db.execute(
                "INSERT INTO licenses (license_key, activated, created_at) VALUES (?, 0, ?)",
                (key, datetime.utcnow().isoformat())
            )
            db.commit()
            generated.append(key)
        except sqlite3.IntegrityError:
            attempts += 1
    return {"generated": len(generated), "keys": generated}


@app.post("/admin/list")
def list_licenses(db: sqlite3.Connection = Depends(get_db), _=Depends(check_secret)):
    """Liste toutes les licences et leur statut (admin uniquement)."""
    rows = db.execute(
        "SELECT license_key, activated, device_id, created_at FROM licenses ORDER BY created_at"
    ).fetchall()
    return {"total": len(rows), "licenses": [dict(r) for r in rows]}


@app.post("/activate")
def activate(req: LicenseRequest, db: sqlite3.Connection = Depends(get_db), _=Depends(check_secret)):
    key = req.license_key.strip().upper()
    row = db.execute("SELECT * FROM licenses WHERE license_key = ?", (key,)).fetchone()

    if not row:
        return {"valid": False, "message": "Clé de licence introuvable."}

    if not row["activated"]:
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
    key = req.license_key.strip().upper()
    row = db.execute("SELECT * FROM licenses WHERE license_key = ?", (key,)).fetchone()

    if not row:
        return {"valid": False}

    if row["activated"] and row["device_id"] == req.device_id:
        return {"valid": True}

    return {"valid": False}
