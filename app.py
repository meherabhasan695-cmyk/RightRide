import streamlit as st
import requests
import pandas as pd
import matplotlib.pyplot as plt
import folium
import os
from datetime import datetime
from streamlit_js_eval import get_geolocation   #streamlite is getting json data from ORS and showing it in a python web
import streamlit.components.v1 as components


st.set_page_config(page_title="RightRide", layout="centered", page_icon="🚦")

GOOGLE_API_KEY = "AIzaSyD9WIwKJ1CjKOg_l9py6oUufN1TOj_cPPc"
ORS_API_KEY    = "eyJvcmciOiI1YjNjZTM1OTc4NTExMTAwMDFjZjYyNDgiLCJpZCI6ImMzYjliYzczOWE4MjQ3NDE4NjRlOTM2ODliZWUxNWE2IiwiaCI6Im11cm11cjY0In0="


# SESSION STATE

for key, default in [
    ("src_override", ""),
    ("dst_override", ""),
    ("location_fetched", False),
    ("location_place", ""),
]:
    if key not in st.session_state:
        st.session_state[key] = default

# =========================
# LOGO + HEADER
# =========================
col1, col2 = st.columns([1, 5])
with col1:
    if os.path.exists("logo.png"):
        st.image("logo.png", width=130)
    else:
        st.write("🚦")
with col2:
    st.title("RightRide")
    st.caption("Smart Transport Recommendation System — Dhaka City")

st.markdown("---")

# =========================
# LANGUAGE
# =========================
lang = st.selectbox("Language / ভাষা", ["English", "বাংলা"])
def tr(en, bn):
    return en if lang == "English" else bn

hour   = datetime.now().hour
minute = datetime.now().minute

def is_rush_hour():
    if hour in (8, 9): return True
    if hour == 10 and minute <= 30: return True
    if 16 <= hour < 20: return True
    return False

def get_traffic_note():
    if is_rush_hour():
        msg = ("This is a rush hour in Dhaka city (8:00–10:30 AM). There is a possibility of high traffic."
               if hour < 12 else
               "This is a rush hour in Dhaka city (4:00–8:00 PM). There is a possibility of high traffic.")
        return "warning", msg
    elif 11 <= hour < 16:
        return "info", "Traffic is generally moderate at this time of day."
    else:
        return "info", "Traffic is generally low at this time of day."

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
# HELPER FUNCTIONS
# =========================
def format_place(name):
    return f"{name}, Dhaka, Bangladesh"

def reverse_geocode(lat, lon):
    try:
        res = requests.get(
            "https://maps.googleapis.com/maps/api/geocode/json",
            params={"latlng": f"{lat},{lon}", "key": GOOGLE_API_KEY},
            timeout=10
        ).json()
        if res["status"] == "OK":
            return res["results"][0]["formatted_address"].split(",")[0]
        return None
    except:
        return None

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
        if res.get("status") != "OK": return None, None, None
        el = res["rows"][0]["elements"][0]
        if el.get("status") != "OK":  return None, None, None
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
    except:
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
    """Short trip (<4.5 km): regression formula. Longer trip: flat formula."""
    if dist < 4.2:
        return 16.45076 + 10.95818 * dist 
    else:
        return 45 + 11.7 * dist

def auto_fare(dist, ttime):
    """Short trip (<4.5 km): regression formula. Longer trip: flat formula."""
    if dist < 4.2:
        return 26.45076 + 10.95818 * dist 
    else:
        return 40 + 11 * dist + 1.2 * ttime

def compute_score(nc, nt, ncom, pref):
    weights = {
        "No Preference": (0.3, 0.5, 0.2),
        "Cheap":         (0.6, 0.3, 0.1),
        "Fast":          (0.2, 0.7, 0.1),
        "Comfort":       (0.2, 0.2, 0.6),
    }
    w1, w2, w3 = weights[pref]
    return round(w1*nc + w2*nt - w3*ncom, 4)

def format_cost(c, mode):
    if mode in ("CNG", "Bike"):
        return f"BDT {int(c*0.94)}–{int(c*1.06)}"
    elif mode in ("Rickshaw", "Auto Rickshaw"):
        return f"BDT {int(c*0.95)}–{int(c*1.05)}"
    else:
        return f"BDT {int(c*0.965)}–{int(c*1.035)}"

comfort_score = {"Bus": 2, "CNG": 5, "Auto Rickshaw": 4, "Rickshaw": 3, "Bike": 3}

# =========================
# SOURCE INPUT
# =========================
st.markdown(f"**{tr('Source', 'শুরুর স্থান')}**")
st.caption(tr(
    "Please do not use any type of punction , it may change the area name.",
    "স্থানের নামে বিরামচিহ্ন ব্যবহার করবেন না, এটি এলাকার নাম পরিবর্তন করতে পারে।"
))

loc_col, btn_col = st.columns([5, 1])
with btn_col:
    use_location = st.button("📍", help="Use my current location as source", key="loc_btn")

# Handle location fetch — runs only on the click rerun
if use_location:
    loc = get_geolocation()
    if loc and loc.get("coords"):
        lat   = loc["coords"]["latitude"]
        lon   = loc["coords"]["longitude"]
        place = reverse_geocode(lat, lon)
        if place:
            st.session_state.src_override    = place
            st.session_state.location_place  = place
            st.session_state.location_fetched = True
        else:
            st.warning(tr("Could not determine place name. Please type manually.",
                          "স্থানের নাম পাওয়া যায়নি। হাতে লিখুন।"))
    else:
        st.warning(tr("Location access denied or unavailable.",
                      "লোকেশন অ্যাক্সেস অস্বীকৃত বা অনুপলব্ধ।"))

if st.session_state.location_fetched:
    st.success(tr(f"Location detected: {st.session_state.location_place}",
                  f"লোকেশন পাওয়া গেছে: {st.session_state.location_place}"))

# Determine dropdown default
src_default_idx = 0
if st.session_state.src_override in all_places:
    src_default_idx = all_places.index(st.session_state.src_override) + 1

with loc_col:
    source_dropdown = st.selectbox(
        "", [""] + all_places,
        index=src_default_idx,
        key="src_drop",
        label_visibility="collapsed"
    )

source_custom = st.text_input(
    tr("Not in list? Type source manually (e.g. Uttara 11)",
       "তালিকায় নেই? নিজে লিখুন (যেমন Uttara 11)"),
    value=st.session_state.src_override if st.session_state.src_override not in all_places else "",
    key="src_text"
)
source = source_custom.strip() if source_custom.strip() else source_dropdown

# =========================
# DESTINATION INPUT
# =========================
st.markdown(f"**{tr('Destination', 'গন্তব্য')}**")
st.caption(tr(
    "Please do not use any type of punction , it may change the area name.",
    "স্থানের নামে বিরামচিহ্ন ব্যবহার করবেন না, এটি এলাকার নাম পরিবর্তন করতে পারে।"
))

dst_default_idx = 0
if st.session_state.dst_override in all_places:
    dst_default_idx = all_places.index(st.session_state.dst_override) + 1

dest_dropdown = st.selectbox(
    "", [""] + all_places,
    index=dst_default_idx,
    key="dst_drop",
    label_visibility="collapsed"
)
dest_custom = st.text_input(
    tr("Not in list? Type destination manually",
       "তালিকায় নেই? নিজে লিখুন"),
    value=st.session_state.dst_override if st.session_state.dst_override not in all_places else "",
    key="dst_text"
)
destination = dest_custom.strip() if dest_custom.strip() else dest_dropdown

# =========================
# OTHER INPUTS
# =========================
col_a, col_b = st.columns(2)
with col_a:
    budget  = st.number_input(tr("Budget (BDT)", "বাজেট (টাকা)"), value=200.0, step=10.0)
with col_b:
    persons = st.number_input(tr("Persons", "যাত্রী সংখ্যা"), min_value=1, max_value=10, value=1)

max_time = st.number_input(
    tr("Max Time (minutes)", "সর্বোচ্চ সময় (মিনিট)"),
    min_value=5, max_value=300, value=60, step=5
)
pref = st.selectbox(tr("Preference", "পছন্দ"), ["No Preference", "Cheap", "Fast", "Comfort"])

# Rush hour warning — shown after all inputs
traffic_note_type, traffic_note_msg = get_traffic_note()
if traffic_note_type == "warning":
    st.warning(traffic_note_msg)
else:
    st.info(traffic_note_msg)

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

    # Note for custom places
    if source not in all_places or destination not in all_places:
        missing = [p for p in [source, destination] if p not in all_places]
        st.info(f"Note: {', '.join(missing)} not in route database. Fare calculated via Google API.")

    # Distance & Traffic
    with st.spinner("Fetching route data..."):
        dist, time_mins, traffic = get_distance_time(source, destination)

    if dist is None:
        st.warning("Live route unavailable — using estimated values.")
        dist, time_mins, traffic = 8.0, 25.0, "medium"

    # Fares
    bus_fare = get_bus_fare(source, destination)
    cng_t    = mode_time(dist, "CNG",          traffic)
    auto_t   = mode_time(dist, "Auto Rickshaw", traffic)
    rick_t   = mode_time(dist, "Rickshaw",      traffic)

    raw_costs = {
        "CNG":          50 + 14.2*dist + 2*cng_t,
        "Auto Rickshaw": auto_fare(dist, auto_t),
        "Rickshaw":      rickshaw_fare(dist, rick_t),
        "Bike":          45 + 13*dist,
        "Bus":          (bus_fare if bus_fare else max(10, dist*2.5)) * persons,
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
            vehicles_needed = -(-persons // 3)
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
            "Vehicles":    vehicles_needed,
        })

    suitable   = sorted([r for r in results if not r["Unsuitable"]], key=lambda x: x["Score"])
    unsuitable = sorted([r for r in results if r["Unsuitable"]],     key=lambda x: x["Score"])
    ranked     = suitable + unsuitable
    best       = suitable[0] if suitable else ranked[0]

    traffic_label = {"low": "Low", "medium": "Moderate", "high": "Heavy"}[traffic]

    # ── Recommendation ────────────────────────────────────────────────────
    st.markdown("---")
    st.subheader(tr("Recommendation", "সুপারিশ"))
    budget_tag = "Within budget" if best["Cost"] <= budget else "Over budget"
    st.success(f"🏆 {best['Mode']} | {best['Display']} | {best['Time']} min | {budget_tag}")
    if bus_fare is None:
        st.warning("No direct bus route found in database — bus fare is estimated.")
    st.info(f"{source}  →  {destination} | {dist:.1f} km | Traffic: {traffic_label}")

    # ── Results Table ─────────────────────────────────────────────────────
    st.subheader(tr("All Options", "সব বিকল্প"))
    rank_labels = ["1st", "2nd", "3rd", "4th", "5th"]
    table_rows  = []
    for i, r in enumerate(ranked):
        rank     = rank_labels[i] if i < 5 else "-"
        budget_s = "Within budget" if r["Cost"] <= budget else "Over budget"
        if r["Time"] <= max_time:
            time_s = f"{r['Time']} min"
        elif r["Time"] <= max_time + 10:
            time_s = f"{r['Time']} min (+{int(r['Time']-max_time)} over)"
        else:
            time_s = f"{r['Time']} min (Exceeds limit)"
        table_rows.append({
            "Rank":        rank,
            "Mode":        r["Mode"],
            "Fare Range":  r["Display"],
            "Cost/Person": f"BDT {r['Cost/Person']:.0f}",
            "Time":        time_s,
            "Score":       r["Score"],
            "Budget":      budget_s,
            "Note":        r["Warning"] if r["Warning"] else "-",
        })

    st.dataframe(pd.DataFrame(table_rows), use_container_width=True, hide_index=True)

    # ── Charts ────────────────────────────────────────────────────────────
    st.subheader(tr("Visual Comparison", "ভিজ্যুয়াল তুলনা"))
    fig, axes = plt.subplots(1, 2, figsize=(11, 4))
    fig.patch.set_facecolor("#f8f9fb")
    for ax in axes:
        ax.set_facecolor("#f8f9fb")
        for spine in ax.spines.values():
            spine.set_edgecolor("#e2e8f0")

    modes       = [r["Mode"]  for r in ranked]
    scores_list = [r["Score"] for r in ranked]
    costs       = [r["Cost"]  for r in ranked]
    x           = range(len(modes))

    axes[0].bar(x, scores_list,
                color=["#10b981" if r == best else "#6366f1" for r in ranked])
    axes[0].set_ylim(0, max(scores_list) + 0.1)
    axes[0].set_xticks(list(x)); axes[0].set_xticklabels(modes, fontsize=9)
    axes[0].set_title("Score (lower = better)", fontweight="bold", color="#1e293b")
    axes[0].set_ylabel("Score", color="#64748b")
    for i, s in enumerate(scores_list):
        axes[0].text(i, s + 0.02, str(s), ha="center", fontsize=8, fontweight="bold")

    bar_colors = ["#10b981" if r["Cost"] <= budget else "#ef4444" for r in ranked]
    axes[1].bar(x, costs, color=bar_colors)
    axes[1].set_ylim(0, max(costs) + 20)
    axes[1].set_xticks(list(x)); axes[1].set_xticklabels(modes, fontsize=9)
    axes[1].set_title("Estimated Cost (BDT)", fontweight="bold", color="#1e293b")
    axes[1].set_ylabel("BDT", color="#64748b")
    axes[1].axhline(y=budget, color="#f59e0b", linestyle="--", linewidth=1.5,
                    label=f"Budget: {budget:.0f} BDT")
    axes[1].legend(fontsize=9)
    for i, c in enumerate(costs):
        axes[1].text(i, c + 5, f"{int(c)}", ha="center", fontsize=8, fontweight="bold")

    plt.tight_layout(pad=2)
    st.pyplot(fig)

    # ── Feedback ──────────────────────────────────────────────────────────
    st.subheader(tr("Analysis & Feedback", "বিশ্লেষণ ও পরামর্শ"))
    cheapest   = min(results, key=lambda x: x["Cost"])
    fastest    = min(results, key=lambda x: x["Time"])
    scores     = [r["Score"] for r in (suitable if suitable else results)]
    pref_label = pref if pref != "No Preference" else "Balanced (No Preference)"

    feedbacks = [
        f"**{best['Mode']}** has the best score ({best['Score']}) based on your **{pref_label}** preference.",
        f"Cheapest option: **{cheapest['Mode']}** at {cheapest['Display']}",
        f"Fastest option: **{fastest['Mode']}** at approximately {fastest['Time']} min",
    ]
    if len(scores) > 1 and max(scores) - min(scores) < 0.1:
        feedbacks.append("Scores are very close — any suitable option is a reasonable choice.")
    over_budget = [r for r in ranked if r["Cost"] > budget]
    if over_budget:
        feedbacks.append(f"{', '.join(r['Mode'] for r in over_budget)} exceed your budget of BDT {budget:.0f}.")
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
            msg += f" Approximately {-(-persons//3)} Rickshaws or Auto Rickshaws may be needed."
        feedbacks.append(msg)
    over_time = [r for r in ranked if r["Time"] > max_time]
    if over_time:
        feedbacks.append(f"{', '.join(r['Mode'] for r in over_time)} exceed your time limit of {max_time} min.")
    if bus_fare:
        feedbacks.append(f"Bus fare of BDT {bus_fare:.0f} confirmed from the route database.")

    for fb in feedbacks:
        st.markdown(
            f'<div style="background:#1e293b;color:#f1f5f9;border-radius:8px;'
            f'padding:12px 16px;margin:6px 0;font-size:0.95rem;">{fb}</div>',
            unsafe_allow_html=True
        )

    # ── Map ───────────────────────────────────────────────────────────────
    st.subheader(tr("Route Map", "রুট মানচিত্র"))
    with st.spinner("Loading map..."):
        lat1, lon1 = get_geocode(source)
        lat2, lon2 = get_geocode(destination)

    if lat1 and lat2:
        mid_lat = (lat1 + lat2) / 2
        mid_lon = (lon1 + lon2) / 2
        fmap    = folium.Map(location=[mid_lat, mid_lon], zoom_start=13,
                             tiles="OpenStreetMap")
        folium.Marker([lat1, lon1], popup=source,
                      icon=folium.Icon(color="green", icon="play")).add_to(fmap)
        folium.Marker([lat2, lon2], popup=destination,
                      icon=folium.Icon(color="red",   icon="stop")).add_to(fmap)

        route_color  = {"low": "#16a34a", "medium": "#d97706", "high": "#dc2626"}[traffic]
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
        components.html(fmap._repr_html_(), height=450)
    else:
        st.info("Map unavailable — enable Geocoding API in Google Cloud Console.")