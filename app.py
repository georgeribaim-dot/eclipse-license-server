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
                expires_at  TEXT,
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
    "1w":  timedelta(weeks=1),
    "2w":  timedelta(weeks=2),
    "1m":  timedelta(days=30),
    "2m":  timedelta(days=60),
    "3m":  timedelta(days=90),
    "6m":  timedelta(days=182),
    "1y":  timedelta(days=365),
    "lifetime": None,
}

# ─── DURÉE CUSTOM ────────────────────────────────────────────────────────────
# Permet en plus des presets ci-dessus une durée arbitraire au format <nombre><unité>
# Unités : h (heures), d (jours), w (semaines), m (mois ~30j), y (années ~365j)
# Exemples : "45d", "12h", "10w", "5m", "2y", "0.5d"
import re

_CUSTOM_DURATION_RE = re.compile(r"^(\d+(?:\.\d+)?)(h|d|w|m|y)$", re.IGNORECASE)

_UNIT_TO_TIMEDELTA = {
    "h": lambda v: timedelta(hours=v),
    "d": lambda v: timedelta(days=v),
    "w": lambda v: timedelta(weeks=v),
    "m": lambda v: timedelta(days=v * 30),
    "y": lambda v: timedelta(days=v * 365),
}

def resolve_duration(duration: str):
    """
    Retourne un timedelta (ou None pour 'lifetime') à partir d'une durée.
    Accepte :
      - les presets fixes de DURATIONS (1w, 2w, 1m, 2m, 3m, 6m, 1y, lifetime)
      - un format custom <nombre><unité> avec unité parmi h/d/w/m/y
    Lève ValueError si le format est invalide.
    """
    if duration in DURATIONS:
        return DURATIONS[duration]

    match = _CUSTOM_DURATION_RE.match(duration.strip())
    if not match:
        raise ValueError(
            f"duration invalide : '{duration}'. "
            f"Valeurs presets : {list(DURATIONS.keys())} "
            f"ou format custom <nombre><unité> avec unité parmi h/d/w/m/y (ex: 45d, 12h, 10w, 5m, 2y)."
        )

    value = float(match.group(1))
    unit = match.group(2).lower()
    if value <= 0:
        raise ValueError("La valeur de durée doit être positive.")

    return _UNIT_TO_TIMEDELTA[unit](value)

# ─── MODÈLES ────────────────────────────────────────────────────────────────
class GenerateRequest(BaseModel):
    count:    int = 1
    duration: str = "lifetime"
    note:     Optional[str] = None   # ex: "client Discord : @pseudo"

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

# ─── PING (public, santé du serveur) ─────────────────────────────────────────
@app.get("/ping")
def ping():
    return {"status": "ok", "server": "Eclipse License Server", "ts": datetime.utcnow().isoformat()}

# ─── ROUTES ADMIN (TOI SEUL) ─────────────────────────────────────────────────

@app.post("/admin/generate")
def generate(req: GenerateRequest, db: sqlite3.Connection = Depends(get_db), _=Depends(require_admin)):
    if req.count < 1 or req.count > 100:
        raise HTTPException(status_code=400, detail="count doit être entre 1 et 100.")

    try:
        delta = resolve_duration(req.duration)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    expires_at = (datetime.utcnow() + delta).isoformat() if delta else None

    generated = []
    attempts = 0
    while len(generated) < req.count and attempts < req.count * 10:
        key = _generate_key()
        try:
            db.execute(
                "INSERT INTO licenses (license_key, activated, created_at, expires_at, note) VALUES (?, 0, ?, ?, ?)",
                (key, datetime.utcnow().isoformat(), expires_at, req.note)
            )
            db.commit()
            generated.append({"key": key, "expires_at": expires_at or "permanent", "note": req.note})
        except sqlite3.IntegrityError:
            attempts += 1

    return {"generated": len(generated), "keys": generated}


@app.post("/admin/list")
def list_licenses(db: sqlite3.Connection = Depends(get_db), _=Depends(require_admin)):
    rows = db.execute(
        "SELECT license_key, activated, device_id, created_at, expires_at, note FROM licenses ORDER BY created_at DESC"
    ).fetchall()
    now = datetime.utcnow()
    result = []
    for r in rows:
        expired = False
        if r["expires_at"]:
            try:
                expired = now > datetime.fromisoformat(r["expires_at"])
            except Exception:
                pass
        result.append({**dict(r), "expired": expired})
    total_active   = sum(1 for r in result if r["activated"] and not r["expired"])
    total_free     = sum(1 for r in result if not r["activated"])
    total_expired  = sum(1 for r in result if r["expired"])
    return {
        "total": len(result),
        "active": total_active,
        "free": total_free,
        "expired": total_expired,
        "licenses": result,
    }


@app.post("/admin/revoke")
def revoke(req: RevokeRequest, db: sqlite3.Connection = Depends(get_db), _=Depends(require_admin)):
    key = req.license_key.strip().upper()
    cur = db.execute("DELETE FROM licenses WHERE license_key = ?", (key,))
    db.commit()
    if cur.rowcount == 0:
        raise HTTPException(status_code=404, detail="Clé introuvable.")
    return {"revoked": key}


@app.post("/admin/reset_device")
def reset_device(req: ResetRequest, db: sqlite3.Connection = Depends(get_db), _=Depends(require_admin)):
    """Réinitialise le device_id d'une clé (permet la réactivation sur un autre PC)."""
    key = req.license_key.strip().upper()
    cur = db.execute(
        "UPDATE licenses SET device_id = NULL, activated = 0 WHERE license_key = ?", (key,)
    )
    db.commit()
    if cur.rowcount == 0:
        raise HTTPException(status_code=404, detail="Clé introuvable.")
    return {"reset": key, "message": "Device réinitialisé. La clé peut être réactivée sur un autre appareil."}


@app.post("/admin/set_note")
def set_note(req: NoteRequest, db: sqlite3.Connection = Depends(get_db), _=Depends(require_admin)):
    """Ajoute ou modifie la note d'une clé (ex: pseudo Discord du client)."""
    key = req.license_key.strip().upper()
    cur = db.execute("UPDATE licenses SET note = ? WHERE license_key = ?", (req.note, key))
    db.commit()
    if cur.rowcount == 0:
        raise HTTPException(status_code=404, detail="Clé introuvable.")
    return {"key": key, "note": req.note}


@app.post("/admin/stats")
def stats(db: sqlite3.Connection = Depends(get_db), _=Depends(require_admin)):
    """Statistiques globales des licences."""
    rows = db.execute("SELECT activated, expires_at FROM licenses").fetchall()
    now = datetime.utcnow()
    total       = len(rows)
    activated   = sum(1 for r in rows if r["activated"])
    not_used    = total - activated
    expired     = 0
    for r in rows:
        if r["expires_at"]:
            try:
                if now > datetime.fromisoformat(r["expires_at"]):
                    expired += 1
            except Exception:
                pass
    return {
        "total_keys": total,
        "activated":  activated,
        "not_used":   not_used,
        "expired":    expired,
        "active_valid": activated - expired,
    }


# ─── ROUTES CLIENT (distribué dans la macro) ─────────────────────────────────

@app.post("/activate")
def activate(req: LicenseRequest, db: sqlite3.Connection = Depends(get_db), _=Depends(require_client)):
    key = req.license_key.strip().upper()
    row = db.execute("SELECT * FROM licenses WHERE license_key = ?", (key,)).fetchone()

    if not row:
        return {"valid": False, "message": "Clé de licence introuvable."}

    if row["expires_at"]:
        exp = datetime.fromisoformat(row["expires_at"])
        if datetime.utcnow() > exp:
            return {"valid": False, "message": "Cette clé de licence a expiré.", "expired": True}

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
