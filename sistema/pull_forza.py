#!/usr/bin/env python3
"""
Estrae da Garmin Connect le attivita' NON di corsa (corpo libero, forza, cardio indoor,
beach volley, 'other'...) degli ultimi N giorni, con le serie/esercizi registrati se ci sono.
Uso: .venv/bin/python sistema/pull_forza.py [--days N]
Di norma non serve lanciarlo a mano: ci pensa ./aggiorna

Salva:
- dati/garmin/periodi/workouts_<da>_<a>.json  -> elenco completo attivita' non-corsa
- dati/garmin/serie/<activityId>.json         -> esercizi e serie (solo se Garmin li ha)
- dati/forza.csv                              -> una riga per attivita'
"""
import argparse, csv, json, sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from percorsi import PERIODI, SERIE, FORZA_CSV, collegati
RUN_TYPES = {"running", "trail_running", "treadmill_running", "track_running"}
FIELDS = ["activityId","date","name","type","duration_min","avg_hr","max_hr","calories",
          "aerobic_te","anaerobic_te","n_sets","exercises"]

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--days", type=int, default=730)
    a = ap.parse_args()
    end = date.today(); start = end - timedelta(days=a.days)
    c = collegati()
    print(f"Attivita' dal {start} al {end}...")
    acts = c.get_activities_by_date(start.isoformat(), end.isoformat())
    non_run = [x for x in acts if (x.get("activityType") or {}).get("typeKey") not in RUN_TYPES]
    print(f"  {len(acts)} totali, {len(non_run)} non di corsa")
    PERIODI.mkdir(parents=True, exist_ok=True); SERIE.mkdir(parents=True, exist_ok=True)
    (PERIODI / f"workouts_{start}_{end}.json").write_text(json.dumps(non_run, indent=2, ensure_ascii=False))
    rows = []
    for x in non_run:
        aid = x["activityId"]; n_sets = 0; ex_names = []
        p = SERIE / f"{aid}.json"
        try:
            sets = p.exists() and json.loads(p.read_text()) or c.get_activity_exercise_sets(str(aid))
            p.write_text(json.dumps(sets, indent=2, ensure_ascii=False))
            for s in (sets or {}).get("exerciseSets", []) or []:
                if s.get("setType") == "ACTIVE":
                    n_sets += 1
                    for e in s.get("exercises", []) or []:
                        nm = e.get("name") or e.get("category")
                        if nm and nm not in ex_names: ex_names.append(nm)
        except Exception as e:
            pass
        rows.append({
            "activityId": aid, "date": (x.get("startTimeLocal") or "")[:10],
            "name": x.get("activityName"), "type": (x.get("activityType") or {}).get("typeKey"),
            "duration_min": round((x.get("duration") or 0)/60, 1),
            "avg_hr": x.get("averageHR"), "max_hr": x.get("maxHR"), "calories": x.get("calories"),
            "aerobic_te": x.get("aerobicTrainingEffect"), "anaerobic_te": x.get("anaerobicTrainingEffect"),
            "n_sets": n_sets, "exercises": "|".join(ex_names),
        })
    rows.sort(key=lambda r: r["date"])
    with FORZA_CSV.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS); w.writeheader(); w.writerows(rows)
    print(f"  scritte {len(rows)} righe in {FORZA_CSV}")

if __name__ == "__main__": main()
