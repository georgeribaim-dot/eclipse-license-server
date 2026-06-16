import os
import secrets
import re
from datetime import datetime, timedelta
from typing import Optional

import psycopg2
import psycopg2.extras
from fastapi import FastAPI, HTTPException, Header, Depends
from pydantic import BaseModel

# ─── SECRETS ────────────────────────────────────────────────────────────────
ADMIN_SECRET  = os.getenv("ADMIN_SECRET",  "xK9#mP2qLv!")
CLIENT_SECRET = os.getenv("CLIENT_SECRET", "eclipse_client_2025")

# Railway injecte automatiquement DATABASE_URL quand tu ajoutes un PostgreSQL
DATABASE_URL  = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL manquant – ajoute un PostgreSQL sur Railway.")

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

# ─── DB ─────────────────────────────────────────────────────────────────────

def get_db():
    conn = psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        yield conn
    finally:
        conn.close()

def init_db():
    with psycopg2.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS licenses (
                    license_key TEXT PRIMARY KEY,
                    device_id   TEXT,
                    activated   BOOLEAN DEFAULT FALSE,
                    created_at  TIMESTAMPTZ DEFAULT NOW(),
                    expires_at  TIMESTAMPTZ,
                    note        TEXT
                )
            """)
        conn.commit()

init_db()

# ─── AUTH ────────────────────────────────────────────────────────────────────

def require_admin(x_api_secret: str = Header(...)):
    if x_api_secret != ADMIN_SECRET:
        raise HTTPException(status_code=403, detail="Accès refusé.")

def require_client(x_api_secret: str = Header(...)):
    if x_api_secret not in (CLIENT_SECRET, ADMIN_SECRET):
        raise HTTPException(status_code=403, detail="Accès refusé.")

# ─── UTILS ──────────────────────────────────────────────────────────────────

def _generate_key() -> str:
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "-".join(
        "".join(secrets.choice(alphabet) for _ in range(4))
        for _ in range(4)
    )

DURATIONS = {
    "1w":       timedelta(weeks=1),
    "2w":       timedelta(weeks=2),
    "1m":       timedelta(days=30),
    "2m":       timedelta(days=60),
    "3m":       timedelta(days=90),
    "6m":       timedelta(days=182),
    "1y":       timedelta(days=365),
    "lifetime": None,
}

_CUSTOM_RE = re.compile(r"^(\d+(?:\.\d+)?)(h|d|w|m|y)$", re.IGNORECASE)
_UNIT = {
    "h": lambda v: timedelta(hours=v),
    "d": lambda v: timedelta(days=v),
    "w": lambda v: timedelta(weeks=v),
    "m": lambda v: timedelta(days=v * 30),
    "y": lambda v: timedelta(days=v * 365),
}

def resolve_duration(duration: str):
    if duration in DURATIONS:
        return DURATIONS[duration]
    m = _CUSTOM_RE.match(duration.strip())
    if not m:
        raise ValueError(f"duration invalide : '{duration}'.")
    v, u = float(m.group(1)), m.group(2).lower()
    if v <= 0:
        raise ValueError("La valeur de durée doit être positive.")
    return _UNIT[u](v)

# ─── MODÈLES ────────────────────────────────────────────────────────────────

class GenerateRequest(BaseModel):
    count:    int = 1
    duration: str = "lifetime"
    note:     Optional[str] = None

class LicenseRequest(BaseModel):
    license_key: str
    device_id:   str

class RevokeRequest(BaseModel):
    license_key: str

class ResetRequest(BaseModel):
    license_key: str

class NoteRequest(BaseModel):
    license_key: str
    note: str

# ─── PING ────────────────────────────────────────────────────────────────────

@app.get("/ping")
def ping():
    return {"status": "ok", "server": "Eclipse License Server", "ts": datetime.utcnow().isoformat()}

# ─── ADMIN ───────────────────────────────────────────────────────────────────

@app.post("/admin/generate")
def generate(req: GenerateRequest, db=Depends(get_db), _=Depends(require_admin)):
    if req.count < 1 or req.count > 100:
        raise HTTPException(status_code=400, detail="count doit être entre 1 et 100.")
    try:
        delta = resolve_duration(req.duration)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    expires_at = (datetime.utcnow() + delta) if delta else None
    generated = []
    attempts  = 0
    with db.cursor() as cur:
        while len(generated) < req.count and attempts < req.count * 10:
            key = _generate_key()
            try:
                cur.execute(
                    "INSERT INTO licenses (license_key, activated, created_at, expires_at, note) "
                    "VALUES (%s, FALSE, NOW(), %s, %s)",
                    (key, expires_at, req.note)
                )
                db.commit()
                generated.append({"key": key, "expires_at": expires_at.isoformat() if expires_at else "permanent", "note": req.note})
            except psycopg2.IntegrityError:
                db.rollback()
                attempts += 1
    return {"generated": len(generated), "keys": generated}


@app.post("/admin/list")
def list_licenses(db=Depends(get_db), _=Depends(require_admin)):
    with db.cursor() as cur:
        cur.execute("SELECT license_key, activated, device_id, created_at, expires_at, note FROM licenses ORDER BY created_at DESC")
        rows = cur.fetchall()
    now = datetime.utcnow()
    result = []
    for r in rows:
        r = dict(r)
        exp = r.get("expires_at")
        r["expired"] = bool(exp and now > exp.replace(tzinfo=None))
        r["created_at"] = r["created_at"].isoformat() if r["created_at"] else None
        r["expires_at"] = exp.isoformat() if exp else "permanent"
        result.append(r)
    return {
        "total":   len(result),
        "active":  sum(1 for r in result if r["activated"] and not r["expired"]),
        "free":    sum(1 for r in result if not r["activated"]),
        "expired": sum(1 for r in result if r["expired"]),
        "licenses": result,
    }


@app.post("/admin/revoke")
def revoke(req: RevokeRequest, db=Depends(get_db), _=Depends(require_admin)):
    key = req.license_key.strip().upper()
    with db.cursor() as cur:
        cur.execute("DELETE FROM licenses WHERE license_key = %s", (key,))
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="Clé introuvable.")
    db.commit()
    return {"revoked": key}


@app.post("/admin/reset_device")
def reset_device(req: ResetRequest, db=Depends(get_db), _=Depends(require_admin)):
    key = req.license_key.strip().upper()
    with db.cursor() as cur:
        cur.execute("UPDATE licenses SET device_id = NULL, activated = FALSE WHERE license_key = %s", (key,))
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="Clé introuvable.")
    db.commit()
    return {"reset": key, "message": "Device réinitialisé."}


@app.post("/admin/set_note")
def set_note(req: NoteRequest, db=Depends(get_db), _=Depends(require_admin)):
    key = req.license_key.strip().upper()
    with db.cursor() as cur:
        cur.execute("UPDATE licenses SET note = %s WHERE license_key = %s", (req.note, key))
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="Clé introuvable.")
    db.commit()
    return {"key": key, "note": req.note}


@app.post("/admin/stats")
def stats(db=Depends(get_db), _=Depends(require_admin)):
    with db.cursor() as cur:
        cur.execute("SELECT activated, expires_at FROM licenses")
        rows = cur.fetchall()
    now = datetime.utcnow()
    total     = len(rows)
    activated = sum(1 for r in rows if r["activated"])
    expired   = sum(1 for r in rows if r["expires_at"] and now > r["expires_at"].replace(tzinfo=None))
    return {
        "total_keys":    total,
        "activated":     activated,
        "not_used":      total - activated,
        "expired":       expired,
        "active_valid":  activated - expired,
    }

# ─── CLIENT ──────────────────────────────────────────────────────────────────

@app.post("/activate")
def activate(req: LicenseRequest, db=Depends(get_db), _=Depends(require_client)):
    key = req.license_key.strip().upper()
    with db.cursor() as cur:
        cur.execute("SELECT * FROM licenses WHERE license_key = %s", (key,))
        row = cur.fetchone()

    if not row:
        return {"valid": False, "message": "Clé de licence introuvable."}

    exp = row["expires_at"]
    if exp and datetime.utcnow() > exp.replace(tzinfo=None):
        return {"valid": False, "message": "Cette clé de licence a expiré.", "expired": True}

    if not row["activated"]:
        with db.cursor() as cur:
            cur.execute("UPDATE licenses SET device_id = %s, activated = TRUE WHERE license_key = %s",
                        (req.device_id, key))
        db.commit()
        return {"valid": True, "message": "Licence activée avec succès.",
                "expires_at": exp.isoformat() if exp else "permanent"}

    if row["device_id"] == req.device_id:
        return {"valid": True, "message": "Licence déjà activée sur cet appareil.",
                "expires_at": exp.isoformat() if exp else "permanent"}

    return {"valid": False, "message": "Cette licence est déjà utilisée sur un autre appareil."}


@app.post("/verify")
def verify(req: LicenseRequest, db=Depends(get_db), _=Depends(require_client)):
    key = req.license_key.strip().upper()
    with db.cursor() as cur:
        cur.execute("SELECT * FROM licenses WHERE license_key = %s", (key,))
        row = cur.fetchone()

    if not row:
        return {"valid": False}

    exp = row["expires_at"]
    if exp and datetime.utcnow() > exp.replace(tzinfo=None):
        return {"valid": False, "expired": True}

    if row["activated"] and row["device_id"] == req.device_id:
        return {"valid": True, "expires_at": exp.isoformat() if exp else "permanent"}

    return {"valid": False}


