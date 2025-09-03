# app.py
import os
import re
import time
import datetime as dt
from typing import Dict, Any, List, Optional

from monitor_engine import MonitorEngine
import streamlit as st
from streamlit_autorefresh import st_autorefresh

from resy_client import ResyClient, ResyClientError
from discord_webhook import DiscordWebhook, DiscordEmbed

from dotenv import load_dotenv

load_dotenv()


WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")

def sendWebhook(restaurauntName, date, time_str, partySize, link, type_str, image):
    webhook = DiscordWebhook(url=WEBHOOK_URL, rate_limit_retry=True)
    embed = DiscordEmbed(title=restaurauntName, color='0x2ecc71')
    embed.set_timestamp()
    embed.add_embed_field(name='Date:', value=date)
    embed.add_embed_field(name='Time:', value=time_str)
    embed.add_embed_field(name='Party Size:', value=str(partySize))
    embed.add_embed_field(name='Type:', value=type_str)
    embed.add_embed_field(name='Link:', value=link)
    embed.set_thumbnail(url=image)
    webhook.add_embed(embed)
    webhook.execute()

# ---------- Constants ----------
REFRESH_EVERY_MS = 120_000  # 2 minutes
TORONTO_TZ = dt.timezone(dt.timedelta(hours=-4))  # Streamlit will render in server TZ anyway

# ---------- Utilities ----------
RESY_URL_RE = re.compile(
    r"^https?://(www\.)?resy\.com/cities/([^/]+)/venues/([^/?#]+)",
    re.IGNORECASE
)

def parse_resy_url(url: str):
    """
    Extract (city_slug, venue_slug) from a Resy venue URL like:
    https://resy.com/cities/toronto-on/venues/casa-paco
    """
    m = RESY_URL_RE.match(url.strip())
    if not m:
        from urllib.parse import urlparse
        path = urlparse(url).path.strip("/")
        parts = path.split("/")
        if len(parts) >= 4 and parts[0] == "cities" and parts[2] == "venues":
            return parts[1], parts[3]
        raise ValueError("URL does not look like a valid Resy venue URL")
    return m.group(2), m.group(3)


def times_12h_options() -> List[str]:
    # 15-minute grid looks clean; adjust to your taste
    opts = []
    for hour in range(0, 24):
        for minute in (0, 15, 30, 45):
            t = dt.time(hour=hour, minute=minute)
            opts.append(t.strftime("%I:%M %p").lstrip("0"))
    return opts


def to_24h_hhmm(t12: str) -> str:
    """Convert '7:30 PM' → '19:30' (string)."""
    t = dt.datetime.strptime(t12.upper(), "%I:%M %p").time()
    return f"{t.hour:02d}:{t.minute:02d}"


def daterange(start: dt.date, end: dt.date) -> List[str]:
    """Inclusive date strings YYYY-MM-DD."""
    out = []
    cur = start
    while cur <= end:
        out.append(cur.strftime("%Y-%m-%d"))
        cur += dt.timedelta(days=1)
    return out


# ---------- Client ----------
RESY_API_KEY = os.getenv("RESY_API_KEY")
USER_AGENT = os.getenv(
    "USER_AGENT",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36 Edg/137.0.0.0"
)
REQUEST_TIMEOUT = float(os.getenv("REQUEST_TIMEOUT", "12.0"))

client = ResyClient(
    api_key=RESY_API_KEY,
    user_agent=USER_AGENT,
    request_timeout=REQUEST_TIMEOUT,
)


# ---- ENGINE and Run Check ----

def run_check(item: Dict[str, Any]) -> None:
    """Update item in-place by checking availability."""
    try:
        # 1) Calendar pass (only dates with reservation == 'available')
        start = item["start_date"].strftime("%Y-%m-%d")
        end = item["end_date"].strftime("%Y-%m-%d")

        ts = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{ts}] HTTP GET /4/venue/calendar",
      f"params={{'venue_id': {item['venue_id']}, 'num_seats': {item['party_size']}, 'start_date': '{start}', 'end_date': '{end}'}}")


        cal = client.get_calendar(item["venue_id"], item["party_size"], start, end)

        available_dates = [
            x["date"] for x in cal.get("scheduled", [])
            if x.get("inventory", {}).get("reservation") == "available"
        ]

        if not available_dates:
            item["status"] = "none"
            item["status_msg"] = "Nothing available (calendar)"
            item["found_slots"] = []
            item["error"] = None
            return

        # 2) For each date w/ availability, call /4/find and filter to chosen times
        matches = []
        # Keep your logic: only call find if calendar showed dates
        for date_str in available_dates:
            try:

                ts = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                print(f"[{ts}] HTTP POST /4/find",
                    f"payload={{'day': '{date_str}', 'lat': 0, 'long': 0, 'party_size': {item['party_size']}, 'venue_id': '{item['venue_id']}'}}")
        

                find_json = client.find(item["venue_id"], item["party_size"], date_str, None)
                venues = find_json.get("results", {}).get("venues", [])
                if not venues:
                    continue

                
                for slot in venues[0].get("slots", []):
                    # Resy format seems: 'YYYY-MM-DD HH:MM:SS'
                    t = slot["date"]["start"].split(" ")[1].rsplit(":", 1)[0]  # → HH:MM
                    if t in item["times_24"]:
                        matches.append({
                            "date": date_str,
                            "time_24": t,
                            "type": slot["config"].get("type", "reservation"),
                            "time_filter": slot["config"].get("time_filter", ""),
                            "image": venues[0]['templates'][venues[0]['venue']['default_template']]['images'][0]
                        })
            except ResyClientError as e:
                # Keep going on per-date errors
                continue

        if matches:
            # --- NEW single-send logic ---
            if item.get("only_one_webhook") and item.get("webhook_sent"):
                # Already sent the one-time webhook before; don't send again.
                pass
            else:
                if item.get("only_one_webhook"):
                    # Send a single webhook for the first matching slot only
                    m = matches[0]
                    dt24 = dt.datetime.strptime(m["time_24"], "%H:%M").time()
                    time_12 = dt24.strftime("%I:%M %p").lstrip("0")

                    # If multiple matches, indicate that in the type field
                    if len(matches) > 1:
                        print(matches)
                        sendWebhook(item["venue_name"], m["date"], time_12, item["party_size"], item["url"], "MANY MANY MANY", m["image"])
                    else:
                        sendWebhook(item["venue_name"], m["date"], time_12, item["party_size"], item["url"], m["type"], m["image"])
                    item["webhook_sent"] = True

                else:
                    # Original behavior: send for every matched slot
                    for m in matches:
                        dt24 = dt.datetime.strptime(m["time_24"], "%H:%M").time()
                        time_12 = dt24.strftime("%I:%M %p").lstrip("0")
                        sendWebhook(item["venue_name"], m["date"], time_12, item["party_size"], item["url"], m["type"])

            item["status"] = "found"
            item["status_msg"] = "🎉 Found reservations!"
            item["found_slots"] = matches
            item["error"] = None

            # Stop polling this monitor after first match (default True)
            if item.get("stop_on_match", True):
                item["active"] = False
        else:
            item["status"] = "none"
            item["status_msg"] = "Nothing available for selected times"
            item["found_slots"] = []
            item["error"] = None


    except ResyClientError as e:
        item["status"] = "error"
        item["status_msg"] = f"API error {e.status_code or ''}".strip()
        item["error"] = e.details.get("text") or e.details.get("error") or str(e)
    except Exception as e:
        item["status"] = "error"
        item["status_msg"] = "Unexpected error"
        item["error"] = str(e)
    finally:
        item["last_checked"] = dt.datetime.now()

@st.cache_resource
def get_engine():
    # run_check is your existing function that does calendar → find → webhook
    return MonitorEngine(checker=run_check)

engine = get_engine()

# ---------- Streamlit App ----------
st.set_page_config(page_title="Resy Monitor", page_icon="🍽️", layout="centered")

# App state
if "monitors" not in st.session_state:
    st.session_state.monitors: List[Dict[str, Any]] = []

if "last_refresh" not in st.session_state:
    st.session_state.last_refresh = time.time()


st.markdown(
    """
    <style>
    /* Beautify bordered containers */
    div[data-testid="stContainer"] > div:has(> div[data-testid="stVerticalBlock"]) {
        background: #1e1e1e;
        border: 1px solid #333 !important;
        border-radius: 12px;
        box-shadow: 0 2px 6px rgba(0,0,0,0.25);
        padding: 16px;
        margin-bottom: 16px;
    }

    .pill { padding: 2px 8px; border-radius: 999px; font-size: 12px; display:inline-block; }
    .pill-ok { background: #E6F4EA; color: #137333; }
    .pill-warn { background: #FCE8E6; color: #B31412; }
    .pill-run { background: #E8F0FE; color: #174EA6; }
    .pill-stop { background: #FFF4E5; color: #8A4A00; }
    .meta { color: #9ca3af; font-size: 12px; margin-top: 2px; }
    .name { font-weight: 600; font-size: 16px; }
    .stButton > button { white-space: nowrap; }

    /* tiny animated spinner */
    .spinner {
    display:inline-block;
    width: 14px; height: 14px;
    border: 2px solid rgba(255,255,255,.25);
    border-top-color: #9ca3af;
    border-radius: 50%;
    animation: spin .8s linear infinite;
    margin-right: 6px;
    vertical-align: -2px;
    }
    @keyframes spin { to { transform: rotate(360deg); } }
    </style>
    """,
    unsafe_allow_html=True,
)


st.title("🍽️ Resy Reservation Monitor")

with st.expander("Add a restaurant to monitor", expanded=True):
    with st.form("add_monitor"):
        col1, col2 = st.columns([2, 1])
        with col1:
            url = st.text_input("Resy venue URL", placeholder="https://resy.com/cities/toronto-on/venues/casa-paco")
        with col2:
            party_size = st.number_input("Party size", min_value=1, max_value=10, value=2, step=1)

        c3, c4 = st.columns(2)
        with c3:
            start_date = st.date_input("Start date", value=dt.date.today())
        with c4:
            end_date = st.date_input("End date", value=dt.date.today())

        time_options = times_12h_options()
        picked_times_12h = st.multiselect(
            "Times (12-hour, select multiple)",
            options=time_options,
            default=["7:00 PM", "7:30 PM", "8:00 PM"]
        )

        only_one = st.checkbox("Send only one webhook (first match only)", value=True)

        submitted = st.form_submit_button("➕ Add to monitor")
        if submitted:
            try:
                if not url or not picked_times_12h:
                    st.error("Please provide a valid URL and at least one time.")
                elif end_date < start_date:
                    st.error("End date must be the same as or after start date.")
                else:
                    city, slug = parse_resy_url(url.strip())
                    venue_info = client.lookup_venue(city, slug)
                    venue_id = str(venue_info.get("id")["resy"])
                    venue_name = venue_info.get("name", slug.replace("-", " ").title())

                    # Save monitor entry
                    times_24 = [to_24h_hhmm(t) for t in picked_times_12h]

                    item = {
                    "id": f"{venue_id}-{int(time.time()*1000)}",
                    "venue_id": venue_id,
                    "venue_name": venue_name,
                    "url": url.strip(),
                    "party_size": int(party_size),
                    "start_date": start_date,
                    "end_date": end_date,
                    "times_24": times_24,
                    "times_12": picked_times_12h,
                    "last_checked": None,
                    "status": "polling",
                    "status_msg": "Monitoring…",
                    "found_slots": [],
                    "error": None,
                    "created_at": dt.datetime.now(),
                    "only_one_webhook": bool(only_one),
                    "webhook_sent": False,
                    "stop_on_match": True,
                    "active": True,
                }
                
                # do one fast synchronous check so the card shows immediately
                with st.spinner(f"Checking {venue_name}…"):
                    run_check(item)

                st.session_state.monitors.append(item)   # keep for UI state if you like
                engine.add(item)                         # <-- NEW: background engine owns polling

                st.success(f"Added **{venue_name}** for party of {party_size}.")
            except ResyClientError as e:
                st.error(f"Resy API error: {e.message} ({e.status_code or 'n/a'})")
            except Exception as e:
                st.error(f"Failed to add monitor: {e}")



st.subheader("Currently monitored")
st_autorefresh(interval=15_000, key="ui_tick")  # periodic UI update (engine polls independently)


# HAS TO MATCH ENGINE INTERVAL
ENGINE_POLL_INTERVAL_SEC = 120

def eta_text(item):
    last_ts = item["last_checked"].timestamp() if item.get("last_checked") else 0
    elapsed = max(0, time.time() - last_ts)
    remain = max(0, ENGINE_POLL_INTERVAL_SEC - int(elapsed))
    m, s = divmod(remain, 60)
    if m: return f"{m}m {s}s"
    return f"{s}s"


def status_pill(item):
    if item.get("status") == "found":
        return '<span class="pill pill-ok">✅ Found</span>'
    if item.get("status") == "none":
        return '<span class="pill pill-warn">❌ None</span>'
    if item.get("status") == "error":
        return '<span class="pill pill-warn">⚠️ Error</span>'
    return '<span class="pill pill-run">🔄 Polling</span>'

live_items = engine.list()

to_remove = []

if not live_items:
    st.info("No restaurants are being monitored yet. Add one above!")
else:
    for item in live_items:
        with st.container(border=True):
            # everything inside here will actually be inside the box
            top_cols = st.columns([4, 2, 2, 1])
            with top_cols[0]:
                st.markdown(
                    f'<div class="name">{item["venue_name"]}</div>'
                    f'<div class="meta">{item["url"]}</div>',
                    unsafe_allow_html=True
                )
            with top_cols[1]:
                st.write(f"Party: **{item['party_size']}**")
                st.write(f"Dates: **{item['start_date']} → {item['end_date']}**")
            with top_cols[2]:
                st.write("Times:")
                st.write(", ".join(item["times_12"]))
            with top_cols[3]:
                if st.button("Remove", key=f"rm-{item['id']}", use_container_width=True):
                    to_remove.append(item["id"])

            pill_html = status_pill(item)
            c1, c2 = st.columns([1.4, 8])
            with c1:
                st.markdown(pill_html, unsafe_allow_html=True)
            with c2:
                last = item["last_checked"].strftime("%Y-%m-%d %H:%M:%S") if item.get("last_checked") else "—"
                if item.get("status") == "found":
                    st.markdown(f"**Matched!**  •  Last checked: {last}")
                elif item.get("status") == "none":
                     st.markdown(f'<span class="spinner"></span> Waiting • next check in {eta_text(item)}  •  Last checked: {last}', unsafe_allow_html=True)
                elif item.get("status") == "error":
                    st.markdown(f"Error: {item.get('status_msg', 'Unknown')}  •  Last checked: {last}")
                else:
                    st.markdown(f"Polling…  •  Last checked: {last}")


# Apply removals to engine
for _id in to_remove:
    engine.remove(_id)

if to_remove:
    st.rerun()
