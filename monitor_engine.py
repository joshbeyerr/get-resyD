# monitor_engine.py
import threading
import time
import datetime as dt
from typing import Dict, Any, List, Optional, Callable

POLL_INTERVAL_SEC = 120  # 2 minutes

class MonitorEngine:
    def __init__(self, checker: Callable[[Dict[str, Any]], None]):
        """
        checker(item): mutates item with keys: last_checked, status, status_msg, found_slots, error
        """
        self._checker = checker
        self._monitors: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def _loop(self):
        while not self._stop.is_set():
            now = time.time()
            with self._lock:
                items = list(self._monitors.values())
            for item in items:
                if not item.get("active", True):
                    continue
                last_ts = item["last_checked"].timestamp() if item.get("last_checked") else 0
                if now - last_ts >= POLL_INTERVAL_SEC:
                    try:

                        ts = time.strftime("%Y-%m-%d %H:%M:%S")
                        print(f"[{ts}] ENGINE: due → checking venue_id={item.get('venue_id')} name={item.get('venue_name')} party={item.get('party_size')} dates={item.get('start_date')}→{item.get('end_date')}")

                        self._checker(item)
                    except Exception as e:
                        item["status"] = "error"
                        item["status_msg"] = "Background error"
                        item["error"] = str(e)
                        item["last_checked"] = dt.datetime.now()
            # small sleep so the loop is responsive to stop()
            self._stop.wait(1.0)

    def add(self, item: Dict[str, Any]) -> None:
        with self._lock:
            self._monitors[item["id"]] = item

    def remove(self, item_id: str) -> None:
        with self._lock:
            self._monitors.pop(item_id, None)

    def list(self) -> List[Dict[str, Any]]:
        with self._lock:
            # return shallow copies for safety
            return [dict(v) for v in self._monitors.values()]

    def set_active(self, item_id: str, active: bool) -> None:
        with self._lock:
            if item_id in self._monitors:
                self._monitors[item_id]["active"] = active

    def stop(self):
        self._stop.set()
        self._thread.join(timeout=3)
