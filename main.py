import requests
import pandas as pd
import matplotlib
matplotlib.use("Agg")          # non-interactive backend so map save works cleanly
import matplotlib.pyplot as plt
import folium
import os
import webbrowser
from datetime import datetime
from math import ceil

# =========================
# CONFIG
# =========================
GOOGLE_API_KEY = "AIzaSyD9WIwKJ1CjKOg_l9py6oUufN1TOj_cPPc"
ORS_API_KEY    = "eyJvcmciOiI1YjNjZTM1OTc4NTExMTAwMDFjZjYyNDgiLCJpZCI6ImMzYjliYzczOWE4MjQ3NDE4NjRlOTM2ODliZWUxNWE2IiwiaCI6Im11cm11cjY0In0="

# =========================
# LOAD BUS DATA
# =========================
def load_bus_data():
    try:
        df = pd.read_csv("Final_Cleaned_Bus_Routes.csv")
        df["From"] = df["From"].str.strip()
        df["To"]   = df["To"].str.strip()
        return df
    except FileNotFoundError:
        print("Warning: Final_Cleaned_Bus_Routes.csv not found. Bus fares will be estimated.")
        return pd.DataFrame(columns=["From", "To", "Fare"])

bus_data   = load_bus_data()
all_places = sorted(set(bus_data["From"].tolist() + bus_data["To"].tolist()))

# =========================
# RUSH HOUR CHECK
# =========================
def check_rush_hour():
    now    = datetime.now()
    hour   = now.hour
    minute = now.minute
    if hour in (8, 9) or (hour == 10 and minute <= 30):
        print("\n[Warning] Rush hour (8:00–10:30 AM). High traffic is possible.\n")
    elif 16 <= hour < 20:
        print("\n[Warning] Rush hour (4:00–8:00 PM). High traffic is possible.\n")
    elif 10 <= hour < 16:
        print("\n[Info] Traffic is generally moderate at this time.\n")
    else:
        print("\n[Info] Traffic is generally low at this time.\n")

# =========================
# INPUT HELPER
# =========================
def ask(prompt, kind=str, valid=None, min_val=None, max_val=None, allow_empty=False):
    while True:
        raw = input(prompt).strip()
        if allow_empty and raw == "":
            return ""
        if not raw:
            print("  Input cannot be empty.")
            continue
        try:
            val = kind(raw)
        except ValueError:
            print(f"  Please enter a valid {kind.__name__}.")
            continue
        if valid and val not in valid:
            print(f"  Choose one of: {', '.join(str(v) for v in valid)}")
            continue
        if min_val is not None and val < min_val:
            print(f"  Minimum value is {min_val}.")
            continue
        if max_val is not None and val > max_val:
            print(f"  Maximum value is {max_val}.")
            continue
        return val

# =========================
# HELPER FUNCTIONS
# =========================
def format_place(name):
    return f"{name}, Dhaka, Bangladesh"

def get_distance_time(src, dst):
    try:
        res = requests.get(
            "https://maps.googleapis.com/maps/api/distancematrix/json",
            params={
                "origins":        format_place(src),
                "destinations":   format_place(dst),
                "key":            GOOGLE_API_KEY,
                "departure_time": "now",
                "traffic_model":  "best_guess",
                "mode":           "driving",
                "units":          "metric"
            },
            timeout=10
        ).json()
        if res.get("status") != "OK":
            print(f"  API Error: {res.get('status')}")
            return None, None, None
        el = res["rows"][0]["elements"][0]
        if el.get("status") != "OK":
            print(f"  Route Error: {el.get('status')} — check place names.")
            return None, None, None
        dist_km  = el["distance"]["value"] / 1000
        norm_min = el["duration"]["value"] / 60
        if "duration_in_traffic" in el:
            traffic_min = el["duration_in_traffic"]["value"] / 60
            ratio = traffic_min / norm_min
        else:
            traffic_min = norm_min * 1.3
            ratio = 1.3
        traffic = "low" if ratio < 1.2 else ("medium" if ratio < 1.5 else "high")
        return round(dist_km, 2), round(traffic_min, 2), traffic
    except requests.ConnectionError:
        print("  No internet connection.")
        return None, None, None
    except Exception as e:
        print(f"  Unexpected error: {e}")
        return None, None, None

def get_geocode(place):
    try:
        res = requests.get(
            "https://maps.googleapis.com/maps/api/geocode/json",
            params={"address": format_place(place), "key": GOOGLE_API_KEY},
            timeout=10
        ).json()
        if res["status"] == "OK":
            loc = res["results"][0]["geometry"]["location"]
            return loc["lat"], loc["lng"]
        return None, None
    except:
        return None, None

def get_ors_route(lat1, lon1, lat2, lon2):
    try:
        res = requests.post(
            "https://api.openrouteservice.org/v2/directions/driving-car/geojson",
            headers={"Authorization": ORS_API_KEY, "Content-Type": "application/json"},
            json={"coordinates": [[lon1, lat1], [lon2, lat2]]},
            timeout=15
        )
        if res.status_code == 200:
            coords = res.json()["features"][0]["geometry"]["coordinates"]
            return [[c[1], c[0]] for c in coords]
        return None
    except:
        return None

def get_bus_fare(src, dst):
    if bus_data.empty:
        return None
    match = bus_data[
        ((bus_data["From"].str.lower() == src.lower()) & (bus_data["To"].str.lower() == dst.lower())) |
        ((bus_data["From"].str.lower() == dst.lower()) & (bus_data["To"].str.lower() == src.lower()))
    ]
    return float(match.iloc[0]["Fare"]) if not match.empty else None

def mode_time(dist_km, mode, traffic):
    speeds     = {"Bus": 18, "CNG": 25, "Auto Rickshaw": 18, "Rickshaw": 10, "Bike": 22}
    multiplier = {"low": 1.0, "medium": 1.3, "high": 1.7}[traffic]
    return round((dist_km / speeds[mode]) * 60 * multiplier, 1)

def rickshaw_fare(dist, ttime):
    if dist < 4.5:
        return 16.45076 + 10.95818 * dist
    return 45 + 11.7 * dist

def auto_fare(dist, ttime):
    if dist < 4.5:
        return 26.45076 + 10.95818 * dist
    return 40 + 11 * dist + 1.2 * ttime

def compute_score(nc, nt, ncom, pref):
    weights = {
        "":              (0.3, 0.5, 0.2),
        "No Preference": (0.3, 0.5, 0.2),
        "Cheap":         (0.6, 0.3, 0.1),
        "Fast":          (0.2, 0.7, 0.1),
        "Comfort":       (0.2, 0.2, 0.6),
    }
    w1, w2, w3 = weights.get(pref, (0.3, 0.5, 0.2))
    return round(w1*nc + w2*nt - w3*ncom, 4)

def format_cost(c, mode):
    if mode in ("CNG", "Bike"):
        return f"BDT {int(c*0.94)}-{int(c*1.06)}"
    elif mode in ("Rickshaw", "Auto Rickshaw"):
        return f"BDT {int(c*0.95)}-{int(c*1.05)}"
    else:
        return f"BDT {int(c*0.965)}-{int(c*1.035)}"

comfort_score = {"Bus": 2, "CNG": 5, "Auto Rickshaw": 4, "Rickshaw": 3, "Bike": 3}

# =========================
# PRINT TABLE
# =========================
def print_table(ranked, budget, max_time):
    """Print a formatted ranking table similar to the Streamlit version."""
    rank_labels = ["1st", "2nd", "3rd", "4th", "5th"]
    # Column widths
    col_w = [5, 15, 18, 12, 20, 8, 15, 28]
    headers = ["Rank", "Mode", "Fare Range", "Cost/Pax", "Time", "Score", "Budget", "Note"]

    sep   = "+" + "+".join("-" * w for w in col_w) + "+"
    row_f = "|" + "|".join(f"{{:<{w}}}" for w in col_w) + "|"

    print("\n" + sep)
    print(row_f.format(*headers))
    print(sep)

    for i, r in enumerate(ranked):
        rank     = rank_labels[i] if i < 5 else "-"
        budget_s = "Within budget" if r["Cost"] <= budget else "Over budget"
        t        = r["Time"]
        if t <= max_time:
            time_s = f"{t} min"
        elif t <= max_time + 10:
            time_s = f"{t} min (+{int(t-max_time)} over)"
        else:
            time_s = f"{t} min (Exceeds limit)"
        note = r["Warning"] if r["Warning"] else "-"
        print(row_f.format(
            rank,
            r["Mode"],
            r["Display"],
            f"BDT {r['Cost/Person']:.0f}",
            time_s,
            str(r["Score"]),
            budget_s,
            note
        ))

    print(sep)

# =========================
# SAVE & OPEN MAP
# =========================
def open_map(source, destination, traffic):
    traffic_label = {"low": "Low", "medium": "Moderate", "high": "Heavy"}[traffic]
    route_color   = {"low": "#16a34a", "medium": "#d97706", "high": "#dc2626"}[traffic]

    print("\nFetching coordinates for map...")
    lat1, lon1 = get_geocode(source)
    lat2, lon2 = get_geocode(destination)

    if not (lat1 and lat2):
        print("Map unavailable — Geocoding API may not be enabled.")
        return

    fmap = folium.Map(location=[(lat1+lat2)/2, (lon1+lon2)/2],
                      zoom_start=13, tiles="OpenStreetMap")

    folium.Marker([lat1, lon1], popup=source,
                  icon=folium.Icon(color="green", icon="play")).add_to(fmap)
    folium.Marker([lat2, lon2], popup=destination,
                  icon=folium.Icon(color="red", icon="stop")).add_to(fmap)

    route_coords = get_ors_route(lat1, lon1, lat2, lon2)
    if route_coords:
        folium.PolyLine(route_coords, color=route_color, weight=5, opacity=0.8,
                        tooltip=f"Traffic: {traffic_label}").add_to(fmap)
    else:
        folium.PolyLine([[lat1, lon1], [lat2, lon2]], color=route_color,
                        weight=4, dash_array="8",
                        tooltip="Approximate route").add_to(fmap)

    legend = f"""
    <div style="position:fixed;bottom:30px;left:30px;background:white;
                padding:10px 14px;border-radius:8px;
                box-shadow:0 2px 6px rgba(0,0,0,0.2);font-size:13px;z-index:1000;">
        <b>Traffic Condition</b><br>
        <span style="color:#16a34a;">&#9644;</span> Low &nbsp;
        <span style="color:#d97706;">&#9644;</span> Moderate &nbsp;
        <span style="color:#dc2626;">&#9644;</span> Heavy<br>
        <b>Current:</b> <span style="color:{route_color};">{traffic_label}</span>
    </div>"""
    fmap.get_root().html.add_child(folium.Element(legend))

    map_path = os.path.abspath("route_map.html")
    fmap.save(map_path)
    print(f"Map saved to: {map_path}")
    print("Opening map in browser...")
    webbrowser.open(f"file:///{map_path}")

# =========================
# MAIN
# =========================
def main():
    print("=" * 55)
    print("       RightRide — Transport Recommendation System")
    print("              Dhaka City Console Version")
    print("=" * 55)

    check_rush_hour()

    print("Note: Please do not use hyphens ( - ) in place names")
    print("      as it may change the area name recognized by the system.\n")

    # ── Inputs ─────────────────────────────────────────────────
    source      = ask("Source      : ")
    destination = ask("Destination : ")

    if source.lower() == destination.lower():
        print("Error: Source and destination cannot be the same.")
        return

    budget   = ask("Budget (BDT)          : ", kind=float, min_val=0)
    persons  = ask("Number of persons     : ", kind=int,   min_val=1, max_val=10)
    max_time = ask("Max travel time (min) : ", kind=int,   min_val=5, max_val=300)
    pref_raw = ask(
        "Preference [Cheap / Fast / Comfort / Enter to skip] : ",
        allow_empty=True
    )
    pref = pref_raw.capitalize() if pref_raw.capitalize() in ("Cheap", "Fast", "Comfort") else ""
    pref_label = pref if pref else "Balanced (No Preference)"

    # ── Distance & Traffic ─────────────────────────────────────
    print("\nFetching route data from Google...")
    dist, time_mins, traffic = get_distance_time(source, destination)

    if dist is None:
        print("Live route unavailable — using estimated values (8 km, medium traffic).")
        dist, time_mins, traffic = 8.0, 25.0, "medium"

    traffic_label = {"low": "Low", "medium": "Moderate", "high": "Heavy"}[traffic]
    print(f"Distance : {dist} km")
    print(f"Traffic  : {traffic_label}")

    # ── Fares ──────────────────────────────────────────────────
    bus_fare = get_bus_fare(source, destination)
    cng_t    = mode_time(dist, "CNG",           traffic)
    auto_t   = mode_time(dist, "Auto Rickshaw",  traffic)
    rick_t   = mode_time(dist, "Rickshaw",       traffic)

    raw_costs = {
        "CNG":           50 + 14.2*dist + 2*cng_t,
        "Auto Rickshaw": auto_fare(dist, auto_t),
        "Rickshaw":      rickshaw_fare(dist, rick_t),
        "Bike":          45 + 13*dist,
        "Bus":           (bus_fare if bus_fare else max(10, dist*2.5)) * persons,
    }
    raw_times    = {m: mode_time(dist, m, traffic) for m in raw_costs}
    min_c, max_c = min(raw_costs.values()), max(raw_costs.values())
    min_t, max_t = min(raw_times.values()), max(raw_times.values())
    min_com      = min(comfort_score.values())
    max_com      = max(comfort_score.values())

    results = []
    for mode, base_cost in raw_costs.items():
        ttime           = raw_times[mode]
        warning         = ""
        vehicles_needed = 1

        if mode == "Bike" and persons > 1:
            warning = f"Not suitable for {persons} persons"
        if mode in ("Rickshaw", "Auto Rickshaw") and persons > 3:
            vehicles_needed = ceil(persons / 3)
            warning = f"~{vehicles_needed} {mode}s needed"

        adjusted_cost = base_cost * vehicles_needed
        nc    = (adjusted_cost - min_c) / (max_c - min_c) if max_c != min_c else 0
        nt    = (ttime - min_t)         / (max_t - min_t) if max_t != min_t else 0
        ncom  = (comfort_score[mode] - min_com) / (max_com - min_com) if max_com != min_com else 0
        score = compute_score(nc, nt, ncom, pref)

        results.append({
            "Mode":        mode,
            "Cost":        adjusted_cost,
            "Cost/Person": round(adjusted_cost / persons, 1),
            "Time":        ttime,
            "Score":       score,
            "Display":     format_cost(adjusted_cost, mode),
            "Warning":     warning,
            "Unsuitable":  bool(warning),
        })

    suitable   = sorted([r for r in results if not r["Unsuitable"]], key=lambda x: x["Score"])
    unsuitable = sorted([r for r in results if r["Unsuitable"]],     key=lambda x: x["Score"])
    ranked     = suitable + unsuitable
    best       = suitable[0] if suitable else ranked[0]

    # ── Output ─────────────────────────────────────────────────
    print("\n" + "=" * 55)
    print("  RECOMMENDATION")
    print("=" * 55)
    budget_tag = "Within budget" if best["Cost"] <= budget else "Over budget"
    print(f"  Best Mode : {best['Mode']}")
    print(f"  Fare      : {best['Display']}")
    print(f"  Time      : {best['Time']} min")
    print(f"  Budget    : {budget_tag}")
    if bus_fare is None:
        print("  Note      : No direct bus route in database — bus fare is estimated.")
    print(f"\n  {source} -> {destination} | {dist:.1f} km | Traffic: {traffic_label}")

    # ── Ranking Table ──────────────────────────────────────────
    print_table(ranked, budget, max_time)

    # ── Feedback ───────────────────────────────────────────────
    cheapest = min(results, key=lambda x: x["Cost"])
    fastest  = min(results, key=lambda x: x["Time"])
    scores   = [r["Score"] for r in (suitable if suitable else results)]

    print("\nAnalysis & Feedback")
    print("-" * 55)
    feedbacks = [
        f"{best['Mode']} has the best score ({best['Score']}) based on {pref_label} preference.",
        f"Cheapest: {cheapest['Mode']} at {cheapest['Display']}",
        f"Fastest : {fastest['Mode']} at {fastest['Time']} min",
    ]
    if len(scores) > 1 and max(scores) - min(scores) < 0.1:
        feedbacks.append("Scores are very close — any suitable option is reasonable.")
    over_budget = [r for r in ranked if r["Cost"] > budget]
    if over_budget:
        feedbacks.append(f"Over budget: {', '.join(r['Mode'] for r in over_budget)} exceed BDT {budget:.0f}.")
    else:
        feedbacks.append(f"All options are within your budget of BDT {budget:.0f}.")
    feedbacks.append({
        "high":   "Heavy traffic — consider leaving earlier or choosing Bus.",
        "medium": "Moderate traffic — allow ~10 extra minutes.",
        "low":    "Light traffic — a smooth journey is expected."
    }[traffic])
    if persons > 1:
        msg = f"For {persons} persons: Bike is not recommended."
        if persons > 3:
            msg += f" ~{ceil(persons/3)} Rickshaws or Auto Rickshaws may be needed."
        feedbacks.append(msg)
    over_time = [r for r in ranked if r["Time"] > max_time]
    if over_time:
        feedbacks.append(f"Exceeds time limit: {', '.join(r['Mode'] for r in over_time)} > {max_time} min.")
    if bus_fare:
        feedbacks.append(f"Bus fare BDT {bus_fare:.0f} confirmed from route database.")

    for fb in feedbacks:
        print(f"  - {fb}")

    # ── Map ────────────────────────────────────────────────────
    print()
    show_map = input("Open route map in browser? (y/n): ").strip().lower()
    if show_map == "y":
        open_map(source, destination, traffic)

    print("\nThank you for using RightRide.")

if __name__ == "__main__":
    main()