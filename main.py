import requests
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
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
        print("Warning: Final_Cleaned_Bus_Routes.csv not found. Bus fare will be estimated.")
        return pd.DataFrame(columns=["From", "To", "Fare"])

bus_data   = load_bus_data()
all_places = sorted(set(bus_data["From"].tolist() + bus_data["To"].tolist()))

# =========================
# HELPER FUNCTIONS
# =========================
def format_place(name):
    return f"{name}, Dhaka, Bangladesh"

def get_distance_time(src, dst):
    try:
        url    = "https://maps.googleapis.com/maps/api/distancematrix/json"
        params = {
            "origins":        format_place(src),
            "destinations":   format_place(dst),
            "key":            GOOGLE_API_KEY,
            "departure_time": "now",
            "traffic_model":  "best_guess",
            "mode":           "driving",
            "units":          "metric"
        }
        res     = requests.get(url, params=params, timeout=10).json()
        if res["status"] != "OK":
            return None, None, None
        element = res["rows"][0]["elements"][0]
        if element["status"] != "OK":
            return None, None, None
        dist_km  = element["distance"]["value"] / 1000
        norm_min = element["duration"]["value"] / 60
        if "duration_in_traffic" in element:
            traffic_min = element["duration_in_traffic"]["value"] / 60
            ratio = traffic_min / norm_min
        else:
            traffic_min = norm_min * 1.3
            ratio = 1.3
        traffic = "low" if ratio < 1.2 else ("medium" if ratio < 1.5 else "high")
        return round(dist_km, 2), round(traffic_min, 2), traffic
    except Exception as e:
        print(f"API Error: {e}")
        return None, None, None

def get_bus_fare(src, dst):
    match = bus_data[
        ((bus_data["From"].str.lower() == src.lower()) & (bus_data["To"].str.lower() == dst.lower())) |
        ((bus_data["From"].str.lower() == dst.lower()) & (bus_data["To"].str.lower() == src.lower()))
    ]
    return float(match.iloc[0]["Fare"]) if not match.empty else None

def mode_time(dist_km, mode, traffic):
    speeds     = {"Bus": 18, "CNG": 25, "Rickshaw": 10, "Bike": 22}
    multiplier = {"low": 1.0, "medium": 1.3, "high": 1.7}[traffic]
    return round((dist_km / speeds[mode]) * 60 * multiplier, 1)

def compute_score(cost, time, comfort, preference):
    if preference == "none":
        w1, w2, w3 = 0.33, 0.33, 0.33
    elif preference == "Cheap":
        w1, w2, w3 = 0.6, 0.3, 0.1
    elif preference == "Fast":
        w1, w2, w3 = 0.3, 0.6, 0.1
    else:
        w1, w2, w3 = 0.3, 0.2, 0.5
    return round(w1*cost + w2*time - w3*comfort, 2)

def format_cost(c, mode):
    if mode in ("CNG", "Bike"):
        return f"BDT {int(c*0.94)}–{int(c*1.06)}"
    elif mode == "Rickshaw":
        return f"BDT {int(c*0.95)}–{int(c*1.05)}"
    else:
        return f"BDT {int(c*0.965)}–{int(c*1.035)}"

comfort_score = {"Bus": 3, "CNG": 4, "Rickshaw": 2, "Bike": 2}

# =========================
# VISUALIZATION
# =========================
def plot_comparison(ranked, budget, source, destination):
    """
    Draws a side-by-side bar chart replicating the Visual Comparison layout:
      Left  → Overall Score  (lower = better)
      Right → Estimated Cost (BDT) with a budget reference line
    """
    modes  = [r["Mode"]  for r in ranked]
    scores = [r["Score"] for r in ranked]
    costs  = [r["Cost"]  for r in ranked]

    x         = np.arange(len(modes))
    bar_width = 0.5
    bg_color  = "#f0f2f8"

    # ── score bar colours: green=best, orange=2nd/3rd best tie, purple=rest ──
    min_score   = min(scores)
    score_colors = []
    for s in scores:
        if s == min_score:
            score_colors.append("#2ec4a9")   # teal-green → best
        elif s <= sorted(scores)[1] + 1:
            score_colors.append("#e07b39")   # orange → near-best
        else:
            score_colors.append("#7b6fd4")   # purple → rest

    # ── cost bar colours: green=within budget, red=over budget ──
    cost_colors = ["#2ec4a9" if c <= budget else "#e05c5c" for c in costs]

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13, 5.5))
    fig.patch.set_facecolor(bg_color)

    # ── LEFT: Overall Score ──────────────────────────────────────────────────
    ax1.set_facecolor(bg_color)
    bars1 = ax1.bar(x, scores, width=bar_width, color=score_colors,
                    zorder=2, linewidth=0)

    for bar, val in zip(bars1, scores):
        ax1.text(bar.get_x() + bar.get_width() / 2,
                 bar.get_height() + max(scores) * 0.018,
                 f"{val}",
                 ha="center", va="bottom",
                 fontsize=11, fontweight="bold", color="#222222")

    ax1.set_xticks(x)
    ax1.set_xticklabels(modes, fontsize=11)
    ax1.set_ylabel("Score", fontsize=11, color="#555555")
    ax1.set_title("Overall Score (lower = better)",
                  fontsize=13, fontweight="bold", pad=14)
    ax1.set_ylim(0, max(scores) * 1.25)
    ax1.spines[["top", "right", "left"]].set_visible(False)
    ax1.tick_params(left=False, colors="#444444")
    ax1.yaxis.grid(True, color="white", linewidth=1.4, zorder=0)
    ax1.set_axisbelow(True)

    # ── RIGHT: Estimated Cost ─────────────────────────────────────────────────
    ax2.set_facecolor(bg_color)
    bars2 = ax2.bar(x, costs, width=bar_width, color=cost_colors,
                    zorder=2, linewidth=0)

    for bar, val in zip(bars2, costs):
        ax2.text(bar.get_x() + bar.get_width() / 2,
                 bar.get_height() + max(costs) * 0.018,
                 f"{int(val)} BDT",
                 ha="center", va="bottom",
                 fontsize=11, fontweight="bold", color="#222222")

    # budget reference line
    ax2.axhline(y=budget, color="#e8a020", linewidth=2,
                linestyle="--", zorder=3)
    ax2.text(len(modes) - 0.28, budget + max(costs) * 0.02,
             f"Budget: {int(budget)} BDT",
             ha="right", va="bottom",
             fontsize=10, color="#e8a020", fontstyle="italic")

    ax2.set_xticks(x)
    ax2.set_xticklabels(modes, fontsize=11)
    ax2.set_ylabel("BDT", fontsize=11, color="#555555")
    ax2.set_title("Estimated Cost (BDT)",
                  fontsize=13, fontweight="bold", pad=14)
    ax2.set_ylim(0, max(max(costs), budget) * 1.28)
    ax2.spines[["top", "right", "left"]].set_visible(False)
    ax2.tick_params(left=False, colors="#444444")
    ax2.yaxis.grid(True, color="white", linewidth=1.4, zorder=0)
    ax2.set_axisbelow(True)

    # ── Title & layout ────────────────────────────────────────────────────────
    fig.suptitle("Visual Comparison",
                 fontsize=17, fontweight="bold",
                 x=0.02, ha="left", y=1.03)
    fig.text(0.02, 0.98,
             f"{source}  →  {destination}",
             fontsize=10, color="#666666", ha="left", va="top")

    plt.tight_layout()
    plt.savefig("rightride_comparison.png",
                dpi=150, bbox_inches="tight",
                facecolor=fig.get_facecolor())
    print("\n  Chart saved → rightride_comparison.png")
    plt.show()

# =========================
# GET USER INPUT
# =========================
def get_input(prompt, valid_options=None, type_fn=str, min_val=None, max_val=None):
    while True:
        val = input(prompt).strip()
        if valid_options and val not in valid_options:
            print(f"  Invalid input. Choose from: {', '.join(str(v) for v in valid_options)}")
            continue
        try:
            val = type_fn(val)
            if min_val is not None and val < min_val:
                print(f"  Minimum value is {min_val}.")
                continue
            if max_val is not None and val > max_val:
                print(f"  Maximum value is {max_val}.")
                continue
            return val
        except:
            print("  Invalid input. Please try again.")

def main():
    print("=" * 55)
    print("       RightRide — Transport Recommendation System")
    print("       Dhaka City")
    print("=" * 55)

    # Source
    print(f"\nAvailable locations ({len(all_places)} total). Type name exactly or enter any Dhaka area.")
    source = input("Source location: ").strip()
    if not source:
        print("Source cannot be empty."); return

    # Destination
    destination = input("Destination location: ").strip()
    if not destination:
        print("Destination cannot be empty."); return

    if source.lower() == destination.lower():
        print("Source and destination cannot be the same."); return

    # Warn if not in database
    if source not in all_places:
        print(f"  Note: '{source}' not in route database. Distance calculated via Google API.")
    if destination not in all_places:
        print(f"  Note: '{destination}' not in route database. Distance calculated via Google API.")

    # Budget
    budget = get_input("Budget (BDT): ", type_fn=float, min_val=0)

    # Persons
    persons = get_input("Number of persons (1-10): ", type_fn=int, min_val=1, max_val=10)

    # Max time
    max_time = get_input("Maximum acceptable travel time (minutes): ", type_fn=int, min_val=5, max_val=300)

    # Preference — press Enter to skip
    print("Preference: Type 'Cheap', 'Fast', 'Comfort', or press Enter to skip (Balanced).")
    while True:
        pref_input = input("Preference [Cheap / Fast / Comfort / Enter to skip]: ").strip()
        if pref_input == "":
            pref = "none"
            print("  No preference selected — using balanced scoring.")
            break
        elif pref_input in ("Cheap", "Fast", "Comfort"):
            pref = pref_input
            break
        else:
            print("  Invalid input. Type Cheap, Fast, Comfort, or press Enter to skip.")

    # =========================
    # CALCULATE
    # =========================
    print("\nFetching route data...")
    dist, time_mins, traffic = get_distance_time(source, destination)

    if dist is None:
        print("Warning: Live route unavailable — using estimated values.")
        dist, time_mins, traffic = 8.0, 25.0, "medium"

    bus_fare = get_bus_fare(source, destination)
    cng_t    = mode_time(dist, "CNG", traffic)

    fares = {
        "CNG":      40 + 12 * dist + 2 * cng_t,
        "Rickshaw": 20 + 10 * dist,
        "Bike":     30 + 12 * dist,
        "Bus":      bus_fare if bus_fare else max(10, dist * 2.5),
    }

    results = []
    for mode, base_cost in fares.items():
        ttime   = mode_time(dist, mode, traffic)
        warning = ""

        # Apply passenger multiplier ONLY to the Bus
        if mode == "Bus":
            adjusted_cost = base_cost * persons
        else:
            adjusted_cost = base_cost

        # Simple warnings without complex math
        if mode == "Bike" and persons > 1:
            warning = f"Not suitable for {persons} persons"
        elif mode == "Rickshaw" and persons > 3:
            warning = f"Tight fit for {persons} persons"

        score = compute_score(adjusted_cost, ttime, comfort_score[mode], pref)

        results.append({
            "Mode":       mode,
            "Cost":       adjusted_cost,
            "Time":       ttime,
            "Score":      score,
            "Display":    format_cost(adjusted_cost, mode),
            "Warning":    warning,
            "Unsuitable": mode == "Bike" and persons > 1,
            "Vehicles":   1,
        })

    suitable   = sorted([r for r in results if not r["Unsuitable"]], key=lambda x: x["Score"])
    unsuitable = sorted([r for r in results if r["Unsuitable"]],     key=lambda x: x["Score"])
    ranked     = suitable + unsuitable
    best       = suitable[0] if suitable else ranked[0]

    # =========================
    # OUTPUT
    # =========================
    traffic_label = {"low": "Low", "medium": "Moderate", "high": "Heavy"}[traffic]
    pref_display  = "Balanced" if pref == "none" else pref

    print("\n" + "=" * 55)
    print("RECOMMENDATION")
    print("=" * 55)
    budget_tag = "Within budget" if best["Cost"] <= budget else "Over budget"
    print(f"  🏆 Best Option : {best['Mode']}")
    print(f"  Fare Range   : {best['Display']}")
    print(f"  Travel Time  : {best['Time']} min")
    print(f"  Budget       : {budget_tag}")

    if bus_fare is None:
        print("  Note: No direct bus route in database — bus fare is estimated.")

    print(f"\n  Route   : {source} to {destination}")
    print(f"  Distance: {dist:.1f} km")
    print(f"  Traffic : {traffic_label}")

    print("\n" + "-" * 55)
    print("ALL RANKINGS (lower score = better)")
    print("-" * 55)
    rank_labels = ["1st", "2nd", "3rd", "4th"]
    for i, r in enumerate(ranked):
        rank     = rank_labels[i] if i < 4 else "-  "
        over     = "Over budget" if r["Cost"] > budget else "Within budget"
        note     = f" | {r['Warning']}" if r["Warning"] else ""
        if r["Time"] <= max_time:
            time_tag = ""
        elif r["Time"] <= max_time + 10:
            time_tag = f" | +{int(r['Time'] - max_time)} min over limit"
        else:
            time_tag = " | Exceeds time limit"
        print(f"  {rank}. {r['Mode']:<10} | {r['Display']:<18} | {r['Time']} min"
              f" | Score: {r['Score']:<7} | {over}{time_tag}{note}")

    print("\n" + "-" * 55)
    print("ANALYSIS & FEEDBACK")
    print("-" * 55)

    cheapest = min(results, key=lambda x: x["Cost"])
    fastest  = min(results, key=lambda x: x["Time"])
    scores   = [r["Score"] for r in suitable] if suitable else [r["Score"] for r in results]

    feedbacks = [
        f"{best['Mode']} has the best score ({best['Score']}) based on your {pref_display} preference.",
        f"Cheapest option: {cheapest['Mode']} at {cheapest['Display']}",
        f"Fastest option:  {fastest['Mode']} at approximately {fastest['Time']} min",
    ]

    if len(scores) > 1 and max(scores) - min(scores) < 5:
        feedbacks.append("Scores are very close — any suitable option is a reasonable choice.")

    over_budget = [r for r in ranked if r["Cost"] > budget]
    if over_budget:
        names = ", ".join([r["Mode"] for r in over_budget])
        feedbacks.append(f"{names} exceed{'s' if len(over_budget)==1 else ''} your budget of BDT {budget:.0f}.")
    else:
        feedbacks.append(f"All options are within your budget of BDT {budget:.0f}.")

    feedbacks.append({
        "high":   "Heavy traffic detected. Consider leaving earlier or choosing Bus.",
        "medium": "Moderate traffic on this route. Allow approximately 10 extra minutes.",
        "low":    "Traffic is light. A smooth journey is expected."
    }[traffic])

    if persons > 1:
        msg = f"For {persons} persons: Bike is not recommended."
        if persons > 3:
            msg += f" Approximately {-(-persons//3)} rickshaws may be needed."
        feedbacks.append(msg)

    over_time = [r for r in ranked if r["Time"] > max_time]
    if over_time:
        names = ", ".join([r["Mode"] for r in over_time])
        feedbacks.append(f"{names} exceed{'s' if len(over_time)==1 else ''} your time limit of {max_time} min.")

    if bus_fare:
        feedbacks.append(f"Bus fare of BDT {bus_fare} is confirmed from the route database.")

    for fb in feedbacks:
        print(f"  - {fb}")

    print("\n" + "=" * 55)

    # =========================
    # VISUALISATION
    # =========================
    plot_comparison(ranked, budget, source, destination)


if __name__ == "__main__":
    main()