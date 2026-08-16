import io
from datetime import date, timedelta

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from supabase import create_client

GOAL_KG = 80.0

st.set_page_config(page_title="Recomp tracker", page_icon="📈", layout="centered")


@st.cache_resource
def get_client():
    url = st.secrets["SUPABASE_URL"]
    key = st.secrets["SUPABASE_KEY"]
    return create_client(url, key)


sb = get_client()


def load_weights() -> pd.DataFrame:
    res = sb.table("weight_entries").select("*").order("entry_date").execute()
    df = pd.DataFrame(res.data)
    if not df.empty:
        df["entry_date"] = pd.to_datetime(df["entry_date"]).dt.date
    return df


def load_visits() -> pd.DataFrame:
    res = sb.table("gym_visits").select("*").order("visit_date").execute()
    df = pd.DataFrame(res.data)
    if not df.empty:
        df["visit_date"] = pd.to_datetime(df["visit_date"]).dt.date
    return df


def upsert_weight(d: date, weight: float, bodyfat: float | None):
    sb.table("weight_entries").upsert(
        {"entry_date": d.isoformat(), "weight_kg": weight, "bodyfat_pct": bodyfat},
        on_conflict="entry_date",
    ).execute()


def log_visit(d: date):
    sb.table("gym_visits").upsert(
        {"visit_date": d.isoformat()}, on_conflict="visit_date"
    ).execute()


def iso_week_start(d: date) -> date:
    return d - timedelta(days=d.weekday())


weights_df = load_weights()
visits_df = load_visits()

st.markdown("### Body weight")

col1, col2 = st.columns([2, 1])
with col1:
    if not weights_df.empty:
        latest = weights_df.iloc[-1]
        delta = None
        if len(weights_df) > 1:
            prev = weights_df.iloc[-2]
            delta = round(latest["weight_kg"] - prev["weight_kg"], 1)
        st.metric(
            "Current weight",
            f"{latest['weight_kg']:.1f} kg",
            delta=f"{delta:+.1f} kg" if delta is not None else None,
            delta_color="inverse",
        )
    else:
        st.metric("Current weight", "—")
with col2:
    to_goal = max(0.0, weights_df.iloc[-1]["weight_kg"] - GOAL_KG) if not weights_df.empty else None
    st.metric("To goal (80.0 kg)", f"{to_goal:.1f} kg" if to_goal is not None else "—")

with st.form("weight_form", clear_on_submit=True):
    c1, c2, c3 = st.columns(3)
    w_date = c1.date_input("Date", value=date.today())
    w_weight = c2.number_input("Weight (kg)", min_value=0.0, max_value=400.0, step=0.1, format="%.1f")
    w_bf = c3.number_input("Body fat % (optional)", min_value=0.0, max_value=70.0, step=0.1, format="%.1f", value=0.0)
    submitted = st.form_submit_button("Log weight")
    if submitted:
        if w_weight <= 0:
            st.error("Enter a weight greater than 0.")
        else:
            upsert_weight(w_date, w_weight, w_bf if w_bf > 0 else None)
            st.rerun()

if not weights_df.empty:
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=weights_df["entry_date"], y=weights_df["weight_kg"],
        mode="lines+markers", name="Weight",
        line=dict(color="#34D399", width=2),
        marker=dict(size=6, color="#5EEAD4"),
        hovertemplate="%{x|%Y-%m-%d}<br>%{y:.1f} kg<extra></extra>",
    ))
    fig.add_hline(y=GOAL_KG, line_dash="dash", line_color="#F0A868",
                   annotation_text="goal 80.0", annotation_position="top right")
    fig.update_layout(
        height=320, margin=dict(l=10, r=10, t=20, b=10),
        template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        xaxis_title=None, yaxis_title="kg", showlegend=False,
    )
    st.plotly_chart(fig, use_container_width=True)
else:
    st.caption("Log your first weigh-in to see the chart.")

st.markdown("### Third Space sessions")

today = date.today()
this_week = iso_week_start(today)
logged_today = (not visits_df.empty) and (today in set(visits_df["visit_date"]))

bcol1, bcol2 = st.columns([1, 2])
with bcol1:
    if st.button("Logged today ✓" if logged_today else "Log today's session", disabled=logged_today):
        log_visit(today)
        st.rerun()

if not visits_df.empty:
    week_keys = [this_week - timedelta(weeks=i) for i in range(13, -1, -1)]
    visits_df["week"] = visits_df["visit_date"].apply(iso_week_start)
    counts = visits_df.groupby("week").size()
    week_counts = [int(counts.get(k, 0)) for k in week_keys]
    colors = ["#5EEAD4" if k == this_week else "#F0A868" for k in week_keys]

    total_sessions = len(visits_df)
    this_week_count = week_counts[-1]
    streak = 0
    cursor = this_week
    while counts.get(cursor, 0) >= 3:
        streak += 1
        cursor -= timedelta(weeks=1)

    k1, k2, k3 = st.columns(3)
    k1.metric("This week", this_week_count)
    k2.metric("Streak (≥3/wk)", streak)
    k3.metric("Total sessions", total_sessions)

    fig2 = go.Figure()
    fig2.add_trace(go.Bar(
        x=[k.strftime("%m-%d") for k in week_keys], y=week_counts,
        marker_color=colors,
        hovertemplate="week of %{x}<br>%{y} sessions<extra></extra>",
    ))
    fig2.add_hline(y=3, line_dash="dash", line_color="#4A5568")
    fig2.update_layout(
        height=220, margin=dict(l=10, r=10, t=10, b=10),
        template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        yaxis_title=None, xaxis_title=None,
    )
    st.plotly_chart(fig2, use_container_width=True)
else:
    st.caption("No sessions logged yet.")

st.markdown("### Export")

if not weights_df.empty or not visits_df.empty:
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        weights_df.rename(columns={"entry_date": "date", "weight_kg": "weight_kg", "bodyfat_pct": "bodyfat_pct"}) \
            .drop(columns=["id"], errors="ignore").to_excel(writer, sheet_name="weight", index=False)
        visits_df.rename(columns={"visit_date": "date"}).drop(columns=["id", "week"], errors="ignore") \
            .to_excel(writer, sheet_name="gym_sessions", index=False)
    st.download_button(
        "Download as Excel (.xlsx)",
        data=buffer.getvalue(),
        file_name=f"recomp_export_{today.isoformat()}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
else:
    st.caption("Nothing to export yet.")
