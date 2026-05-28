"""
server/generate_license.py
───────────────────────────
Script ADMIN — à exécuter uniquement sur le serveur privé.
Les utilisateurs n'ont JAMAIS accès à ce script.

Usage :
    python generate_license.py 50        → génère 50 nouvelles clés
    python generate_license.py 1         → génère 1 clé
    python generate_license.py --list    → affiche toutes les clés et leur statut
"""

import sys
import sqlite3
import secrets
import string
from datetime import datetime

DB_PATH = "licenses.db"


def init_db(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS licenses (
            license_key TEXT PRIMARY KEY,
            device_id   TEXT,
            activated   INTEGER DEFAULT 0,
            created_at  TEXT
        )
    """)
    conn.commit()


def generate_key() -> str:
    """
    Génère une clé au format ABCD-EFGH-IJKL-MNOP
    (16 caractères alphanumériques en majuscule, sans ambiguïté : sans O/0/I/1)
    """
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # sans O, 0, I, 1
    segments = []
    for _ in range(4):
        segment = "".join(secrets.choice(alphabet) for _ in range(4))
        segments.append(segment)
    return "-".join(segments)


def generate_licenses(count: int):
    with sqlite3.connect(DB_PATH) as conn:
        init_db(conn)
        generated = []
        attempts = 0
        while len(generated) < count:
            if attempts > count * 10:
                print("[ERREUR] Trop de collisions, arrêt.")
                break
            key = generate_key()
            try:
                conn.execute(
                    "INSERT INTO licenses (license_key, activated, created_at) VALUES (?, 0, ?)",
                    (key, datetime.utcnow().isoformat())
                )
                conn.commit()
                generated.append(key)
            except sqlite3.IntegrityError:
                attempts += 1  # collision, on retente
                continue

        print(f"\n✅ {len(generated)} clé(s) générée(s) :\n")
        for k in generated:
            print(f"  {k}")
        print()


def list_licenses():
    with sqlite3.connect(DB_PATH) as conn:
        init_db(conn)
        rows = conn.execute(
            "SELECT license_key, activated, device_id, created_at FROM licenses ORDER BY created_at"
        ).fetchall()

    if not rows:
        print("Aucune licence en base.")
        return

    print(f"\n{'CLEF':<22} {'STATUT':<12} {'DEVICE ID':<68} {'CRÉÉE LE'}")
    print("─" * 130)
    for row in rows:
        key, activated, device_id, created_at = row
        status = "✅ Activée" if activated else "⬜ Libre"
        device  = device_id or "—"
        print(f"  {key:<20} {status:<12} {device:<68} {created_at}")
    print(f"\nTotal : {len(rows)} licence(s)\n")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage : python generate_license.py <nombre>")
        print("        python generate_license.py --list")
        sys.exit(1)

    if sys.argv[1] == "--list":
        list_licenses()
    else:
        try:
            count = int(sys.argv[1])
            if count < 1:
                raise ValueError
        except ValueError:
            print("[ERREUR] Argument invalide. Entrez un nombre entier positif.")
            sys.exit(1)
        generate_licenses(count)
