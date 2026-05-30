import os
import secrets
import sqlite3
from datetime import datetime, timedelta
from fastapi import FastAPI, HTTPException, Header, Depends
from pydantic import BaseModel
from typing import Optional

# ─── SECRETS ────────────────────────────────────────────────────────────────
# ADMIN_SECRET : connu UNIQUEMENT de toi, jamais distribué dans la macro
# CLIENT_SECRET : connu du client (lecture seule : activate + verify)
ADMIN_SECRET  = os.getenv("ADMIN_SECRET",  "xK9#mP2qLv!")
CLIENT_SECRET = os.getenv("CLIENT_SECRET", "eclipse_client_2025")
DB_PATH       = os.getenv("DB_PATH", "licenses.db")

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

# ─── DB ─────────────────────────────────────────────────────────────────────
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
                created_at  TEXT,
                expires_at  TEXT
            )
        """)
        conn.commit()

init_db()

# ─── AUTH ────────────────────────────────────────────────────────────────────
def require_admin(x_api_secret: str = Header(...)):
    if x_api_secret != ADMIN_SECRET:
        raise HTTPException(status_code=403, detail="Accès refusé.")

def require_client(x_api_secret: str = Header(...)):
    if x_api_secret != CLIENT_SECRET:
        raise HTTPException(status_code=403, detail="Accès refusé.")

# ─── UTILS ──────────────────────────────────────────────────────────────────
def _generate_key() -> str:
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "-".join(
        "".join(secrets.choice(alphabet) for _ in range(4))
        for _ in range(4)
    )

DURATIONS = {
    "1w":  timedelta(weeks=1),
    "2w":  timedelta(weeks=2),
    "1m":  timedelta(days=30),
    "2m":  timedelta(days=60),
    "3m":  timedelta(days=90),
    "6m":  timedelta(days=182),
    "1y":  timedelta(days=365),
    "lifetime": None,
}

# ─── MODÈLES ────────────────────────────────────────────────────────────────
class GenerateRequest(BaseModel):
    count:    int = 1
    duration: str = "lifetime"  # "1w", "2w", "1m", "2m", "3m", "6m", "1y", "lifetime"

class LicenseRequest(BaseModel):
    license_key: str
    device_id:   str

# ─── ROUTES ADMIN (TOI SEUL) ─────────────────────────────────────────────────
@app.post("/admin/generate")
def generate(req: GenerateRequest, db: sqlite3.Connection = Depends(get_db), _=Depends(require_admin)):
    if req.count < 1 or req.count > 100:
        raise HTTPException(status_code=400, detail="count doit être entre 1 et 100.")
    if req.duration not in DURATIONS:
        raise HTTPException(status_code=400, detail=f"duration invalide. Valeurs : {list(DURATIONS.keys())}")

    delta = DURATIONS[req.duration]
    expires_at = (datetime.utcnow() + delta).isoformat() if delta else None

    generated = []
    attempts = 0
    while len(generated) < req.count and attempts < req.count * 10:
        key = _generate_key()
        try:
            db.execute(
                "INSERT INTO licenses (license_key, activated, created_at, expires_at) VALUES (?, 0, ?, ?)",
                (key, datetime.utcnow().isoformat(), expires_at)
            )
            db.commit()
            generated.append({"key": key, "expires_at": expires_at or "permanent"})
        except sqlite3.IntegrityError:
            attempts += 1

    return {"generated": len(generated), "keys": generated}

@app.post("/admin/list")
def list_licenses(db: sqlite3.Connection = Depends(get_db), _=Depends(require_admin)):
    rows = db.execute(
        "SELECT license_key, activated, device_id, created_at, expires_at FROM licenses ORDER BY created_at"
    ).fetchall()
    return {"total": len(rows), "licenses": [dict(r) for r in rows]}

@app.post("/admin/revoke")
def revoke(body: dict, db: sqlite3.Connection = Depends(get_db), _=Depends(require_admin)):
    key = body.get("license_key", "").strip().upper()
    db.execute("DELETE FROM licenses WHERE license_key = ?", (key,))
    db.commit()
    return {"revoked": key}

# ─── ROUTES CLIENT (distribué dans la macro) ─────────────────────────────────
@app.post("/activate")
def activate(req: LicenseRequest, db: sqlite3.Connection = Depends(get_db), _=Depends(require_client)):
    key = req.license_key.strip().upper()
    row = db.execute("SELECT * FROM licenses WHERE license_key = ?", (key,)).fetchone()

    if not row:
        return {"valid": False, "message": "Clé de licence introuvable."}

    # Vérification expiration
    if row["expires_at"]:
        exp = datetime.fromisoformat(row["expires_at"])
        if datetime.utcnow() > exp:
            return {"valid": False, "message": "Cette clé de licence a expiré."}

    if not row["activated"]:
        db.execute(
            "UPDATE licenses SET device_id = ?, activated = 1 WHERE license_key = ?",
            (req.device_id, key)
        )
        db.commit()
        return {"valid": True, "message": "Licence activée avec succès.", "expires_at": row["expires_at"] or "permanent"}

    if row["device_id"] == req.device_id:
        return {"valid": True, "message": "Licence déjà activée sur cet appareil.", "expires_at": row["expires_at"] or "permanent"}

    return {"valid": False, "message": "Cette licence est déjà utilisée sur un autre appareil."}

@app.post("/verify")
def verify(req: LicenseRequest, db: sqlite3.Connection = Depends(get_db), _=Depends(require_client)):
    key = req.license_key.strip().upper()
    row = db.execute("SELECT * FROM licenses WHERE license_key = ?", (key,)).fetchone()

    if not row:
        return {"valid": False}

    if row["expires_at"]:
        exp = datetime.fromisoformat(row["expires_at"])
        if datetime.utcnow() > exp:
            return {"valid": False, "expired": True}

    if row["activated"] and row["device_id"] == req.device_id:
        return {"valid": True, "expires_at": row["expires_at"] or "permanent"}

    return {"valid": False}
