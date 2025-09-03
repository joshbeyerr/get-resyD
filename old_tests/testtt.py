import re
from urllib.parse import urlparse
from resy_client import ResyClient, ResyClientError
import os
from discord_webhook import DiscordWebhook, DiscordEmbed

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


def sendWebhook(restaurauntName, date, time, partySize, link, type):
    webhook = DiscordWebhook(url='https://discord.com/api/webhooks/1412488835451064330/ouPA7jGc2IkReshRethgL1LHk2sqtNVg_3hxYd5slJ6eVqcBysX-RyOI5az0qk2v2E5K', rate_limit_retry=True)
    embed = DiscordEmbed(title=restaurauntName, color='0x2ecc71')
    embed.set_timestamp()
    embed.add_embed_field(name='Date:', value=(date))
    embed.add_embed_field(name='Time: ', value=time)
    embed.add_embed_field(name='Party Size: ', value=str(partySize))
    embed.add_embed_field(name='Type: ', value=(type))
    embed.add_embed_field(name='Link: ', value=(link))

    #embed.set_thumbnail(url=image)
    webhook.add_embed(embed)
    webhook.execute()


def main():

    # user input
    url = "https://resy.com/cities/toronto-on/venues/goa-indian-farm-kitchen"
    party_size = 2 
    start_date = "2025-09-03"
    end_date = "2025-09-03"
    times = ["19:00"]



    # getting venue id
    city, slug = parse_resy_url(url.strip())
    venue_info = client.lookup_venue(city, slug)

    venue_id = str(venue_info.get("id")['resy'])


    # getting calendar
    calendar = client.get_calendar(venue_id, party_size, start_date, end_date)

    print(calendar)

    # dates with availability within specified date range
    # will use this to check availability for specific times on those dates
    availableDates = [x['date'] for x in calendar['scheduled'] if x['inventory']['reservation'] == "available"]

    print("Available dates:", availableDates)

    availableSlots = []
    # checking availability for specific times on available dates
    for date in availableDates:
        availability = client.find(venue_id, party_size, date, None)

        for slot in availability['results']['venues'][0]['slots']:
            time = slot['date']['start'].split(" ")[1].rsplit(":", 1)[0]
            if time in times:
                availableSlots.append(
                    {
                        "date": date,
                        "time": time,
                        "type": slot['config']['type']
                    }
                )

    print("Available slots:", availableSlots)

    for slot in availableSlots:
        sendWebhook(venue_info.get("name"), slot['date'], slot['time'], party_size, url, slot['type'])

                


main()