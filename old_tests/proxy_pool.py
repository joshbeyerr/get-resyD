import os
import random

class ProxyPool:
    def __init__(self, proxies):
        self._proxies = proxies or []

    @classmethod
    def from_file(cls, path: str):
        if not os.path.exists(path):
            return cls([])
        proxies = []
        with open(path, "r") as f:
            for raw in f:
                cleaned = raw.strip()
                if not cleaned or ":" not in cleaned:
                    continue
                try:
                    ip, port, user, pwd = cleaned.split(":")
                    proxies.append(f"http://{user}:{pwd}@{ip}:{port}")
                except ValueError:
                    # allow simple ip:port lines too
                    parts = cleaned.split(":")
                    if len(parts) == 2:
                        ip, port = parts
                        proxies.append(f"http://{ip}:{port}")
        return cls(proxies)

    @property
    def has_proxies(self) -> bool:
        return len(self._proxies) > 0

    def pick(self) -> str:
        return random.choice(self._proxies)
