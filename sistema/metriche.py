#!/usr/bin/env python3
"""
Calcola le metriche che l'Instinct Solar (gen 1) non fornisce, partendo dai dati grezzi
scaricati da pull_attivita.py.
Uso: .venv/bin/python sistema/metriche.py [--days N] [--quiet]
Di norma non serve lanciarlo a mano: ci pensa ./aggiorna

L'orologio non ha VO2max, Training Status, Training Load, Training Effect ne Training
Readiness (verificato sul manuale ufficiale Garmin 2020: quei termini non ci sono).
Qui le ricostruiamo da cio' che c'e' davvero: FC delle attivita', RHR, body battery
al risveglio, fasi del sonno.

Calcola:
- TRIMP di Banister per attivita' (somma lap per lap, non sulla FC media dell'intera
  seduta: un fartlek e un lento con la stessa FC media hanno TRIMP diversi)
- Carico acuto (somma 7gg) e cronico (media settimanale su 28gg)
- ACWR = acuto/cronico, il rapporto dietro al "Training Status" di Garmin
- Punteggio di prontezza 0-100 da RHR vs baseline + body battery al risveglio + sonno

Salva:
- dati/giorni.csv   -> una riga per giorno, con le componenti in chiaro
"""
import argparse
import csv
import json
import math
import statistics
from datetime import date, datetime, timedelta
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent))
from percorsi import GIORNI, SPLIT, ZONE_FC, ATTIVITA_CSV, GIORNI_CSV

# Fallback usati solo se il dato reale manca.
DEFAULT_MAX_HR = 198
DEFAULT_REST_HR = 51

# Finestre di calcolo (giorni).
ACUTE_WINDOW = 7
CHRONIC_WINDOW = 28
RHR_BASELINE_WINDOW = 14

# Un giorno conta come "orologio indossato" se ha almeno 4h di sonno registrato: prima di
# fine agosto 2026 l'orologio veniva messo solo di giorno, e quei RHR (74, 110, 129 bpm)
# sono letture sporche che avvelenerebbero baseline e carico cronico.
MIN_SLEEP_SECONDS_WORN = 4 * 3600
# Sotto questa copertura la finestra cronica e' troppo bucata per dare un verdetto ACWR.
MIN_CHRONIC_COVERAGE = 0.70

# Pesi del punteggio di prontezza. Rinormalizzati sulle componenti disponibili.
READINESS_WEIGHTS = {"rhr": 0.40, "body_battery": 0.35, "sleep": 0.25}

CSV_FIELDS = [
    "date", "trimp", "trimp_acute_7d", "trimp_chronic_weekly_28d", "acwr", "acwr_zone",
    "chronic_coverage_pct", "readiness", "readiness_components", "rhr", "rhr_baseline_14d",
    "rhr_delta", "body_battery_wake", "sleep_hours", "sleep_quality_pct", "data_quality",
]


def load_json(path: Path):
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None


def get_max_hr() -> int:
    """FC massima dalle zone configurate sull'orologio."""
    zones = load_json(ZONE_FC) or []
    for z in zones:
        if z.get("sport") == "DEFAULT" and z.get("maxHeartRateUsed"):
            return int(z["maxHeartRateUsed"])
    return DEFAULT_MAX_HR


def trimp_banister(duration_min: float, avg_hr: float, rest_hr: float, max_hr: float) -> float:
    """
    TRIMP di Banister, coefficienti maschili: durata * HRr * 0.64 * e^(1.92*HRr),
    dove HRr e' la frazione di riserva cardiaca. L'esponenziale pesa l'intensita':
    10 minuti forti valgono piu' di 10 minuti lenti, che e' il punto.
    """
    reserve = max_hr - rest_hr
    if reserve <= 0 or duration_min <= 0 or not avg_hr:
        return 0.0
    hrr = min(max((avg_hr - rest_hr) / reserve, 0.0), 1.0)
    return duration_min * hrr * 0.64 * math.exp(1.92 * hrr)


def read_daily_wellness() -> dict[str, dict]:
    """Un dizionario per giorno con RHR, body battery al risveglio e sonno."""
    daily: dict[str, dict] = {}
    for day_dir in sorted(GIORNI.iterdir()):
        if not day_dir.is_dir() or not day_dir.name.startswith("20"):
            continue
        stats = load_json(day_dir / "stats.json") or {}
        sleep = (load_json(day_dir / "sleep.json") or {}).get("dailySleepDTO") or {}

        sleep_s = sleep.get("sleepTimeSeconds") or 0
        deep_rem = (sleep.get("deepSleepSeconds") or 0) + (sleep.get("remSleepSeconds") or 0)

        # bodyBatteryAtWakeTime esiste solo sui giorni con sonno registrato; il massimo
        # giornaliero e' un buon surrogato, perche' il picco cade al risveglio.
        bb_wake = stats.get("bodyBatteryAtWakeTime")
        if bb_wake is None:
            bb_wake = stats.get("bodyBatteryHighestValue")

        daily[day_dir.name] = {
            "rhr": stats.get("restingHeartRate"),
            "body_battery_wake": bb_wake,
            "sleep_hours": round(sleep_s / 3600, 2) if sleep_s else None,
            "sleep_quality_pct": round(100 * deep_rem / sleep_s, 1) if sleep_s else None,
            # La finestra di wellness e' sempre l'intera giornata, quindi non dice nulla
            # sull'uso reale: il sonno registrato invece si.
            "worn": (stats.get("sleepingSeconds") or 0) >= MIN_SLEEP_SECONDS_WORN,
        }
    return daily


def read_daily_trimp(max_hr: int, daily: dict[str, dict]) -> dict[str, float]:
    """TRIMP per giorno, sommando lap per lap ogni attivita' di quel giorno."""
    if not ATTIVITA_CSV.exists():
        return {}

    rest_hrs = [d["rhr"] for d in daily.values() if d["rhr"]]
    fallback_rest = statistics.median(rest_hrs) if rest_hrs else DEFAULT_REST_HR

    by_day: dict[str, float] = {}
    with ATTIVITA_CSV.open(newline="") as f:
        for row in csv.DictReader(f):
            day = row["date"]
            if not day:
                continue
            rest_hr = (daily.get(day) or {}).get("rhr") or fallback_rest
            by_day[day] = by_day.get(day, 0.0) + activity_trimp(row, rest_hr, max_hr)
    return by_day


def activity_trimp(row: dict, rest_hr: float, max_hr: int) -> float:
    """TRIMP di una singola attivita': dai lap se li abbiamo, altrimenti dalla FC media."""
    splits = load_json(SPLIT / f"{row['activityId']}.json") or {}
    laps = splits.get("lapDTOs") or []

    total = 0.0
    for lap in laps:
        duration_min = (lap.get("duration") or 0) / 60
        total += trimp_banister(duration_min, lap.get("averageHR"), rest_hr, max_hr)
    if total > 0:
        return total

    # Nessuno split disponibile: ricadiamo sulla media dell'attivita'.
    try:
        return trimp_banister(float(row["duration_min"]), float(row["avg_hr"]), rest_hr, max_hr)
    except (TypeError, ValueError):
        return 0.0


def acwr_zone(acwr: float | None, coverage: float) -> str:
    """Le fasce di lettura del rapporto acuto/cronico, se la baseline e' abbastanza piena."""
    if acwr is None:
        return ""
    if coverage < MIN_CHRONIC_COVERAGE:
        return "baseline-incompleta"
    if acwr < 0.8:
        return "scarico"
    if acwr <= 1.3:
        return "ottimale"
    if acwr <= 1.5:
        return "attenzione"
    return "rischio"


def band_score(value: float, best: float, worst: float) -> float:
    """Interpola 100 (a 'best') -> 0 (a 'worst'), con qualsiasi direzione."""
    if best == worst:
        return 100.0
    return max(0.0, min(100.0, 100 * (value - worst) / (best - worst)))


def sleep_score(hours: float, quality_pct: float | None) -> float:
    """
    Durata come componente principale (banda 7.5-9h = pieno), corretta dalla quota di
    sonno profondo+REM: 40% e' il riferimento tipico, sotto il 25% penalizza.
    """
    if hours >= 7.5:
        duration = 100.0
    else:
        duration = band_score(hours, best=7.5, worst=4.5)
    if quality_pct is None:
        return duration
    quality = band_score(quality_pct, best=40, worst=20)
    return 0.75 * duration + 0.25 * quality


def readiness(day: str, daily: dict[str, dict], ordered_days: list[str]) -> tuple[float | None, str]:
    """
    Punteggio 0-100 dalle tre componenti che l'orologio misura davvero. Restituisce anche
    quali componenti sono entrate nel conto: un punteggio su una sola componente vale poco.
    """
    d = daily.get(day) or {}
    scores: dict[str, float] = {}

    baseline = rhr_baseline(day, daily, ordered_days)
    if d.get("rhr") and baseline:
        # Sopra la baseline = affaticamento o stress. -2 bpm e' ottimo, +6 e' un allarme.
        scores["rhr"] = band_score(d["rhr"] - baseline, best=-2, worst=6)
    if d.get("body_battery_wake") is not None:
        scores["body_battery"] = float(d["body_battery_wake"])
    if d.get("sleep_hours"):
        scores["sleep"] = sleep_score(d["sleep_hours"], d.get("sleep_quality_pct"))

    # Con una sola componente il "punteggio" e' quella componente ribattezzata: non e'
    # una prontezza, e presentarla come tale sarebbe fuorviante.
    if len(scores) < 2:
        return None, "+".join(scores)

    total_weight = sum(READINESS_WEIGHTS[k] for k in scores)
    score = sum(scores[k] * READINESS_WEIGHTS[k] for k in scores) / total_weight
    return round(score), "+".join(sorted(scores))


def rhr_baseline(day: str, daily: dict[str, dict], ordered_days: list[str]) -> float | None:
    """
    Mediana del RHR nei 14 giorni precedenti, contando SOLO i giorni con l'orologio
    indossato la notte. Senza questo filtro la baseline includerebbe letture da 74-129 bpm
    e ogni giorno normale sembrerebbe un recupero eccezionale.
    """
    idx = ordered_days.index(day)
    window = ordered_days[max(0, idx - RHR_BASELINE_WINDOW):idx]
    values = [daily[d]["rhr"] for d in window
              if (daily.get(d) or {}).get("rhr") and daily[d]["worn"]]
    return statistics.median(values) if len(values) >= 3 else None


def chronic_coverage(day: date, daily: dict[str, dict]) -> float:
    """
    Quota dei 28 giorni della finestra cronica con l'orologio indossato. Un carico cronico
    calcolato su giorni in cui non registravamo e' sottostimato, e l'ACWR che ne esce e'
    gonfiato: va detto, non nascosto.
    """
    worn = sum(1 for i in range(CHRONIC_WINDOW)
               if (daily.get((day - timedelta(days=i)).isoformat()) or {}).get("worn"))
    return worn / CHRONIC_WINDOW


def data_quality(d: dict) -> str:
    """Etichetta onesta sull'affidabilita' della riga: senza questa si legge rumore per dato."""
    if not d.get("worn"):
        return "parziale-orologio-non-indossato-di-notte"
    if not d.get("sleep_hours"):
        return "parziale-sonno-mancante"
    if d.get("body_battery_wake") is None:
        return "parziale-body-battery-mancante"
    return "ok"


def build_rows(days_back: int | None) -> list[dict]:
    max_hr = get_max_hr()
    daily = read_daily_wellness()
    if not daily:
        return []

    trimp_by_day = read_daily_trimp(max_hr, daily)
    ordered_days = sorted(daily)

    # Le finestre di carico vanno calcolate su tutta la storia, non solo sui giorni mostrati.
    first, last = date.fromisoformat(ordered_days[0]), date.fromisoformat(ordered_days[-1])
    # days_back=None -> tutta la storia disponibile (e' cosi' che si scrive il CSV: lo
    # storico non deve mai accorciarsi perche' oggi guardiamo solo le ultime due settimane)
    cutoff = first if days_back is None else last - timedelta(days=days_back)

    rows = []
    day = first
    while day <= last:
        day_str = day.isoformat()
        acute = sum(trimp_by_day.get((day - timedelta(days=i)).isoformat(), 0.0)
                    for i in range(ACUTE_WINDOW))
        chronic_total = sum(trimp_by_day.get((day - timedelta(days=i)).isoformat(), 0.0)
                            for i in range(CHRONIC_WINDOW))
        chronic_weekly = chronic_total / (CHRONIC_WINDOW / 7)
        acwr = round(acute / chronic_weekly, 2) if chronic_weekly > 0 else None
        coverage = chronic_coverage(day, daily)

        if day >= cutoff and day_str in daily:
            d = daily[day_str]
            score, components = readiness(day_str, daily, ordered_days)
            baseline = rhr_baseline(day_str, daily, ordered_days)
            rows.append({
                "date": day_str,
                "trimp": round(trimp_by_day.get(day_str, 0.0), 1),
                "trimp_acute_7d": round(acute, 1),
                "trimp_chronic_weekly_28d": round(chronic_weekly, 1),
                "acwr": acwr,
                "acwr_zone": acwr_zone(acwr, coverage),
                "chronic_coverage_pct": round(100 * coverage),
                "readiness": score,
                "readiness_components": components,
                "rhr": d["rhr"],
                "rhr_baseline_14d": baseline,
                "rhr_delta": round(d["rhr"] - baseline, 1) if d["rhr"] and baseline else None,
                "body_battery_wake": d["body_battery_wake"],
                "sleep_hours": d["sleep_hours"],
                "sleep_quality_pct": d["sleep_quality_pct"],
                "data_quality": data_quality(d),
            })
        day += timedelta(days=1)
    return rows


def write_csv(rows: list[dict]) -> None:
    GIORNI_CSV.parent.mkdir(parents=True, exist_ok=True)
    with GIORNI_CSV.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def print_report(rows: list[dict]) -> None:
    fmt = lambda v: "-" if v in (None, "") else str(v)
    print(f"\n{'data':11} {'TRIMP':>6} {'acuto':>6} {'cronico':>8} {'ACWR':>5} {'fascia':<20} "
          f"{'cop.':>5} {'pront.':>7} {'RHR':>4} {'delta':>6} {'BB':>4} {'sonno':>6}  qualita' dato")
    for r in rows:
        print(f"{r['date']:11} {fmt(r['trimp']):>6} {fmt(r['trimp_acute_7d']):>6} "
              f"{fmt(r['trimp_chronic_weekly_28d']):>8} {fmt(r['acwr']):>5} {r['acwr_zone']:<20} "
              f"{fmt(r['chronic_coverage_pct']):>4}% {fmt(r['readiness']):>7} {fmt(r['rhr']):>4} "
              f"{fmt(r['rhr_delta']):>6} {fmt(r['body_battery_wake']):>4} "
              f"{fmt(r['sleep_hours']):>6}  {r['data_quality']}")

    usable = [r for r in rows if r["readiness"] is not None]
    if not usable:
        print("\nNessun giorno con dati sufficienti per la prontezza.")
        return

    last = usable[-1]
    print(f"\nUltimo giorno utile: {last['date']}")
    print(f"  Prontezza {last['readiness']}/100 (componenti: {last['readiness_components']})")
    if last["acwr"] is not None:
        print(f"  Carico ACWR {last['acwr']} -> {last['acwr_zone']} "
              f"(acuto {last['trimp_acute_7d']} vs cronico settimanale {last['trimp_chronic_weekly_28d']})")
    if last["acwr_zone"] == "baseline-incompleta":
        print(f"  Il carico cronico copre solo il {last['chronic_coverage_pct']}% dei 28 giorni: "
              f"l'ACWR e' gonfiato, non leggerlo come un rischio reale")
    if last["data_quality"] != "ok":
        print(f"  Attenzione: {last['data_quality']} — il punteggio vale meno del solito")


def main():
    parser = argparse.ArgumentParser(description="Metriche derivate dai dati Garmin")
    parser.add_argument("--days", type=int, default=30,
                        help="Quanti giorni mostrare a schermo (default: 30). "
                             "Il CSV contiene sempre tutta la storia.")
    parser.add_argument("--quiet", action="store_true", help="Scrive il CSV senza stampare il report")
    args = parser.parse_args()

    rows = build_rows(None)
    if not rows:
        print(f"Nessun dato in {GIORNI}. Esegui prima ./aggiorna")
        return

    write_csv(rows)
    if not args.quiet:
        print_report(rows[-args.days:])
    print(f"\n{len(rows)} giorni in {GIORNI_CSV}")


if __name__ == "__main__":
    main()
