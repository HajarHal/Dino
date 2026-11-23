"""Liste les libellés de garantie non reconnus (à ajouter dans config/taxonomy.yaml), les plus fréquents d'abord.

    python tools/unrecognised.py
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from ica import ai_classifier, unrecognised  # noqa: E402

folder = Path(os.environ.get("ICA_DATA_DIR") or ROOT / "data")
rows = sorted(unrecognised.load(folder).values(), key=lambda e: -len(e["contracts"]))
sys.stdout.reconfigure(encoding="utf-8")
if not rows:
    print("Aucun libellé non reconnu.")
for e in rows:
    print(f"{len(e['contracts']):>3} contrat(s)  {e['label']}  [{', '.join(e['insurers']) or '?'}]  vu le {e.get('last_seen', e['first_seen'])}")

ai = ai_classifier.load(folder)
if ai:
    print("\nClassements IA (à reporter dans config/taxonomy.yaml une fois confirmés) :")
    for e in sorted(ai.values(), key=lambda e: e.get("status", "")):
        what = e.get("code") or "-"
        why = f"p. {e['page']}" if e.get("page") else e.get("reason", "")
        print(f"  {e.get('status', '?'):<10} {e['label']}  ->  {what}  [{e.get('insurer')}]  {why}")
