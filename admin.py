"""
admin.py — Outil de gestion des licences Eclipse Macro
USAGE PERSONNEL UNIQUEMENT — Ne jamais distribuer ce fichier.
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
    Presets :
      1w       → 1 semaine
      2w       → 2 semaines
      1m       → 1 mois
      2m       → 2 mois
      3m       → 3 mois
      6m       → 6 mois
      1y       → 1 an
      lifetime → Permanent (par défaut)

    Durée personnalisée (<nombre><unité>) :
      h  → heures   (ex: 12h, 36h)
      d  → jours    (ex: 3d, 45d, 0.5d)
      w  → semaines (ex: 5w, 10w)
      m  → mois     (ex: 4m, 8m)
      y  → années   (ex: 2y, 3y)

    Exemples :
      py admin.py generate 1 45d
      py admin.py generate 5 12h "@pseudo Discord"
      py admin.py generate 1 2.5d
"""

def _call(method, endpoint, payload=None):
    try:
        r = requests.request(method, f"{SERVER_URL}{endpoint}", json=payload or {}, headers=HEADERS, timeout=10)
    except requests.exceptions.ConnectionError:
        print(f"\n[ERREUR] Impossible de joindre le serveur : {SERVER_URL}")
        print("  → Vérifie ta connexion ou que le serveur Railway est bien démarré.\n")
        sys.exit(1)
    except requests.exceptions.Timeout:
        print("\n[ERREUR] Le serveur ne répond pas (timeout).\n")
        sys.exit(1)

    if r.status_code == 403:
        print("\n[ERREUR] Accès refusé (403) — ADMIN_SECRET incorrect.\n")
        sys.exit(1)
    if r.status_code == 404:
        print(f"\n[ERREUR] Route introuvable (404) — Le serveur est-il bien déployé ?\n")
        sys.exit(1)
    if r.status_code != 200:
        print(f"\n[ERREUR] Réponse inattendue : HTTP {r.status_code}\n  {r.text}\n")
        sys.exit(1)

    try:
        return r.json()
    except Exception:
        print(f"\n[ERREUR] Réponse non-JSON :\n  {r.text}\n")
        sys.exit(1)


def generate(count: int, duration: str = "lifetime", note: str = None):
    payload = {"count": count, "duration": duration}
    if note:
        payload["note"] = note
    data = _call("POST", "/admin/generate", payload)
    print(f"\n✅ {data['generated']} clé(s) générée(s) [{duration}] :\n")
    for item in data["keys"]:
        exp  = item.get("expires_at", "permanent")
        note = item.get("note") or ""
        note_str = f"   ({note})" if note else ""
        print(f"  {item['key']}   expire : {exp}{note_str}")
    print()


def list_all():
    data = _call("POST", "/admin/list")
    total   = data.get("total", 0)
    active  = data.get("active", 0)
    free    = data.get("free", 0)
    expired = data.get("expired", 0)
    print(f"\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print(f"  Total : {total}   ✅ Activées : {active}   ⬜ Libres : {free}   ❌ Expirées : {expired}")
    print(f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n")
    licenses = data.get("licenses", [])
    if not licenses:
        print("  Aucune licence en base.\n")
        return
    print(f"  {'CLÉ':<22} {'STATUT':<14} {'EXPIRE LE':<24} {'NOTE / DEVICE'}")
    print("  " + "─" * 95)
    for lic in licenses:
        if lic.get("expired"):
            status = "❌ Expirée"
        elif lic.get("activated"):
            status = "✅ Activée"
        else:
            status = "⬜ Libre"
        expires = lic.get("expires_at") or "permanent"
        note    = lic.get("note") or ""
        device  = lic.get("device_id") or "—"
        extra   = note if note else device[:30]
        print(f"  {lic.get('license_key','?'):<22} {status:<14} {expires:<24} {extra}")
    print()


def revoke(key: str):
    data = _call("POST", "/admin/revoke", {"license_key": key})
    print(f"\n🗑️  Clé révoquée : {data.get('revoked', key)}\n")


def reset_device(key: str):
    data = _call("POST", "/admin/reset_device", {"license_key": key})
    print(f"\n🔄 Device réinitialisé pour : {data.get('reset', key)}")
    print(f"   {data.get('message', '')}\n")


def set_note(key: str, note: str):
    data = _call("POST", "/admin/set_note", {"license_key": key, "note": note})
    print(f"\n📝 Note mise à jour pour {data.get('key', key)} : {data.get('note', '')}\n")


def stats():
    data = _call("POST", "/admin/stats")
    print(f"\n📊 Statistiques des licences :")
    print(f"   Total           : {data.get('total_keys', 0)}")
    print(f"   Activées valides: {data.get('active_valid', 0)}")
    print(f"   Non utilisées   : {data.get('not_used', 0)}")
    print(f"   Expirées        : {data.get('expired', 0)}\n")


def ping():
    data = _call("GET", "/ping")
    print(f"\n🟢 Serveur en ligne : {data.get('server', '')} — {data.get('ts', '')}\n")


def usage():
    print("""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Eclipse Macro — Outil d'administration des licences
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Commandes disponibles :

    py admin.py generate <nombre> [durée] [note]
        → Génère des clés d'activation
        → Ex : py admin.py generate 5 1m "@pseudo Discord"

    py admin.py list
        → Liste toutes les licences (statut, expiration, note)

    py admin.py revoke <CLÉ>
        → Supprime définitivement une licence
        → Ex : py admin.py revoke ABCD-EFGH-IJKL-MNOP

    py admin.py reset <CLÉ>
        → Réinitialise le device (permet réactivation sur autre PC)
        → Ex : py admin.py reset ABCD-EFGH-IJKL-MNOP

    py admin.py note <CLÉ> <texte>
        → Ajoute/modifie la note d'une licence
        → Ex : py admin.py note ABCD-EFGH-IJKL-MNOP "@client123"

    py admin.py stats
        → Affiche les statistiques globales

    py admin.py ping
        → Vérifie que le serveur est en ligne
""")
    print(DURATIONS_HELP)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        usage()
        sys.exit(1)

    cmd = sys.argv[1].lower()

    if cmd == "generate":
        count    = int(sys.argv[2]) if len(sys.argv) > 2 else 1
        duration = sys.argv[3] if len(sys.argv) > 3 else "lifetime"
        note     = sys.argv[4] if len(sys.argv) > 4 else None
        generate(count, duration, note)

    elif cmd == "list":
        list_all()

    elif cmd == "revoke":
        if len(sys.argv) < 3:
            print("[ERREUR] Précise la clé à révoquer.")
            sys.exit(1)
        revoke(sys.argv[2])

    elif cmd == "reset":
        if len(sys.argv) < 3:
            print("[ERREUR] Précise la clé à réinitialiser.")
            sys.exit(1)
        reset_device(sys.argv[2])

    elif cmd == "note":
        if len(sys.argv) < 4:
            print("[ERREUR] Usage : py admin.py note <CLÉ> <texte>")
            sys.exit(1)
        set_note(sys.argv[2], sys.argv[3])

    elif cmd == "stats":
        stats()

    elif cmd == "ping":
        ping()

    else:
        print(f"[ERREUR] Commande inconnue : '{cmd}'")
        usage()
