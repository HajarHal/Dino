"""Outil de lecture des CG : sommaire des articles, texte d'un article, recherche.

python tools/cg_find.py <id> toc                  sommaire (lignes « Article ... » / titres)
python tools/cg_find.py <id> grep <regex> [n]     passages qui contiennent <regex> (n caractères autour)
python tools/cg_find.py <id> at <page> [start] [n] texte d'une page
"""
import re, sys
from pathlib import Path
T = Path(__file__).resolve().parent.parent / "config" / "cg_library" / "text"
iid, cmd, *a = sys.argv[1:]
txt = (T / f"{iid}.txt").read_text(encoding="utf-8")
pages = re.split(r"\n\n=== Page (\d+) ===\n", txt)[1:]
pages = {int(pages[i]): pages[i + 1] for i in range(0, len(pages), 2)}
sys.stdout.reconfigure(encoding="utf-8")
if cmd == "toc":
    for p, t in pages.items():
        for ln in t.splitlines():
            s = ln.strip()
            if re.match(r"^(art(icle)?\.?\s*\d+|titre|chapitre|section|annexe)\b", s, re.I) or (s.isupper() and 6 < len(s) < 80):
                print(f"p{p}: {s[:90]}")
elif cmd == "grep":
    n = int(a[1]) if len(a) > 1 else 200
    for p, t in pages.items():
        flat = re.sub(r"\s+", " ", t)
        for m in re.finditer(a[0], flat, re.I):
            print(f"--- p{p}: …{flat[max(0, m.start()-n):m.end()+n]}…")
elif cmd == "after":  # le passage qui commence à <regex>, n caractères, une fois par page
    n = int(a[1]) if len(a) > 1 else 800
    for p, t in pages.items():
        flat = re.sub(r"\s+", " ", t)
        last = -10**9
        for m in re.finditer(a[0], flat, re.I):
            if m.start() < last + n:
                continue
            last = m.start()
            print(f"--- p{p}: {flat[m.start():m.start()+n]}")
elif cmd == "at":
    flat = re.sub(r"\s+", " ", pages[int(a[0])])
    s = int(a[1]) if len(a) > 1 else 0
    n = int(a[2]) if len(a) > 2 else 9000
    print(flat[s:s+n])
