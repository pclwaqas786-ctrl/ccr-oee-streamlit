"""Ops Excellence Dash Board — standard format (separate page).

Executive summary view pulling live data from the same OEE_Data tab
of the company Google Sheet (via the baked data.json).
"""
import json
import re
import calendar
import datetime

import requests
import pandas as pd
import streamlit as st
import plotly.graph_objects as go

BLUE = "#1f4e78"
GREEN = "#2e7d32"
AMBER = "#c77700"
RED = "#c0392b"

st.set_page_config(page_title="Ops Excellence Dash Board", layout="wide")

# ---------------------------------------------------------------- data ----
@st.cache_data(ttl=900)
def fetch_sheet():
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
         "target": 0.0, "shift": []}
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
                "oee": num(r[11]), "status": str(r[12] or ""),
                "ach_blank": str(r[7] or "").strip() == ""})
            continue
        if re.match(r"^MTD TOTAL", lab, re.I):
            M["mtd"] = {"avail": num(r[2]), "dt": num(r[3]), "run": num(r[4]),
                        "availP": num(r[5]), "plan": num(r[6]), "ach": num(r[7]),
                        "perfP": num(r[8]), "qualP": num(r[10]),
                        "oeeP": num(r[11]), "dtHrs": num(r[13])}
            continue
        if re.match(r"^MTD Downtime by Reason", lab, re.I):
            section = "reasons"; continue
        if re.match(r"^MTD Production by Shift", lab, re.I):
            section = "shift"; continue
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
        elif section == "shift" and lab and re.match(r"^Shift", lab, re.I):
            M["shift"].append({"name": lab, "prod": num(r[2])})
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


def fy_label():
    """Pakistan FY (Jul-Jun), e.g. Oct 2026 -> 'FY 2026-27'."""
    p5 = datetime.timezone(datetime.timedelta(hours=5))
    now = datetime.datetime.now(p5)
    if now.month >= 7:
        return f"FY {now.year}-{str(now.year + 1)[2:]}"
    return f"FY {now.year - 1}-{str(now.year)[2:]}"


def kpi_card(lbl, val, note="", ac=BLUE):
    st.markdown(
        f'<div class="kpi-card" style="--ac:{ac}">'
        f'<div class="lbl">{lbl}</div><div class="val">{val}</div>'
        + (f'<div class="note">{note}</div>' if note else '') +
        '</div>', unsafe_allow_html=True)


# ------------------------------------------------------------------ UI ----
st.markdown("""
<style>
  .kpi-card { background:#ffffff; border:1px solid #d9e1ea; border-left:5px solid var(--ac,#1f4e78);
    border-radius:10px; padding:12px 14px; box-shadow:0 1px 3px rgba(16,42,67,.08); }
  .kpi-card .lbl { font-size:11px; color:#64748b; text-transform:uppercase; letter-spacing:.6px; }
  .kpi-card .val { font-size:28px; font-weight:700; color:#1c2733; }
  .kpi-card .note { font-size:12px; color:#64748b; }
  h1, h2, h3 { color:#1c2733; }
  .title-accent { height:4px; border-radius:2px; margin:-6px 0 14px 0; background:#1f4e78; }
</style>
""", unsafe_allow_html=True)

st.title("Ops Excellence Dash Board")
st.markdown('<div class="title-accent"></div>', unsafe_allow_html=True)

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

FY = fy_label()

# ---- monthly performance ----
st.subheader("Monthly Performance")
mp, ma = mtd.get("plan", 0), mtd.get("ach", 0)
mpct = ma / mp if mp else 0
mc = st.columns(4)
for col, (lbl, val, note, ac) in zip(mc, [
        ("Monthly Target (MT)", f"{mp:,.1f}", "Value tons", BLUE),
        ("Monthly Achieved (MT)", f"{ma:,.1f}", f"{mpct * 100:.1f}% of target", GREEN),
        ("Balance (MT)", f"{mp - ma:,.1f}", "remaining to target", "#b45309"),
        ("% of Target", f"{mpct * 100:.1f}%", "achieved / target", "#6d28d9"),
]):
    with col:
        kpi_card(lbl, val, note, ac)
st.progress(min(max(mpct, 0.0), 1.0))
st.divider()

# ---- yearly performance ----
st.subheader(f"Yearly Performance ({FY})")
tgt = M["target"] or 4800
ytd = sum(m["prod"] for m in M["trend"]) if M["trend"] else 0
ypct = ytd / tgt if tgt else 0
yc = st.columns(4)
for col, (lbl, val, note, ac) in zip(yc, [
        ("Yearly Target (MT)", f"{tgt:,.0f}", "Value tons", BLUE),
        ("YTD Achieved (MT)", f"{ytd:,.0f}", f"{ypct * 100:.1f}% of target", GREEN),
        ("Balance (MT)", f"{tgt - ytd:,.0f}", "remaining to target", "#b45309"),
        ("% of Target", f"{ypct * 100:.1f}%", "achieved / target", "#6d28d9"),
]):
    with col:
        kpi_card(lbl, val, note, ac)
st.progress(min(max(ypct, 0.0), 1.0))
st.divider()

# ---- OEE summary ----
st.subheader("OEE Summary (MTD)")
oc = st.columns(4)
for col, (lbl, val, ac) in zip(oc, [
        ("Availability", pct(mtd.get("availP", 0)), "#0f766e"),
        ("Performance", pct(mtd.get("perfP", 0)), "#c2410c"),
        ("Quality", pct(mtd.get("qualP", 0)), "#4d7c0f"),
        ("OEE", pct(mtd.get("oeeP", 0)), BLUE),
]):
    with col:
        kpi_card(lbl, val, "", ac)
st.divider()

# ---- month-wise production ----
if M["trend"]:
    st.subheader(f"Month-wise Production ({FY})")
    ms = [m["m"] for m in M["trend"]]
    ps = [m["prod"] for m in M["trend"]]
    fig = go.Figure(go.Bar(x=ms, y=ps, marker_color=BLUE,
                           text=[f"{v:,.0f}" for v in ps],
                           textposition="outside", textfont=dict(size=12),
                           hovertemplate="%{x}: %{y:,.1f} MT<extra></extra>"))
    fig.update_layout(height=380, margin=dict(l=10, r=10, t=40, b=10),
                      yaxis_title="MT")
    st.plotly_chart(fig, use_container_width=True, key="ops-monthly")
    st.caption(f"YTD: {ytd:,.0f} MT / {tgt:,.0f} MT target ({ypct * 100:.1f}%)"
               f" — balance {tgt - ytd:,.0f} MT")

# ---- shift-wise production ----
if M["shift"]:
    st.subheader("Shift-wise Production (MTD)")
    sns = [s["name"] for s in M["shift"]]
    svs = [s["prod"] for s in M["shift"]]
    fig = go.Figure(go.Bar(x=svs, y=sns, orientation="h",
                           marker_color=[BLUE, "#5b9bd5"],
                           text=[f"{v:.1f} MT" for v in svs],
                           textposition="outside", textfont=dict(size=13),
                           hovertemplate="%{y}: %{x:.1f} MT<extra></extra>"))
    fig.update_layout(height=220, margin=dict(l=10, r=60, t=10, b=10),
                      xaxis_title="MT")
    st.plotly_chart(fig, use_container_width=True, key="ops-shift")

st.divider()
st.caption("Source: OEE_Data tab of the Google Sheet — updates appear automatically (cached ~15 min).")
