import os
import re
from datetime import date, timedelta, datetime, timezone
from urllib.parse import urlparse

import streamlit as st
from resy_client import ResyClient, ResyClientError

# ------------------------------
# Config / client
# ------------------------------
RESY_API_KEY = "VbWk7s3L4KiK5fzlO7JD3Q5EYolJI7n5"
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

# ------------------------------
# Helpers
# ------------------------------
RESY_URL_RE = re.compile(
    r"^https?://(www\.)?resy\.com/cities/([^/]+)/venues/([^/?#]+)",
    re.IGNORECASE
)

def parse_resy_url(url: str):
    """
    Extract (city_slug, venue_slug) from a Resy venue URL like:
    https://resy.com/cities/toronto-on/venues/casa-paco
    """
    m = RESY_URL_RE.match(url)
    if not m:
        path = urlparse(url).path.strip("/")
        parts = path.split("/")
        if len(parts) >= 4 and parts[0] == "cities" and parts[2] == "venues":
            return parts[1], parts[3]
        raise ValueError("URL does not look like a valid Resy venue URL")
    return m.group(2), m.group(3)

def date_list(start: date, end: date):
    d = start
    out = []
    while d <= end:
        out.append(d.isoformat())
        d += timedelta(days=1)
    return out

def get_day_slots(client: ResyClient, venue_id: str, day_str: str, num_seats: int):
    """
    Query /4/find for a specific day to get individual time options.
    Returns a list of 'HH:MM' 24h strings.
    """
    url = "https://api.resy.com/4/find"
    params = {"day": day_str, "party_size": num_seats, "venue_id": venue_id}
    resp = client._request("GET", url, params=params)  # reuse headers/retries
    data = resp.json()

    print(data)

    slots = []

    def collect(obj):
        if isinstance(obj, dict):
            # look for structures that have 'date' + 'time'
            if "date" in obj and "time" in obj:
                t = str(obj["time"])  # '17:30:00'
                slots.append(t[:5])   # '17:30'
            for v in obj.values():
                collect(v)
        elif isinstance(obj, list):
            for v in obj:
                collect(v)

    collect(data)
    return sorted(set(slots))

def to_24h(label: str):
    """Convert '5:30 PM' -> '17:30'."""
    label = label.strip().upper()
    # quick parse for 'H:MM AM/PM'
    import datetime as _dt
    try:
        dt = _dt.datetime.strptime(label, "%I:%M %p")
        return dt.strftime("%H:%M")
    except Exception:
        return label  # fallback, let intersection fail if malformed

def pretty_name(slug: str):
    return slug.replace("-", " ").title()

# ------------------------------
# Streamlit UI
# ------------------------------
st.set_page_config(page_title="Resy Reservation Monitor", layout="centered")
st.title("📆 Resy Reservation Monitor")

if RESY_API_KEY == "PUT-YOUR-API-KEY-HERE":
    st.warning("Set the RESY_API_KEY environment variable before checking availability.")

# State
if "monitored" not in st.session_state:
    # each item:
    # { url, city, slug, venue_id, num_seats, dates [YYYY-MM-DD],
    #   times_24 ['HH:MM'], status, last_checked }
    st.session_state.monitored = []

if "page" not in st.session_state:
    st.session_state.page = "add"

if "auto_refresh" not in st.session_state:
    st.session_state.auto_refresh = True

# --- Auto-refresh every 100s using a simple JS reload (stable across versions) ---
if st.session_state.auto_refresh:
    st.markdown(
        "<script>setTimeout(function(){window.location.reload();}, 100000);</script>",
        unsafe_allow_html=True,
    )

with st.container():
    st.markdown("### ➕ Add a venue to monitor")
    with st.form("add_form", enter_to_submit=False):
        url = st.text_input(
            "Resy venue URL",
            placeholder="https://resy.com/cities/toronto-on/venues/casa-paco"
        )
        num_seats = st.number_input("Party size", min_value=1, max_value=12, value=2, step=1)

        c1, c2 = st.columns(2)
        with c1:
            start_date = st.date_input("Start date", value=date.today())
        with c2:
            end_date = st.date_input("End date", value=date.today() + timedelta(days=7))

        # Time choices (like your old UI)
        time_labels = ["5:00 PM", "5:30 PM", "6:00 PM", "6:30 PM",
                       "7:00 PM", "7:30 PM", "8:00 PM"]
        chosen_labels = st.multiselect("Select target times (optional)", time_labels, default=[])

        submit = st.form_submit_button("➕ Add to Monitor")
        if submit:
            if not url.strip():
                st.error("Please paste a venue URL.")
            elif start_date > end_date:
                st.error("Start date must be on/before end date.")
            else:
                try:
                    city, slug = parse_resy_url(url.strip())
                    venue_info = client.lookup_venue(city, slug)
                    
                    venue_id = str(venue_info.get("id")['resy'])

                    print(city, slug)
                    print(venue_id)

                    if not venue_id:
                        raise ResyClientError("Missing venue id from lookup", status_code=502)

                    item = {
                        "url": url.strip(),
                        "city": city,
                        "slug": slug,
                        "venue_id": venue_id,
                        "num_seats": int(num_seats),
                        "dates": date_list(start_date, end_date),
                        "times_24": [to_24h(lbl) for lbl in chosen_labels],  # [] -> any time
                        "status": "Waiting",
                        "last_checked": None,
                    }
                    st.session_state.monitored.append(item)
                    st.success(f"Monitoring **{pretty_name(slug)}** ({len(item['dates'])} day(s)).")
                    st.rerun()
                except ValueError as e:
                    st.error(str(e))
                except ResyClientError as e:
                    st.error(f"Lookup failed: {e.message} (status={e.status_code})")

st.divider()
st.subheader("📡 Currently Monitored")

def check_item(item: dict) -> dict:
    """Check availability for one monitored item; returns updated item."""
    found = []

    print(item)
    for d in item["dates"]:
        try:
            if item["times_24"]:
                # Try specific time matches via /4/find
                try:
                    slots = get_day_slots(client, item["venue_id"], d, item["num_seats"])
                except ResyClientError as e:

                    print("wada")
                    # Fallback: date-level check if /4/find complains (e.g., 400)
                    cal = client.get_calendar(
                        venue_id=item["venue_id"],
                        num_seats=item["num_seats"],
                        start_date=d,
                        end_date=d
                    )
                    scheduled = cal.get("scheduled", [])
                    for entry in scheduled:
                        if str(entry.get("date")) == d:
                            inv = entry.get("inventory", {})
                            if inv.get("reservation") == "available":
                                # We can’t confirm specific times; note ANY for that date
                                found.append({"date": d, "times": ["ANY"]})
                            break
                    continue  # go to next date

                hits = sorted(set(slots).intersection(set(item["times_24"])))
                if hits:
                    found.append({"date": d, "times": hits})
            else:
                # Date-level via /4/venue/calendar
                cal = client.get_calendar(
                    venue_id=item["venue_id"],
                    num_seats=item["num_seats"],
                    start_date=d,
                    end_date=d
                )
                for entry in cal.get("scheduled", []):
                    if str(entry.get("date")) == d:
                        inv = entry.get("inventory", {})
                        if inv.get("reservation") == "available":
                            found.append({"date": d, "times": ["ANY"]})
                        break
        except ResyClientError as e:
            return {
                **item,
                "status": f"Error: {e.message}",
                "last_checked": datetime.now(timezone.utc).isoformat(timespec="seconds")
            }

    if found:
        return {
            **item,
            "status": f"✅ Available: {found}",
            "last_checked": datetime.now(timezone.utc).isoformat(timespec="seconds")
        }
    return {
        **item,
        "status": "❌ No matches",
        "last_checked": datetime.now(timezone.utc).isoformat(timespec="seconds")
    }


if not st.session_state.monitored:
    st.info("Nothing is being monitored yet.")
else:
    # controls row
    colA, colB = st.columns([1, 2])
    with colA:
        if st.button("🔄 Check now"):
            updated = [check_item(it) for it in st.session_state.monitored]
            st.session_state.monitored = updated
            st.rerun()
    with colB:
        st.session_state.auto_refresh = st.checkbox("Auto-check every 100s", value=st.session_state.auto_refresh)

    # list
    to_remove = []
    for i, item in enumerate(st.session_state.monitored):
        c1, c2 = st.columns([6, 1])
        with c1:
            human_times = ", ".join(item["times_24"]) if item["times_24"] else "ANY"
            st.write(
                f"🍽️ **{pretty_name(item['slug'])}** — party {item['num_seats']} — "
                f"{len(item['dates'])} day(s) — times: {human_times}"
            )
            st.caption(
                f"[{item['url']}]({item['url']})  |  "
                f"Status: {item['status']}  |  Last checked: {item['last_checked'] or '—'}"
            )
        with c2:
            if st.button("Remove", key=f"rm_{i}"):
                to_remove.append(i)
        st.divider()

    if to_remove:
        st.session_state.monitored = [x for idx, x in enumerate(st.session_state.monitored) if idx not in to_remove]
        st.rerun()
