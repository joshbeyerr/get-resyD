import random
import time
from typing import Optional, Dict, Any
import requests


class ResyClientError(Exception):
    def __init__(self, message: str, status_code: Optional[int] = None, details: Optional[dict] = None):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.details = details or {}


class ResyClient:
    def __init__(
        self,
        api_key: str,
        user_agent: str,
        request_timeout: float = 12.0,
        max_retries: int = 3,
        backoff_base: float = 0.7,
    ):
        self.api_key = api_key
        self.user_agent = user_agent
        self.timeout = request_timeout
        self.max_retries = max_retries
        self.backoff_base = backoff_base

        self.session = requests.Session()
        self.session.headers.update({
            "user-agent": self.user_agent,
            "authorization": f'ResyAPI api_key="{self.api_key}"',
        })

    def _request(self, method: str, url: str, **kwargs) -> requests.Response:
        """HTTP request with retry/backoff (no proxies)."""
        kwargs.setdefault("timeout", self.timeout)

        last_exc = None
        for attempt in range(1, self.max_retries + 1):
            try:
                resp = self.session.request(method, url, **kwargs)
                # Retry certain upstream statuses; otherwise raise with details.
                if resp.status_code >= 400:
                    if resp.status_code in (429, 500, 502, 503, 504) and attempt < self.max_retries:
                        sleep_s = self.backoff_base * (2 ** (attempt - 1)) + random.random() * 0.3
                        time.sleep(sleep_s)
                        continue
                    raise ResyClientError(
                        f"Upstream error {resp.status_code}",
                        status_code=resp.status_code,
                        details={"text": resp.text}
                    )
                return resp
            except (requests.Timeout, requests.ConnectionError) as e:
                last_exc = e
                if attempt < self.max_retries:
                    sleep_s = self.backoff_base * (2 ** (attempt - 1)) + random.random() * 0.3
                    time.sleep(sleep_s)
                    continue
                raise ResyClientError("Network error", details={"error": str(e)})
        raise ResyClientError("Network error", details={"error": str(last_exc)})

    # --- Public methods ---

    def lookup_venue(self, city_slug: str, venue_slug: str) -> Dict[str, Any]:
        """
        GET /3/venue?url_slug=<venue_slug>&location=<city_slug>
        Returns JSON that includes `id`.
        """
        url = "https://api.resy.com/3/venue"
        params = {"url_slug": venue_slug, "location": city_slug}
        resp = self._request("GET", url, params=params)
        data = resp.json()
        if "id" not in data:
            raise ResyClientError("Venue lookup did not return an id", details={"response": data})
        return data

    def get_calendar(self, venue_id: str, num_seats: int, start_date: str, end_date: str) -> Dict[str, Any]:
        """
        GET /4/venue/calendar?venue_id=...&num_seats=...&start_date=...&end_date=...
        Pass-through JSON.
        """
        url = "https://api.resy.com/4/venue/calendar"
        params = {
            "venue_id": venue_id,
            "num_seats": num_seats,
            "start_date": start_date,
            "end_date": end_date
        }
        resp = self._request("GET", url, params=params)
        return resp.json()
    
    def find(self, venue_id: str, num_seats: int, day: str, time_filter: Optional[str] = None) -> Dict[str, Any]:
        """
        POST /4/find
        Body JSON:
        {
            "day": "2025-09-02",
            "lat": 0,
            "long": 0,
            "party_size": 2,
            "venue_id": "12345",
            "time_filter": "evening"    # optional
        }
        Returns the Resy /4/find JSON response.
        """
        url = "https://api.resy.com/4/find"
        payload = {
            "day": day,
            "lat": 0,
            "long": 0,
            "party_size": num_seats,
            "venue_id": venue_id,
        }
        if time_filter:
            payload["time_filter"] = time_filter

        resp = self._request("POST", url, json=payload)
        return resp.json()

    

    
