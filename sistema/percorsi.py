#!/usr/bin/env python3
"""
Un posto solo per sapere dove sta ogni cosa. Tutti gli script importano da qui:
se una cartella cambia nome, si cambia una riga sola.
"""
import sys
from pathlib import Path

RADICE = Path(__file__).resolve().parent.parent

# Credenziali (fuori da git, vedi .gitignore)
TOKEN = str(RADICE / ".garmin_tokens")

# Dati
DATI = RADICE / "dati"
GARMIN = DATI / "garmin"          # grezzi, cosi' come li manda Garmin
GIORNI = GARMIN / "giorni"        # una cartella per data: stats, HR, sonno, stress
PERIODI = GARMIN / "periodi"      # scaricamenti per intervallo di date
SPLIT = GARMIN / "split"          # split (lap) delle corse, uno per attivita'
SERIE = GARMIN / "serie"          # serie/esercizi delle sedute di forza
ZONE_FC = GARMIN / "zone-fc-orologio.json"

# Tabelle derivate: generate dagli script, non si toccano a mano
ATTIVITA_CSV = DATI / "attivita.csv"    # ogni attivita' registrata, una riga
FORZA_CSV = DATI / "forza.csv"          # sedute non di corsa, con serie ed esercizi
GIORNI_CSV = DATI / "giorni.csv"        # una riga al giorno: carico, ACWR, prontezza


def collegati():
    """Client Garmin autenticato con la sessione salvata da login.py."""
    from garminconnect import Garmin, GarminConnectAuthenticationError
    client = Garmin()
    try:
        client.login(TOKEN)
    except (GarminConnectAuthenticationError, FileNotFoundError) as e:
        print(f"Sessione Garmin non valida ({e}).\n"
              "Esegui nel tuo terminale: .venv/bin/python sistema/login.py",
              file=sys.stderr)
        sys.exit(1)
    return client
