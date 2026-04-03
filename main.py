import streamlit as st
import requests
import pandas as pd
import seaborn as sns
import matplotlib.pyplot as plt
import os

# =========================
# CONFIG
# =========================
st.set_page_config(page_title="RightRide", layout="centered", page_icon="🚦")

GOOGLE_API_KEY = "AIzaSyD9WIwKJ1CjKOg_l9py6oUufN1TOj_cPPc"

# =========================
# LOGO + HEADER
# =========================
col1, col2 = st.columns([1, 5])
with col1:
    if os.path.exists("logo.png"):
        st.image("logo.png", width=80)
    else:
        st.write("🚦")
with col2:
    st.title("RightRide")
    st.caption("Smart Transport Recommendation System")

# =========================
# LANGUAGE
# =========================
lang = st.selectbox("Language / ভাষা", ["English", "বাংলা"])

def tr(en, bn):
    return en if lang == "English" else bn

# =========================
# LOAD BUS DATA
# =========================
@st.cache_data
def load_bus_data():
    df = pd.read_csv("Final_Cleaned_Bus_Routes.csv")
    df["From"] = df["From"].str.strip()
    df["To"]   = df["To"].str.strip()
    return df

bus_data   = load_bus_data()
all_places = sorted(set(bus_data["From"].tolist() + bus_data["To"].tolist()))

# =========================
# INPUTS — dropdown + optional free text fallback
# =========================
st.markdown(f"**{tr('Source', 'শুরুর স্থান')}**")
source_dropdown = st.selectbox("", [""] + all_places, key="src_drop",
                                label_visibility="collapsed")
source_custom   = st.text_input(tr("Not in list? Type source manually (e.g. Uttara -11)",
                                   "তালিকায় নেই? নিজে লিখুন (যেমন Uttara -11)"),
                                key="src_text")
source = source_custom.strip() if source_custom.strip() else source_dropdown

st.markdown(f"**{tr('Destination', 'গন্তব্য')}**")
dest_dropdown = st.selectbox("", [""] + all_places, key="dst_drop",
                              label_visibility="collapsed")
dest_custom   = st.text_input(tr("Not in list? Type destination manually",
                                 "তালিকায় নেই? নিজে লিখুন"),
                              key="dst_text")
destination = dest_custom.strip() if dest_custom.strip() else dest_dropdown

col_a, col_b = st.columns(2)
with col_a:
    budget  = st.number_input(tr("Budget (BDT)", "বাজেট (টাকা)"), value=200.0, step=10.0)
with col_b:
    persons = st.number_input(tr("Persons", "যাত্রী সংখ্যা"), min_value=1, max_value=10, value=1)

max_time = st.number_input(tr("Max Time (minutes)", "সর্বোচ্চ সময় (মিনিট)"),
                           min_value=5, max_value=300, value=60, step=5)
pref     = st.selectbox(tr("Preference", "পছন্দ"), ["No Preference", "Cheap", "Fast", "Comfort"])

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
    except:
        return None, None, None

def get_bus_fare(src, dst):
    match = bus_data[
        ((bus_data["From"].str.lower() == src.lower()) & (bus_data["To"].str.lower() == dst.lower())) |
        ((bus_data["From"].str.lower() == dst.lower()) & (bus_data["To"].str.lower() == src.lower()))
    ]
    return float(match.iloc[0]["Fare"]) if not match.empty else None

def mode_time(dist_km, mode, traffic):
    speeds     = {"Bus": 18, "CNG": 25, "Auto Rickshaw": 18, "Rickshaw": 10, "Bike": 22}
    multiplier = {"low": 1.0, "medium": 1.3, "high": 1.7}[traffic]
    return round((dist_km / speeds[mode]) * 60 * multiplier, 1)

def compute_score(cost, time, comfort, pref):
    weights = {
        "Cheap":        (0.6, 0.3, 0.1),
        "Fast":         (0.3, 0.6, 0.1),
        "Comfort":      (0.3, 0.2, 0.5),
        "No Preference":(0.3, 0.5, 0.2),  # time has most weightage by default
    }
    w1, w2, w3 = weights[pref]
    return round(w1*cost + w2*time - w3*comfort, 2)

def format_cost(c, mode):
    if mode in ("CNG", "Bike"):
        return f"BDT {int(c*0.94)}–{int(c*1.06)}"
    elif mode in ("Rickshaw", "Auto Rickshaw"):
        return f"BDT {int(c*0.95)}–{int(c*1.05)}"
    else:
        return f"BDT {int(c*0.965)}–{int(c*1.035)}"

comfort_score = {"Bus": 3, "CNG": 4, "Auto Rickshaw": 3, "Rickshaw": 2, "Bike": 2}
rank_labels   = ["1st", "2nd", "3rd", "4th", "5th"]

# =========================
# MAIN BUTTON
# =========================
if st.button(tr("Find Best Transport", "সেরা পরিবহন খুঁজুন"), use_container_width=True):

    if not source or not destination:
        st.error(tr("Please enter both source and destination.", "উৎস ও গন্তব্য দিন।"))
        st.stop()
    if source.lower() == destination.lower():
        st.error(tr("Source and destination cannot be the same.", "উৎস ও গন্তব্য একই হতে পারে না।"))
        st.stop()

    # Check if manually typed places are in CSV
    src_in_db  = source in all_places
    dst_in_db  = destination in all_places
    custom_note = ""
    if not src_in_db or not dst_in_db:
        missing = []
        if not src_in_db:  missing.append(source)
        if not dst_in_db:  missing.append(destination)
        custom_note = f"Note: {', '.join(missing)} not found in route database. Distance and fare calculated via Google API."

    # Distance & Traffic
    with st.spinner("Fetching route data..."):
        dist, time_mins, traffic = get_distance_time(source, destination)

    if dist is None:
        st.warning("Live route unavailable — using estimated values.")
        dist, time_mins, traffic = 8.0, 25.0, "medium"

    # Fares & Results
    bus_fare   = get_bus_fare(source, destination)
    cng_t      = mode_time(dist, "CNG", traffic)
    auto_t     = mode_time(dist, "Auto Rickshaw", traffic)

    fares = {
        "CNG":          40 + 12*dist + 2*cng_t,
        "Auto Rickshaw":30 + 11*dist + 1.2*auto_t,
        "Rickshaw":     20 + 10*dist,
        "Bike":         30 + 12*dist,
        "Bus":          (bus_fare if bus_fare else max(10, dist*2.5)) * persons,
    }

    results = []
    for mode, base_cost in fares.items():
        ttime           = mode_time(dist, mode, traffic)
        warning         = ""
        vehicles_needed = 1

        if mode == "Bike" and persons > 1:
            warning = f"Not suitable for {persons} persons"
        if mode in ("Rickshaw", "Auto Rickshaw") and persons > 3:
            vehicles_needed = -(-persons // 3)
            warning = f"~{vehicles_needed} {mode}s needed for {persons} persons"

        adjusted_cost = base_cost * vehicles_needed
        score         = compute_score(adjusted_cost, ttime, comfort_score[mode], pref)

        results.append({
            "Mode":       mode,
            "Cost":       adjusted_cost,
            "Time":       ttime,
            "Score":      score,
            "Display":    format_cost(adjusted_cost, mode),
            "Warning":    warning,
            "Unsuitable": bool(warning),
            "Vehicles":   vehicles_needed,
        })

    suitable   = sorted([r for r in results if not r["Unsuitable"]], key=lambda x: x["Score"])
    unsuitable = sorted([r for r in results if r["Unsuitable"]],     key=lambda x: x["Score"])
    ranked     = suitable + unsuitable
    best       = suitable[0] if suitable else ranked[0]

    # Recommendation
    st.markdown("---")
    st.subheader(tr("Recommendation", "সুপারিশ"))
    budget_tag = "Within budget" if best["Cost"] <= budget else "Over budget"
    st.success(f"{best['Mode']} | {best['Display']} | {best['Time']} min | {budget_tag}")

    if bus_fare is None:
        st.warning("No direct bus route found in database — bus fare is estimated.")
    if custom_note:
        st.info(custom_note)

    traffic_label = {"low": "Low", "medium": "Moderate", "high": "Heavy"}[traffic]
    st.info(f"{source} to {destination} | {dist:.1f} km | Traffic: {traffic_label}")

    # Rankings
    st.subheader(tr("All Rankings", "সব র‍্যাংকিং"))
    for i, r in enumerate(ranked):
        rank  = rank_labels[i] if i < 4 else "-"
        note  = f" | {r['Warning']}" if r["Warning"] else ""
        over  = " | Over budget" if r["Cost"] > budget else " | Within budget"
        if r["Time"] <= max_time:
            time_tag = ""
        elif r["Time"] <= max_time + 10:
            time_tag = f" | +{int(r['Time'] - max_time)} min over limit — consider if you can spare it"
        else:
            time_tag = " | Exceeds time limit"
        st.markdown(
            f"**{rank}. {r['Mode']}** | {r['Display']} | "
            f"{r['Time']} min | Score: `{r['Score']}`{over}{time_tag}{note}"
        )

    # Charts
    st.subheader(tr("Visual Comparison", "ভিজ্যুয়াল তুলনা"))
    df_chart     = pd.DataFrame(ranked)
    colors_score = ["#10b981" if r == best else ("#f97316" if r["Unsuitable"] else "#6366f1") for r in ranked]
    colors_cost  = ["#10b981" if r["Cost"] <= budget else "#ef4444" for r in ranked]

    fig, axes = plt.subplots(1, 2, figsize=(11, 4))
    fig.patch.set_facecolor("#f8f9fb")
    for ax in axes:
        ax.set_facecolor("#f8f9fb")
        for spine in ax.spines.values():
            spine.set_edgecolor("#e2e8f0")

    sns.barplot(data=df_chart, x="Mode", y="Score", palette=colors_score, ax=axes[0], width=0.55)
    axes[0].set_title("Overall Score (lower = better)", fontweight="bold", color="#1e293b")
    axes[0].set_xlabel(""); axes[0].set_ylabel("Score", color="#64748b")
    for bar, r in zip(axes[0].patches, ranked):
        axes[0].text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.3,
                     str(r["Score"]), ha="center", fontsize=9, fontweight="bold")

    sns.barplot(data=df_chart, x="Mode", y="Cost", palette=colors_cost, ax=axes[1], width=0.55)
    axes[1].set_title("Estimated Cost (BDT)", fontweight="bold", color="#1e293b")
    axes[1].set_xlabel(""); axes[1].set_ylabel("BDT", color="#64748b")
    axes[1].axhline(y=budget, color="#f59e0b", linestyle="--", linewidth=1.8, label=f"Budget: {budget:.0f} BDT")
    axes[1].legend(fontsize=9)
    for bar, r in zip(axes[1].patches, ranked):
        axes[1].text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.3,
                     f"{int(r['Cost'])} BDT", ha="center", fontsize=9, fontweight="bold")

    plt.tight_layout(pad=2)
    st.pyplot(fig)

    # Feedback
    st.subheader(tr("Analysis & Feedback", "বিশ্লেষণ ও পরামর্শ"))
    cheapest = min(results, key=lambda x: x["Cost"])
    fastest  = min(results, key=lambda x: x["Time"])
    scores   = [r["Score"] for r in suitable] if suitable else [r["Score"] for r in results]

    pref_label = pref if pref != "No Preference" else "Balanced (No Preference)"
    feedbacks = [
        f"**{best['Mode']}** has the best score ({best['Score']}) based on your **{pref_label}** preference.",
        f"Cheapest option: **{cheapest['Mode']}** at {cheapest['Display']}",
        f"Fastest option: **{fastest['Mode']}** at approximately {fastest['Time']} min",
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
            msg += f" Approximately {-(-persons//3)} Rickshaws or Auto Rickshaws may be needed — cost adjusted accordingly."
        feedbacks.append(msg)

    over_time = [r for r in ranked if r["Time"] > max_time]
    if over_time:
        names = ", ".join([r["Mode"] for r in over_time])
        feedbacks.append(f"{names} exceed{'s' if len(over_time)==1 else ''} your time limit of {max_time} min.")

    if bus_fare:
        feedbacks.append(f"Bus fare of BDT {bus_fare} is confirmed from the route database.")

    for fb in feedbacks:
        st.markdown(f"""
        <div style="background:#1e293b;color:#f1f5f9;border-radius:8px;
                    padding:12px 16px;margin:6px 0;font-size:0.95rem;">
            {fb}
        </div>
        """, unsafe_allow_html=True)