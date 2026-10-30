# My week OS

The system I use to manage my week: work, a new project and training for my first marathon
(Torino, November 2026).
It pulls my data from Garmin Connect, computes the numbers my watch doesn't give me, and I use
it with Claude as a coach: every week we look at the data, adjust the plan and put it on my
calendar.

The code and comments are in Italian, because I wrote it for myself.

## Why

I train with a Garmin Instinct Solar (1st gen). It records heart rate, sleep, resting HR and body
battery, but it has no VO2max, no Training Load, no Training Status and no Training Readiness. Those
are exactly the numbers you need to decide whether to push or rest. So I calculate them myself from
the raw data.

## What it does

`./aggiorna` runs everything in one go:

1. **Downloads** activities, laps, strength sets, daily stats, heart rate, sleep, stress and body
   battery from Garmin Connect (`sistema/pull_attivita.py`, `sistema/pull_forza.py`).
2. **Computes** (`sistema/metriche.py`):
   - Banister TRIMP for every session, lap by lap, so intervals and easy runs with the same
     average HR don't get the same load
   - acute load (7 days), chronic load (28 days) and their ratio (ACWR)
   - a 0-100 readiness score from resting HR vs my 14-day baseline, body battery at wake-up and
     sleep
3. **Checks the data before I trust it**: how old the last watch sync is (`freschezza.py`), how
   much of the 28-day window was actually recorded, and a quality label on every day. Before late
   August I only wore the watch during the day, and those nights would have ruined the baseline.
4. **Checks the docs**: every link between plans, history and references must point to something
   that exists (`controlla.py`).

The output is `dati/giorni.csv`: one row per day, with load, ACWR, readiness and every component.

## How I use it

The `piani/` (plans), `storico/` (history) and `riferimenti/` (references) folders are where the
plan lives in Markdown. In my private copy Claude reads them together with the CSVs, compares
what was planned with what actually happened, and updates the next week's calendar events. Some
rules I learned the hard way are written in `CLAUDE.md.example`.

My personal data, plans and history are not in this repo. The folders are here empty, so you can
see the structure.

## Run it

```bash
python3 -m venv .venv
.venv/bin/pip install -r sistema/requirements.txt
.venv/bin/python sistema/login.py   # Garmin email, password and MFA, once
./aggiorna                          # last 14 days
./aggiorna 30                       # last 30 days
```

The Garmin session is saved in `.garmin_tokens/` and the data in `dati/`, both ignored by git.
