"""
admin.py — Outil de gestion des licences Eclipse (USAGE PERSONNEL UNIQUEMENT)
Ne jamais distribuer ce fichier ni le ADMIN_SECRET.
"""

import sys
import requests

SERVER_URL   = "https://web-production-ab129.up.railway.app"
ADMIN_SECRET = "xK9#mP2qLv!"

HEADERS = {
    "Content-Type": "application/json",
    "X-API-Secret": ADMIN_SECRET,
}

DURATIONS_HELP = """
  Durées disponibles :
    1w       → 1 semaine
    2w       → 2 semaines
    1m       → 1 mois
    2m       → 2 mois
    3m       → 3 mois
    6m       → 6 mois
    1y       → 1 an
    lifetime → Permanent (par défaut)
"""

def _call(method, endpoint, payload=None):
    """Appel HTTP avec gestion d'erreur centralisée."""
    try:
        r = requests.request(method, f"{SERVER_URL}{endpoint}", json=payload or {}, headers=HEADERS, timeout=10)
    except requests.exceptions.ConnectionError:
        print(f"\n[ERREUR] Impossible de joindre le serveur : {SERVER_URL}")
        print("  → Vérifie ta connexion internet ou que le serveur Railway est bien démarré.\n")
        sys.exit(1)
    except requests.exceptions.Timeout:
        print("\n[ERREUR] Le serveur ne répond pas (timeout).\n")
        sys.exit(1)

    if r.status_code == 403:
        print("\n[ERREUR] Accès refusé (403) — ADMIN_SECRET incorrect ou non défini sur Railway.\n")
        sys.exit(1)
    if r.status_code == 404:
        print(f"\n[ERREUR] Route introuvable (404) — Le serveur est-il bien déployé ?\n")
        sys.exit(1)
    if r.status_code != 200:
        print(f"\n[ERREUR] Réponse inattendue du serveur : HTTP {r.status_code}\n  {r.text}\n")
        sys.exit(1)

    try:
        return r.json()
    except Exception:
        print(f"\n[ERREUR] Réponse non-JSON du serveur :\n  {r.text}\n")
        sys.exit(1)

def generate(count: int, duration: str = "lifetime"):
    data = _call("POST", "/admin/generate", {"count": count, "duration": duration})
    print(f"\n✅ {data['generated']} clé(s) générée(s) [{duration}] :\n")
    for item in data["keys"]:
        exp = item.get("expires_at", "permanent")
        print(f"  {item['key']}   (expire : {exp})")
    print()

def list_all():
    data = _call("POST", "/admin/list")
    total = data.get("total", 0)
    licenses = data.get("licenses", [])
    print(f"\nTotal : {total} licence(s)\n")
    if not licenses:
        print("  Aucune licence en base.\n")
        return
    print(f"{'CLÉ':<22} {'STATUT':<12} {'EXPIRE LE':<22} {'DEVICE ID'}")
    print("─" * 100)
    for lic in licenses:
        status  = "✅ Activée" if lic.get("activated") else "⬜ Libre"
        device  = lic.get("device_id") or "—"
        expires = lic.get("expires_at") or "permanent"
        print(f"  {lic.get('license_key','?'):<20} {status:<12} {expires:<22} {device}")
    print()

def revoke(key: str):
    data = _call("POST", "/admin/revoke", {"license_key": key})
    print(f"\n🗑️  Clé révoquée : {data.get('revoked', key)}\n")

def usage():
    print("\nUsage :")
    print("  py admin.py generate <nombre> [durée]")
    print("  py admin.py list")
    print("  py admin.py revoke <CLÉ>")
    print(DURATIONS_HELP)

if __name__ == "__main__":
    if len(sys.argv) < 2:
        usage()
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == "generate":
        count    = int(sys.argv[2]) if len(sys.argv) > 2 else 1
        duration = sys.argv[3] if len(sys.argv) > 3 else "lifetime"
        generate(count, duration)

    elif cmd == "list":
        list_all()

    elif cmd == "revoke":
        if len(sys.argv) < 3:
            print("[ERREUR] Précise la clé à révoquer.")
            sys.exit(1)
        revoke(sys.argv[2])

    else:
        print(f"[ERREUR] Commande inconnue : '{cmd}'")
        usage()
