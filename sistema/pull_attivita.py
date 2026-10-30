#!/usr/bin/env python3
"""
Estrae dati da Garmin Connect usando la sessione salvata da login.py.
Uso: .venv/bin/python sistema/pull_attivita.py [--days N]
Di norma non serve lanciarlo a mano: ci pensa ./aggiorna

Salva:
- dati/garmin/giorni/AAAA-MM-GG/*.json  -> per giorno: stats, HR, sonno, training status, stress
- dati/garmin/periodi/*.json            -> attivita', body battery e stress del periodo
- dati/garmin/zone-fc-orologio.json     -> le zone FC configurate sull'orologio (sbagliate:
  vedi riferimenti/zone-fc.md)
- dati/garmin/split/<id>.json           -> split (lap) per attivita', solo per le nuove
- dati/attivita.csv                     -> una riga per attivita' (dedup su activityId)

NB: max_metrics, training_readiness e body_battery_events NON si scaricano: l'Instinct
Solar gen 1 non li produce, restituivano sempre {} (erano 597 file vuoti).
"""
import argparse
import csv
import json
import math
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from percorsi import DATI, GIORNI, PERIODI, SPLIT, ZONE_FC, ATTIVITA_CSV, collegati

CSV_FIELDS = [
    "activityId", "date", "name", "type", "distance_km", "duration_min",
    "avg_pace_min_per_km", "avg_hr", "max_hr", "elevation_gain_m",
    "calories", "aerobic_te", "anaerobic_te",
]


def dump_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False))


def pull_daily(client, day: date) -> None:
    day_str = day.isoformat()
    day_dir = GIORNI / day_str
    fetchers = {
        "stats": lambda: client.get_stats(day_str),
        "heart_rate": lambda: client.get_heart_rates(day_str),
        "sleep": lambda: client.get_sleep_data(day_str),
        "training_status": lambda: client.get_training_status(day_str),
        "stress": lambda: client.get_stress_data(day_str),
    }
    for name, fetch in fetchers.items():
        try:
            dump_json(day_dir / f"{name}.json", fetch())
        except Exception as e:
            print(f"  [{day_str}] {name} non disponibile: {e}")


def activity_to_row(a: dict) -> dict:
    distance_m = a.get("distance") or 0
    duration_s = a.get("duration") or 0
    distance_km = distance_m / 1000
    pace = (duration_s / 60) / distance_km if distance_km > 0 else None
    return {
        "activityId": a.get("activityId"),
        "date": (a.get("startTimeLocal") or "")[:10],
        "name": a.get("activityName"),
        "type": (a.get("activityType") or {}).get("typeKey"),
        "distance_km": round(distance_km, 2),
        "duration_min": round(duration_s / 60, 1),
        "avg_pace_min_per_km": round(pace, 2) if pace else None,
        "avg_hr": a.get("averageHR"),
        "max_hr": a.get("maxHR"),
        "elevation_gain_m": a.get("elevationGain"),
        "calories": a.get("calories"),
        "aerobic_te": a.get("aerobicTrainingEffect"),
        "anaerobic_te": a.get("anaerobicTrainingEffect"),
    }


def pull_new_activity_splits(client, activities: list[dict]) -> int:
    """Scarica gli split solo per le attivita' che non li abbiamo gia' salvati."""
    SPLIT.mkdir(parents=True, exist_ok=True)
    added = 0
    for a in activities:
        activity_id = a.get("activityId")
        out_path = SPLIT / f"{activity_id}.json"
        if out_path.exists():
            continue
        try:
            dump_json(out_path, client.get_activity_splits(str(activity_id)))
            added += 1
        except Exception as e:
            print(f"  splits attivita' {activity_id} non disponibili: {e}")
    return added


def append_activities_csv(rows: list[dict]) -> int:
    existing_ids = set()
    if ATTIVITA_CSV.exists():
        with ATTIVITA_CSV.open(newline="") as f:
            existing_ids = {r["activityId"] for r in csv.DictReader(f)}

    new_rows = [r for r in rows if str(r["activityId"]) not in existing_ids]
    if not new_rows:
        return 0

    write_header = not ATTIVITA_CSV.exists()
    ATTIVITA_CSV.parent.mkdir(parents=True, exist_ok=True)
    with ATTIVITA_CSV.open("a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        if write_header:
            writer.writeheader()
        writer.writerows(new_rows)
    return len(new_rows)


def main():
    parser = argparse.ArgumentParser(description="Estrae dati Garmin Connect")
    parser.add_argument("--days", type=int, default=14, help="Quanti giorni indietro (default: 14)")
    args = parser.parse_args()

    end = date.today()
    start = end - timedelta(days=args.days)

    print(f"Login con sessione salvata...")
    client = collegati()
    print(f"Login ok. Estraggo dati dal {start} al {end}...")

    print("Attivita'...")
    activities = client.get_activities_by_date(start.isoformat(), end.isoformat())
    dump_json(PERIODI / f"activities_{start}_{end}.json", activities)
    rows = [activity_to_row(a) for a in activities]
    added = append_activities_csv(rows)
    print(f"  {len(activities)} attivita' trovate, {added} nuove aggiunte a {ATTIVITA_CSV.name}")

    print("Split per le attivita' nuove...")
    n_splits = pull_new_activity_splits(client, activities)
    print(f"  {n_splits} attivita' con split scaricati")

    print("Body battery...")
    try:
        bb = []
        chunk_start = start
        while chunk_start <= end:
            chunk_end = min(chunk_start + timedelta(days=27), end)
            bb.extend(client.get_body_battery(chunk_start.isoformat(), chunk_end.isoformat()))
            chunk_start = chunk_end + timedelta(days=1)
        dump_json(PERIODI / f"body_battery_{start}_{end}.json", bb)
    except Exception as e:
        print(f"  non disponibile: {e}")

    print("Zone di frequenza cardiaca (config attuale)...")
    try:
        dump_json(ZONE_FC, client.get_heart_rate_zones())
    except Exception as e:
        print(f"  non disponibile: {e}")

    print("Stress settimanale...")
    try:
        weeks = max(1, math.ceil(args.days / 7))
        weekly = client.get_weekly_stress(end.isoformat(), weeks=weeks)
        dump_json(PERIODI / f"weekly_stress_{start}_{end}.json", weekly)
    except Exception as e:
        print(f"  non disponibile: {e}")

    print("Dati giornalieri (stats, FC, sonno, training status, stress)...")
    day = start
    while day <= end:
        pull_daily(client, day)
        day += timedelta(days=1)

    print("\nFatto.")


if __name__ == "__main__":
    main()
