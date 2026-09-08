from __future__ import annotations

import httpx

README_URL = "https://raw.githubusercontent.com/public-apis/public-apis/master/README.md"


def fetch_readme(url: str = README_URL, timeout: float = 30.0) -> str:
    response = httpx.get(url, timeout=timeout, follow_redirects=True)
    response.raise_for_status()
    return response.text
