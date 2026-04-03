import requests
import pandas as pd
import matplotlib.pyplot as plt
import numpy as np

# =========================
# CONFIG
# =========================
GOOGLE_API_KEY = "AIzaSyD9WIwKJ1CjKOg_l9py6oUufN1TOj_cPPc"

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
        print("Warning: Bus data file not found. Bus fare will be estimated.")
        return pd.DataFrame(columns=["From", "To", "Fare"])

bus_data   = load_bus_data()
all_places = sorted(set(bus_data["From"].tolist() + bus_data["To"].tolist()))

# =========================
# HELPER FUNCTIONS
# =========================
def get_distance_time(src, dst):
    try:
        url    = "https://maps.googleapis.com/maps/api/distancematrix/json"
        params = {
            "origins":        f"{src}, Dhaka, Bangladesh",
            "destinations":   f"{dst}, Dhaka, Bangladesh",
            "key":            GOOGLE_API_KEY,
            "departure_time": "now",
            "traffic_model":  "best_guess",
            "mode":           "driving"
        }
        res = requests.get(url, params=params, timeout=10).json()

        if res.get("status") != "OK":
            print(f"API Error: {res.get('status')} — {res.get('error_message', '')}")
            return None, None, None

        el = res["rows"][0]["elements"][0]
        if el.get("status") != "OK":
            print(f"Route not found: {el.get('status')}. Check spelling of locations.")
            return None, None, None

        dist    = el["distance"]["value"] / 1000
        normal  = el["duration"]["value"] / 60
        traffic_min = el.get("duration_in_traffic", {}).get("value", normal * 1.3 * 60) / 60
        ratio   = traffic_min / normal
        traffic = "low" if ratio < 1.2 else ("medium" if ratio < 1.5 else "high")
        return round(dist, 2), round(traffic_min, 2), traffic

    except requests.exceptions.ConnectionError:
        print("No internet connection.")
        return None, None, None
    except Exception as e:
        print(f"Unexpected error: {e}")
        return None, None, None

def get_bus_fare(src, dst):
    match = bus_data[
        ((bus_data["From"].str.lower() == src.lower()) & (bus_data["To"].str.lower() == dst.lower())) |
        ((bus_data["From"].str.lower() == dst.lower()) & (bus_data["To"].str.lower() == src.lower()))
    ]
    return float(match.iloc[0]["Fare"]) if not match.empty else None

def mode_time(dist, mode, traffic):
    speeds     = {"Bus": 18, "CNG": 25, "Auto Rickshaw": 18, "Rickshaw": 10, "Bike": 22}
    multiplier = {"low": 1.0, "medium": 1.3, "high": 1.7}[traffic]
    return round((dist / speeds[mode]) * 60 * multiplier, 1)

def compute_score(nc, nt, ncom, pref):
    weights = {
        "Cheap":   (0.6, 0.3, 0.1),
        "Fast":    (0.2, 0.7, 0.1),
        "Comfort": (0.2, 0.2, 0.6),
        "":        (0.3, 0.5, 0.2),
    }
    w1, w2, w3 = weights[pref]
    return round(w1*nc + w2*nt - w3*ncom, 4)

comfort_score = {"Bus": 2, "CNG": 5, "Auto Rickshaw": 4, "Rickshaw": 3, "Bike": 3}

def format_cost(c, mode):
    if mode in ("CNG", "Bike"):        return f"BDT {int(c*0.94)}–{int(c*1.06)}"
    elif mode in ("Rickshaw", "Auto Rickshaw"): return f"BDT {int(c*0.95)}–{int(c*1.05)}"
    else:                              return f"BDT {int(c*0.965)}–{int(c*1.035)}"

def ask(prompt, cast=str, valid=None, min_val=None, max_val=None, allow_empty=False):
    """Generic validated input."""
    while True:
        raw = input(prompt).strip()
        if allow_empty and raw == "":
            return ""
        try:
            val = cast(raw)
        except ValueError:
            print(f"  Invalid — expected {cast.__name__}."); continue
        if valid and val not in valid:
            print(f"  Choose one of: {', '.join(v for v in valid if v)}"); continue
        if min_val is not None and val < min_val:
            print(f"  Minimum is {min_val}."); continue
        if max_val is not None and val > max_val:
            print(f"  Maximum is {max_val}."); continue
        return val

comfort_score = {"Bus": 3, "CNG": 4, "Auto Rickshaw": 3, "Rickshaw": 2, "Bike": 2}

# =========================
# MAIN
# =========================
def main():
    print("=" * 55)
    print("    RightRide — Transport Recommendation System")
    print("=" * 55)

    # Inputs with validation
    source      = ask("Source location      : ")
    destination = ask("Destination location : ")

    if source.lower() == destination.lower():
        print("Error: Source and destination cannot be the same."); return

    if source not in all_places:
        print(f"  Note: '{source}' not in database. Fare via Google API.")
    if destination not in all_places:
        print(f"  Note: '{destination}' not in database. Fare via Google API.")

    budget   = ask("Budget (BDT)         : ", cast=float, min_val=0)
    persons  = ask("Number of persons    : ", cast=int,   min_val=1, max_val=10)
    max_time = ask("Max travel time (min): ", cast=int,   min_val=5, max_val=300)
    pref     = ask("Preference (Cheap/Fast/Comfort, Enter to skip): ", valid=["Cheap", "Fast", "Comfort", ""], allow_empty=True)

    # Fetch route
    print("\nFetching route data...")
    dist, time_mins, traffic = get_distance_time(source, destination)

    if dist is None:
        print("Could not fetch route. Please check location names and internet connection.")
        return

    # Fares
    bus_fare = get_bus_fare(source, destination)
    raw_costs = {
       "CNG":          50 + 14.2*dist + 2*mode_time(dist, "CNG", traffic),
        "Auto Rickshaw":40 + 11*dist + 1.2*mode_time(dist, "Auto Rickshaw", traffic),
        "Rickshaw":     45 + 11.7*dist,
        "Bike":         45 + 13*dist,
        "Bus":          (bus_fare if bus_fare else max(10, dist*2.5)) * persons,
    }
    raw_times   = {m: mode_time(dist, m, traffic) for m in raw_costs}
    min_c, max_c = min(raw_costs.values()), max(raw_costs.values())
    min_t, max_t = min(raw_times.values()), max(raw_times.values())
    min_com      = min(comfort_score.values())
    max_com      = max(comfort_score.values())

    # Build results
    results = []
    for mode, base_cost in raw_costs.items():
        ttime           = raw_times[mode]
        warning         = ""
        vehicles_needed = 1

        if mode == "Bike" and persons > 1:
            warning = "Not suitable for multiple persons"
        if mode in ("Rickshaw", "Auto Rickshaw") and persons > 3:
            vehicles_needed = -(-persons // 3)
            warning = f"~{vehicles_needed} {mode}s needed"

        cost = base_cost * vehicles_needed
        nc   = (cost - min_c) / (max_c - min_c) if max_c != min_c else 0
        nt   = (ttime - min_t) / (max_t - min_t) if max_t != min_t else 0
        ncom = (comfort_score[mode] - min_com) / (max_com - min_com) if max_com != min_com else 0
        score = compute_score(nc, nt, ncom, pref)

        results.append({
            "Mode":    mode,
            "Cost":    cost,
            "Time":    ttime,
            "Score":   score,
            "Display": format_cost(cost, mode),
            "Warning": warning,
            "Unsuitable": bool(warning),
        })

    suitable   = sorted([r for r in results if not r["Unsuitable"]], key=lambda x: x["Score"])
    unsuitable = sorted([r for r in results if r["Unsuitable"]],     key=lambda x: x["Score"])
    ranked     = suitable + unsuitable
    best       = suitable[0] if suitable else ranked[0]

    # Output
    traffic_label = {"low": "Low", "medium": "Moderate", "high": "Heavy"}[traffic]
    print("\n" + "=" * 55)
    print("RECOMMENDATION")
    print("=" * 55)
    print(f"  Best Option : {best['Mode']}")
    print(f"  Fare Range  : {best['Display']}")
    print(f"  Travel Time : {best['Time']} min")
    print(f"  Budget      : {'Within budget' if best['Cost'] <= budget else 'Over budget'}")
    if bus_fare is None:
        print("  Note: No direct bus route found — bus fare is estimated.")
    print(f"\n  Route    : {source} to {destination}")
    print(f"  Distance : {dist:.1f} km  |  Traffic: {traffic_label}")

    print("\n" + "-" * 55)
    print("ALL RANKINGS")
    print("-" * 55)
    rank_labels = ["1st", "2nd", "3rd", "4th", "5th"]
    for i, r in enumerate(ranked):
        over     = "Over budget" if r["Cost"] > budget else "Within budget"
        note     = f" | {r['Warning']}" if r["Warning"] else ""
        if r["Time"] <= max_time:
            time_tag = ""
        elif r["Time"] <= max_time + 10:
            time_tag = f" | +{int(r['Time']-max_time)} min over — consider if you can spare it"
        else:
            time_tag = " | Exceeds time limit"
        print(f"  {rank_labels[i]}. {r['Mode']:<15} {r['Display']:<20} "
              f"{r['Time']} min | Score: {r['Score']} | {over}{time_tag}{note}")

    print("\n" + "-" * 55)
    print("ANALYSIS & FEEDBACK")
    print("-" * 55)

    cheapest = min(results, key=lambda x: x["Cost"])
    fastest  = min(results, key=lambda x: x["Time"])
    scores   = [r["Score"] for r in suitable] if suitable else [r["Score"] for r in results]

    pref_label = pref if pref else "Balanced (default)"
    feedbacks = [
        f"{best['Mode']} has the best score ({best['Score']}) for your {pref_label} preference.",
        f"Cheapest: {cheapest['Mode']} at {cheapest['Display']}",
        f"Fastest:  {fastest['Mode']} at ~{fastest['Time']} min",
    ]
    if len(scores) > 1 and max(scores) - min(scores) < 5:
        feedbacks.append("Scores are very close — any suitable option is reasonable.")
    over_budget = [r for r in ranked if r["Cost"] > budget]
    if over_budget:
        feedbacks.append(f"{', '.join(r['Mode'] for r in over_budget)} exceed your budget of BDT {budget:.0f}.")
    else:
        feedbacks.append(f"All options are within your budget of BDT {budget:.0f}.")
    feedbacks.append({
        "high":   "Heavy traffic. Consider leaving earlier or taking Bus.",
        "medium": "Moderate traffic. Allow ~10 extra minutes.",
        "low":    "Light traffic. Smooth journey expected."
    }[traffic])
    if persons > 1:
        msg = f"For {persons} persons: Bike is not recommended."
        if persons > 3:
            msg += f" ~{-(-persons//3)} rickshaws may be needed."
        feedbacks.append(msg)
    over_time = [r for r in ranked if r["Time"] > max_time]
    if over_time:
        feedbacks.append(f"{', '.join(r['Mode'] for r in over_time)} exceed your time limit of {max_time} min.")
    if bus_fare:
        feedbacks.append(f"Bus fare of BDT {bus_fare} confirmed from database.")

    for fb in feedbacks:
        print(f"  - {fb}")

    # Charts
    print("\nGenerating charts...")
    modes  = [r["Mode"]  for r in ranked]
    costs  = [r["Cost"]  for r in ranked]
    scores_list = [r["Score"] for r in ranked]
    x = np.arange(len(modes))

    fig, axes = plt.subplots(1, 2, figsize=(11, 4))
    fig.suptitle(f"{source} to {destination}", fontweight="bold")

    axes[0].bar(x, scores_list, color=["#10b981" if r==best else "#6366f1" for r in ranked])

    max_score = max(scores_list)
    axes[0].set_ylim(0, max_score + 0.1)

    axes[0].set_xticks(x); axes[0].set_xticklabels(modes)
    axes[0].set_title("Score (lower = better)"); axes[0].set_ylabel("Score")

    for i, s in enumerate(scores_list):
        axes[0].text(i, s + 0.02, str(s), ha="center", fontsize=9, fontweight="bold")

    bar_colors = ["#10b981" if r["Cost"] <= budget else "#ef4444" for r in ranked]
    axes[1].bar(x, costs, color=bar_colors)

    max_cost = max(costs)
    axes[1].set_ylim(0, max_cost + 20)
    axes[1].set_xticks(x); axes[1].set_xticklabels(modes)
    axes[1].set_title("Estimated Cost (BDT)"); axes[1].set_ylabel("BDT")
    axes[1].axhline(y=budget, color="#f59e0b", linestyle="--", linewidth=1.5,
                    label=f"Budget: {budget:.0f} BDT")
    axes[1].legend()
    for i, c in enumerate(costs):
        axes[1].text(i, c + 5, f"{int(c)}", ha="center", fontsize=9, fontweight="bold")

    plt.tight_layout()
    plt.show()
    print("=" * 55)

if __name__ == "__main__":
    main()