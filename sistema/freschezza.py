#!/usr/bin/env python3
"""
Dice quanto sono freschi i dati appena scaricati. Esiste per un motivo solo: l'orologio
sincronizza a intervalli, e i dati "di oggi" sono spesso fermi alla notte. Analizzare
senza saperlo porta a conclusioni sbagliate.
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from percorsi import GIORNI, ATTIVITA_CSV, GIORNI_CSV


def ultimo_sync() -> datetime | None:
    for giorno in sorted(GIORNI.iterdir(), reverse=True):
        stats = giorno / "stats.json"
        if not stats.exists():
            continue
        ts = (json.loads(stats.read_text()) or {}).get("lastSyncTimestampGMT")
        if ts:
            # Garmin manda l'ora UTC senza fuso esplicito: glielo attacchiamo noi
            quando = datetime.fromisoformat(ts.replace("Z", ""))
            return quando.replace(tzinfo=timezone.utc)
    return None


def main():
    sync = ultimo_sync()
    if sync is None:
        print("⚠  Nessun sync trovato: l'orologio non ha ancora caricato niente.")
        return
    ore = (datetime.now(timezone.utc) - sync).total_seconds() / 3600
    stato = "✓" if ore < 12 else "⚠"
    print(f"{stato}  Ultimo sync dell'orologio: {sync:%d/%m alle %H:%M} UTC "
          f"({ore:.0f}h fa)")
    if ore >= 12:
        print("   I dati di oggi possono essere incompleti: sincronizza il Garmin "
              "prima di trarre conclusioni.")
    for nome, path in [("attività", ATTIVITA_CSV), ("giorni", GIORNI_CSV)]:
        if path.exists():
            righe = sum(1 for _ in path.open()) - 1
            print(f"   {path.name}: {righe} {nome}")


if __name__ == "__main__":
    main()
