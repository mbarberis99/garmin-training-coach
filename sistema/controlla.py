#!/usr/bin/env python3
"""
Controlla che ogni rimando dentro i documenti porti davvero da qualche parte: file
che esistono e titoli che esistono. Un link rotto e' peggio di nessun link, perche'
sembra autorevole. Si lancia da solo dentro ./aggiorna.
"""
import re
import sys
import unicodedata
from pathlib import Path

RADICE = Path(__file__).resolve().parent.parent
CARTELLE = ["piani", "storico", "riferimenti"]
LINK = re.compile(r"\[([^\]]*)\]\(([^)\s]+)\)")


def ancora(titolo: str) -> str:
    """Stessa regola di GitHub: minuscolo, via la punteggiatura, spazi in trattini."""
    t = titolo.strip().lower()
    t = "".join(c for c in t if c.isalnum() or c in " -_" or unicodedata.combining(c))
    return re.sub(r"\s+", "-", t.strip())


def documenti() -> list[Path]:
    doc = sorted(RADICE.glob("*.md"))
    for c in CARTELLE:
        doc += sorted((RADICE / c).glob("*.md"))
    return doc


def main():
    ancore = {}
    for f in documenti():
        ancore[f] = {ancora(r.lstrip("# ")) for r in f.read_text().split("\n")
                     if r.startswith("#")}

    rotti = []
    for f in documenti():
        for n, riga in enumerate(f.read_text().split("\n"), 1):
            for testo, destinazione in LINK.findall(riga):
                if destinazione.startswith(("http", "mailto:")):
                    continue
                percorso, _, frammento = destinazione.partition("#")
                bersaglio = (f.parent / percorso).resolve() if percorso else f
                if not bersaglio.exists():
                    rotti.append(f"{f.relative_to(RADICE)}:{n}  file inesistente → {destinazione}")
                elif frammento and bersaglio.suffix == ".md" and frammento not in ancore.get(bersaglio, set()):
                    rotti.append(f"{f.relative_to(RADICE)}:{n}  titolo inesistente → {destinazione}")

    if rotti:
        print(f"✗  {len(rotti)} rimandi rotti:")
        for r in rotti:
            print(f"   {r}")
        sys.exit(1)
    print(f"✓  Rimandi verificati: tutti validi ({len(documenti())} documenti)")


if __name__ == "__main__":
    main()
