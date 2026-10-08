"""CCR Line - Ops Excellence Dashboard (Streamlit).

Live OEE dashboard reading the OEE_Data tab of the company Google Sheet.
Data is fetched server-side (no browser-to-Google dependency) and cached
for 15 minutes.
"""
import json
import re
import calendar
import datetime

import requests
import pandas as pd
import streamlit as st
import plotly.graph_objects as go

SHEET_ID = "1hz224h8DB7akltrzjW0oSnP22seTEbr9RmKBnuGiiVw"
BLUE = "#1f4e78"
GREEN = "#2e7d32"
AMBER = "#c77700"
RED = "#c0392b"

st.set_page_config(page_title="CCR Line - Ops Excellence Dashboard", layout="wide")

# ---------------------------------------------------------------- data ----
@st.cache_data(ttl=900)
def fetch_sheet():
    # Complete baked data (via Sheets API) — gviz drops label-only rows,
    # so we read the baked JSON instead. Refreshed every ~30 min.
    url = "https://pclwaqas786-ctrl.github.io/ccr-oee-dashboard/data.json"
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    d = r.json()
    values = d.get("values", [])
    if not values:
        raise RuntimeError("empty baked data")
    try:
        fa = datetime.datetime.fromisoformat(d["fetched_at"])
        fetched = fa.strftime("%d %b %Y, %H:%M")
    except Exception:
        fetched = str(d.get("fetched_at", ""))
    rows = [list(r) + [None] * (16 - len(r)) for r in values]
    return {"fetched_at": fetched, "rows": rows}


def num(v):
    if v is None or v == "":
        return 0.0
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace(",", "")
    if s.endswith("%"):
        try:
            return float(s[:-1]) / 100.0
        except ValueError:
            return 0.0
    try:
        return float(s)
    except ValueError:
        return 0.0


MON = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
       "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12}


def parse_date(v):
    if v is None or v == "":
        return None
    s = str(v).strip()
    m0 = re.match(r"Date\((\d+),(\d+),(\d+)\)", s)
    if m0:
        return datetime.datetime(int(m0.group(1)), int(m0.group(2)) + 1,
                                 int(m0.group(3)))
    if re.fullmatch(r"\d{4,6}", s):
        return datetime.datetime(1970, 1, 1) + datetime.timedelta(days=int(s) - 25569)
    m = re.match(r"(\d{1,2})-([A-Za-z]{3})-(\d{2,4})", s)
    if m and m.group(2).lower() in MON:
        y = int(m.group(3))
        if y < 100:
            y += 2000
        return datetime.datetime(y, MON[m.group(2).lower()], int(m.group(1)))
    return None


def parse_model(rows):
    M = {"daily": [], "mtd": {}, "reasons": [], "trend": [], "periods": [],
         "target": 0.0}
    section = None
    for r in rows:
        r = list(r) + [None] * (14 - len(r))
        a = r[0]
        lab = str(r[1] if r[1] is not None else "").strip()
        if a not in (None, "") and str(a).strip().replace(".", "", 1).isdigit() \
                and parse_date(r[1]):
            M["daily"].append({
                "day": float(a), "date": parse_date(r[1]),
                "avail": num(r[2]), "dt": num(r[3]), "run": num(r[4]),
                "availP": num(r[5]), "plan": num(r[6]), "ach": num(r[7]),
                "perfP": num(r[8]), "good": num(r[9]), "qualP": num(r[10]),
                "oee": num(r[11]), "status": str(r[12] or "")})
            continue
        if re.match(r"^MTD TOTAL", lab, re.I):
            M["mtd"] = {"avail": num(r[2]), "dt": num(r[3]), "run": num(r[4]),
                        "availP": num(r[5]), "plan": num(r[6]), "ach": num(r[7]),
                        "perfP": num(r[8]), "qualP": num(r[10]),
                        "oeeP": num(r[11]), "dtHrs": num(r[13])}
            continue  # reasons continue after the MTD row — keep section open
        if re.match(r"^MTD Downtime by Reason", lab, re.I):
            section = "reasons"; continue
        if re.match(r"^Yearly Production Trend", lab, re.I):
            section = "trend"; continue
        if re.match(r"^Period-wise Summary", lab, re.I):
            section = "periods"; continue
        if re.match(r"^Yearly Target", lab, re.I):
            M["target"] = num(r[2]); section = None; continue
        if re.match(r"^(Total|Period|Day|Date)\b", lab, re.I) and section != "daily":
            continue
        if lab == "" and section:
            continue
        if section == "reasons" and lab:
            M["reasons"].append({"name": lab, "hrs": num(r[2])})
        elif section == "trend" and lab and re.search(r"-26|-27", lab, re.I):
            M["trend"].append({"m": lab, "prod": num(r[2]), "cum": num(r[3])})
        elif section == "periods" and re.match(r"^Week", lab, re.I):
            M["periods"].append({"p": lab, "avail": num(r[2]), "perf": num(r[3]),
                                 "qual": num(r[4]), "oee": num(r[5]),
                                 "plan": num(r[6]), "ach": num(r[7])})
        if lab == "" and (r[2] in (None, "")) and section \
                and not re.match(r"^Week", lab, re.I):
            if section == "reasons":
                section = None
    M["daily"] = [d for d in M["daily"] if re.search(r"final", d["status"], re.I)]
    M["daily"].sort(key=lambda d: d["date"])
    return M


def pct(x):
    return f"{x * 100:.1f}%"


# ---------------------------------------------------------------- UI ------
st.markdown("""
<style>
  .kpi-card { background:#ffffff; border:1px solid #d9e1ea; border-left:5px solid var(--ac,#1f4e78);
    border-radius:10px; padding:12px 14px; box-shadow:0 1px 3px rgba(16,42,67,.08); }
  .kpi-card .lbl { font-size:11px; color:#64748b; text-transform:uppercase; letter-spacing:.6px; }
  .kpi-card .val { font-size:28px; font-weight:700; color:#1c2733; }
  .kpi-card .note { font-size:12px; color:#64748b; }
  h1, h2, h3 { color:#1c2733; }
  .title-accent { height:4px; border-radius:2px; margin:-6px 0 14px 0; background:#1f4e78; }
  section[data-testid="stSidebar"] { display:none; }
</style>
""", unsafe_allow_html=True)

st.title("CCR LINE — OPS EXCELLENCE DASHBOARD")
st.markdown('<div class="title-accent"></div>', unsafe_allow_html=True)
st.caption("Source: OEE_Data (Google Sheet) · Company format: Daily & Period-wise")

try:
    data = fetch_sheet()
except Exception as e:
    st.error("Could not load data from the sheet. Please press Refresh / Rerun. "
             f"({type(e).__name__})")
    st.stop()

M = parse_model(data["rows"])
mtd = M["mtd"]
st.caption(f"Updated {data['fetched_at']} · auto-refreshes every ~15 min")

if st.button("↻ Refresh data"):
    fetch_sheet.clear()
    st.rerun()

# ---- yearly summary strip (very top) ----
def last_month_entry(ms):
    """Trend entry for the last completed calendar month (PKT)."""
    p5 = datetime.timezone(datetime.timedelta(hours=5))
    now = datetime.datetime.now(p5)
    lm_m = now.month - 1 or 12
    lm_y = now.year if now.month > 1 else now.year - 1
    want = f"{calendar.month_abbr[lm_m]}-{str(lm_y)[2:]}"
    for m in ms:
        if m["m"].strip() == want:
            return m
    cur = f"{calendar.month_abbr[now.month]}-{str(now.year)[2:]}"
    prev = None
    for m in ms:
        if m["m"].strip() == cur:
            return prev
        prev = m
    return None


if M["trend"]:
    ms = M["trend"]
    tgt = M["target"] or 4800
    ytd = sum(m["prod"] for m in ms)
    ypct = ytd / tgt if tgt else 0
    lm = last_month_entry(ms)
    st.subheader("Yearly Summary (FY 2025-26)")
    yc = st.columns(5)
    cards = [
        ("Yearly Target (MT)", f"{tgt:,.0f}", BLUE),
        ("YTD Achieved (MT)", f"{ytd:,.0f}", GREEN),
        ("Balance (MT)", f"{tgt - ytd:,.0f}", "#b45309"),
        ("% of Target", f"{ypct * 100:.1f}%", "#6d28d9"),
    ]
    if lm:
        cards.append((f"Last Month ({lm['m']})", f"{lm['prod']:,.0f}", "#0f766e"))
    for col, (lbl, val, ac) in zip(yc, cards):
        with col:
            st.markdown(
                f'<div class="kpi-card" style="--ac:{ac}">'
                f'<div class="lbl">{lbl}</div><div class="val">{val}</div></div>',
                unsafe_allow_html=True)
    st.progress(min(max(ypct, 0.0), 1.0))
    st.divider()

# ---- KPI cards ----
bal = mtd.get("plan", 0) - mtd.get("ach", 0)
kpis = [
    ("MTD Target (MT)", f"{mtd.get('plan', 0):.1f}", "planned production", BLUE),
    ("MTD Achieved (MT)", f"{mtd.get('ach', 0):.1f}",
     f"{pct(mtd.get('ach', 0) / (mtd.get('plan', 0) or 1))} of plan", GREEN),
    ("Balance (MT)", f"{bal:.1f}", "remaining to target", "#b45309"),
    ("MTD OEE", pct(mtd.get("oeeP", 0)), "production days avg", BLUE),
    ("Availability", pct(mtd.get("availP", 0)), "MTD average", "#0f766e"),
    ("Performance", pct(mtd.get("perfP", 0)), "achieved / planned", "#c2410c"),
    ("Quality", pct(mtd.get("qualP", 0)), "good length", "#4d7c0f"),
    ("Downtime", f"{mtd.get('dtHrs', 0):.1f} hrs",
     f"{mtd.get('dt', 0) / 60:.0f} min/day avg", RED),
]
cols = st.columns(4)
for i, (lbl, val, note, ac) in enumerate(kpis):
    with cols[i % 4]:
        st.markdown(
            f'<div class="kpi-card" style="--ac:{ac}">'
            f'<div class="lbl">{lbl}</div><div class="val">{val}</div>'
            f'<div class="note">{note}</div></div>', unsafe_allow_html=True)
    if i == 3:
        cols = st.columns(4)

st.divider()

# ---- OEE trend + period table (stacked full-width for mobile) ----
st.subheader("Daily & Period-wise — OEE %")
if M["daily"]:
    xs = [d["date"] for d in M["daily"]]
    ys = [d["oee"] * 100 for d in M["daily"]]
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=xs, y=ys, mode="lines+markers",
                             name="OEE %", line=dict(color=BLUE, width=2.5),
                             fill="tozeroy", fillcolor="rgba(31,78,120,0.12)"))
    fig.update_layout(height=300, margin=dict(l=10, r=10, t=10, b=10),
                      yaxis_title="OEE %", xaxis_title="Date")
    st.plotly_chart(fig, use_container_width=True, key="oee-trend")

st.subheader("Period-wise Summary")
if M["periods"]:
    df = pd.DataFrame([{
        "Period": p["p"], "Avail": pct(p["avail"]), "Perf": pct(p["perf"]),
        "Qual": pct(p["qual"]), "OEE": pct(p["oee"]),
        "Plan": round(p["plan"]), "Ach": round(p["ach"], 1)}
        for p in M["periods"]])
    st.dataframe(df, use_container_width=True, hide_index=True)

# ---- daily review + monthly review ----
def gauge(col, name, val, color, key):
    with col:
        fig = go.Figure(go.Indicator(
            mode="gauge+number", value=val * 100,
            number={"suffix": "%", "font": {"size": 22}},
            title={"text": name, "font": {"size": 12}},
            gauge={"axis": {"range": [0, 100]},
                   "bar": {"color": color},
                   "bgcolor": "#eef1f6"}))
        fig.update_layout(height=180, margin=dict(l=10, r=10, t=30, b=10))
        st.plotly_chart(fig, use_container_width=True, key=key)


st.subheader("Daily Review")
if M["daily"]:
    L = M["daily"][-1]
    st.write(f"**{L['date'].strftime('%d-%b-%Y')}** — latest finalized day")
    st.write(f"Planned: **{L['plan']:.1f} MT** · Achieved: **{L['ach']:.1f} MT** · "
             f"% Ach: **{pct(L['ach'] / L['plan'] if L['plan'] else 0)}**")
    st.write(f"Availability: **{pct(L['availP'])}** — run {L['run'] / 60:.1f} hrs / "
             f"available {L['avail'] / 60:.1f} hrs · Downtime: **{L['dt'] / 60:.1f} hrs**")
    d1, d2, d3, d4 = st.columns(4)
    for col, (name, val, color, key) in zip(
            (d1, d2, d3, d4),
            [("Performance", L["perfP"], AMBER, "d-perf"),
             ("Quality", L["qualP"], GREEN, "d-qual"),
             ("Availability", L["availP"], BLUE, "d-avail"),
             ("OEE", L["oee"], "#6d28d9", "d-oee")]):
        gauge(col, name, val, color, key)

st.divider()

st.subheader("Monthly Review (MTD)")
g1, g2, g3, g4 = st.columns(4)
for col, (name, val, color, key) in zip(
        (g1, g2, g3, g4),
        [("Performance", mtd.get("perfP", 0), AMBER, "m-perf"),
         ("Quality", mtd.get("qualP", 0), GREEN, "m-qual"),
         ("Availability", mtd.get("availP", 0), BLUE, "m-avail"),
         ("OEE", mtd.get("oeeP", 0), "#6d28d9", "m-oee")]):
    gauge(col, name, val, color, key)

st.table(pd.DataFrame([
    {"Metric": "Performance", "MTD Value": f"{mtd.get('perfP', 0) * 100:.1f}%"},
    {"Metric": "Quality", "MTD Value": f"{mtd.get('qualP', 0) * 100:.1f}%"},
    {"Metric": "Availability", "MTD Value": f"{mtd.get('availP', 0) * 100:.1f}%"},
    {"Metric": "OEE", "MTD Value": f"{mtd.get('oeeP', 0) * 100:.1f}%"},
]))

st.divider()

# ---- planned vs achieved ----
st.subheader("Daily Production — Planned vs Achieved (MT)")
if M["daily"]:
    xs = [d["date"].strftime("%d-%b") for d in M["daily"]]
    plans = [d["plan"] for d in M["daily"]]
    achs = [d["ach"] for d in M["daily"]]
    colors = []
    labels = []
    pcts = []
    for d in M["daily"]:
        r = d["ach"] / d["plan"] if d["plan"] > 0 else -1
        colors.append("#cbd5e1" if r < 0 else GREEN if r >= 1
                      else AMBER if r >= 0.7 else RED)
        pcts.append(r * 100 if r >= 0 else 0)
        if d["ach"] > 0 and r >= 0:
            labels.append(f"{d['ach']:.1f} MT ({r * 100:.0f}%)")
        else:
            labels.append("")
    fig = go.Figure()
    fig.add_trace(go.Bar(x=xs, y=plans, name="Planned", marker_color="#b0b9c5",
                         hovertemplate="%{x}<br>Planned: %{y:.1f} MT<extra></extra>"))
    fig.add_trace(go.Bar(x=xs, y=achs, name="Achieved", marker_color=colors,
                         text=labels, textposition="outside", textangle=-90,
                         textfont=dict(size=11),
                         customdata=pcts,
                         hovertemplate="%{x}<br>Achieved: %{y:.1f} MT (%{customdata:.0f}% of plan)<extra></extra>"))
    fig.update_layout(barmode="group", height=360,
                      margin=dict(l=10, r=10, t=40, b=10),
                      legend=dict(orientation="h", y=1.08))
    st.plotly_chart(fig, use_container_width=True, key="daily-prod")
    st.caption("Achieved bar color: green = plan met/exceeded, amber = partial, red = low")

# ---- downtime (stacked full-width for mobile) ----
st.subheader("MTD Downtime by Reason ⚠ pending verification")
st.caption("Reason-wise log (285.5 hrs) vs daily rows (52.0 hrs) — not yet reconciled.")
if M["reasons"]:
    rs = sorted(M["reasons"], key=lambda r: r["hrs"], reverse=True)
    fig = go.Figure(go.Bar(
        x=[r["hrs"] for r in rs], y=[r["name"] for r in rs],
        orientation="h", marker_color=AMBER,
        text=[f"{r['hrs']:.1f} h" for r in rs], textposition="outside"))
    fig.update_layout(height=max(220, 40 * len(rs)),
                      margin=dict(l=10, r=10, t=10, b=10),
                      xaxis_title="Hours")
    st.plotly_chart(fig, use_container_width=True, key="dt-reasons")
st.subheader("Daily Downtime Trend")
if M["daily"]:
    xs = [d["date"].strftime("%d-%b") for d in M["daily"]]
    hs = [d["dt"] / 60 for d in M["daily"]]
    colors = [RED if h >= 10 else AMBER if h > 0 else "#e2e8f0" for h in hs]
    fig = go.Figure(go.Bar(x=xs, y=hs, marker_color=colors,
                           text=[f"{h:.1f}" for h in hs], textposition="outside"))
    fig.update_layout(height=320, margin=dict(l=10, r=10, t=10, b=10),
                      yaxis_title="Hours")
    st.plotly_chart(fig, use_container_width=True, key="dt-trend")

st.divider()

# ---- monthly production ----
st.subheader("Month-wise Production (FY 2025-26)")
if M["trend"]:
    ms = M["trend"]
    tgt = M["target"] or 4800
    cum_tgt = [tgt / 12 * (i + 1) for i in range(len(ms))]
    run_cum, cum_vals = 0, []
    for m in ms:
        run_cum += m["prod"]
        cum_vals.append(run_cum)
    fig = go.Figure()
    fig.add_trace(go.Bar(x=[m["m"] for m in ms], y=[m["prod"] for m in ms],
                         name="Production", marker_color=BLUE,
                         text=[f"{m['prod']:.0f}" if m["prod"] > 0 else "" for m in ms],
                         textposition="outside", textfont=dict(size=11)))
    fig.add_trace(go.Scatter(x=[m["m"] for m in ms], y=cum_vals,
                             name="Cumulative", mode="lines+markers",
                             line=dict(color=GREEN, width=2.5, dash="dash"),
                             yaxis="y2"))
    fig.add_trace(go.Scatter(x=[m["m"] for m in ms], y=cum_tgt,
                             name="Target path", mode="lines",
                             line=dict(color="#94a3b8", width=1.5, dash="dot"),
                             yaxis="y2"))
    fig.update_layout(height=340, margin=dict(l=10, r=10, t=30, b=10),
                      yaxis=dict(title="Monthly MT"),
                      yaxis2=dict(title="Cumulative MT", overlaying="y", side="right"),
                      legend=dict(orientation="h", y=1.05))
    st.plotly_chart(fig, use_container_width=True, key="monthly-prod")
    ytd = sum(m["prod"] for m in ms) if ms else 0
    st.write(f"**YTD: {ytd:,.0f} MT / {tgt:,.0f} MT target ({ytd / tgt * 100:.1f}%)** — "
             f"balance **{tgt - ytd:,.0f} MT**")

st.divider()
st.caption("This dashboard reads data from the OEE_Data tab of the Google Sheet — "
           "updates appear automatically (cached ~15 min). Share only this app link "
           "with management; no need to share the full sheet.")
