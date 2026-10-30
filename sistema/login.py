#!/usr/bin/env python3
"""
Login one-time a Garmin Connect. Lancialo TU, direttamente nel tuo terminale:

    .venv/bin/python sistema/login.py

Chiede email, password e (se richiesto) il codice MFA inviato da Garmin.
Al termine salva la sessione (token OAuth) in ./.garmin_tokens/ cosi'
gli script potranno riusarla senza richiedere di nuovo il login.
"""
import getpass
import sys
from pathlib import Path

from garminconnect import Garmin, GarminConnectAuthenticationError

sys.path.insert(0, str(Path(__file__).parent))
from percorsi import TOKEN as TOKENSTORE


def main():
    print("Login Garmin Connect (le credenziali restano solo su questo computer)\n")
    email = input("Email Garmin: ").strip()
    password = getpass.getpass("Password Garmin: ")

    client = Garmin(
        email=email,
        password=password,
        prompt_mfa=lambda: input("Codice MFA (ricevuto via email/SMS/app): ").strip(),
    )

    try:
        client.login(TOKENSTORE)
    except GarminConnectAuthenticationError as e:
        print(f"\nLogin fallito: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"\nLogin riuscito. Sessione salvata in {TOKENSTORE}")
    print("Da ora in poi non serve rifare il login: ./aggiorna riusa questi token.")


if __name__ == "__main__":
    main()
