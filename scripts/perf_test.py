#!/usr/bin/env python3
"""
Performance test for Signal Scout API endpoints.
Hits random endpoints 100x, collects min/max/avg/median response times.
"""

import requests
import time
import random
import statistics
import sys
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

BASE_URL = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8080"

# Random Polish coordinates (within bounds 49.0-55.5 lat, 14.0-24.2 lng)
LOCATIONS = [
    (52.2297, 21.0122),   # Warszawa
    (51.7592, 19.4560),   # Łódź
    (50.0647, 19.9450),   # Kraków
    (51.1079, 17.0385),   # Wrocław
    (54.3520, 18.6466),   # Gdańsk
    (53.1325, 23.1688),   # Białystok
    (50.2649, 19.0238),   # Katowice
    (51.4028, 21.1472),   # Radom
    (53.4285, 14.5528),   # Szczecin
    (49.2992, 19.9496),   # Zakopane
    (50.8118, 19.1203),   # Częstochowa
    (52.4064, 16.9252),   # Poznań
    (51.2465, 22.5684),   # Lublin
    (50.0412, 21.9991),   # Rzeszów
    (54.1759, 15.5614),   # Kołobrzeg
]

PROVIDERS = [
    "Orange Polska S.A.",
    "P4 sp. z o.o.",
    "Polkomtel sp. z o.o.",
    "T-Mobile Polska S.A.",
]

BANDS = [
    "5G3600", "5G2100", "LTE2600", "LTE2100", "LTE1800",
    "LTE900", "LTE800", "UMTS2100", "UMTS900", "GSM900", "GSM1800",
]

NUM_REQUESTS = 100
session = requests.Session()
# PR #5: GET data endpoints require either an API key OR same-origin Referer.
# Set Referer to the scrape target so we behave like a browser.
session.headers.update({"Referer": BASE_URL + "/"})

# Fetch CSRF token from the home page meta tag once. POST /submit_location
# requires it (added in PR #1) — otherwise every POST measurement is 403.
import re as _re
_csrf_token = None


def _ensure_csrf_token():
    global _csrf_token
    if _csrf_token:
        return _csrf_token
    r = session.get(f"{BASE_URL}/", verify=False, timeout=10)
    m = _re.search(r'<meta name="csrf-token" content="([^"]+)"', r.text)
    _csrf_token = m.group(1) if m else ""
    return _csrf_token


def random_submit_location():
    lat, lng = random.choice(LOCATIONS)
    # Add small jitter
    lat += random.uniform(-0.05, 0.05)
    lng += random.uniform(-0.05, 0.05)
    limit = random.choice([3, 6, 9])
    payload = {"lat": lat, "lng": lng, "limit": limit}
    headers = {"X-CSRF-Token": _ensure_csrf_token()}
    start = time.perf_counter()
    r = session.post(f"{BASE_URL}/submit_location", json=payload,
                     headers=headers, verify=False)
    elapsed = time.perf_counter() - start
    return elapsed, r.status_code


def random_get_stations():
    lat, lng = random.choice(LOCATIONS)
    lat += random.uniform(-0.05, 0.05)
    lng += random.uniform(-0.05, 0.05)
    params = {"lat": lat, "lng": lng, "limit": random.choice([3, 6, 9])}
    # Randomly add filters
    if random.random() > 0.5:
        params["service_provider"] = random.choice(PROVIDERS)
    if random.random() > 0.5:
        params["frequency_bands"] = random.choice(BANDS)
    start = time.perf_counter()
    r = session.get(f"{BASE_URL}/stations", params=params, verify=False)
    elapsed = time.perf_counter() - start
    return elapsed, r.status_code


def random_search_stations():
    prefixes = ["OR", "P4", "TM", "PO", "5G", "LT", "BS", "A1", "B2"]
    q = random.choice(prefixes) + str(random.randint(100, 999))
    start = time.perf_counter()
    r = session.get(f"{BASE_URL}/search_stations", params={"q": q}, verify=False)
    elapsed = time.perf_counter() - start
    return elapsed, r.status_code


def random_static_page():
    page = random.choice(["/", "/data", "/stats", "/tips"])
    start = time.perf_counter()
    r = session.get(f"{BASE_URL}{page}", verify=False)
    elapsed = time.perf_counter() - start
    return elapsed, r.status_code


ENDPOINTS = {
    "POST /submit_location": random_submit_location,
    "GET /stations":         random_get_stations,
    "GET /search_stations":  random_search_stations,
    "GET /static_pages":     random_static_page,
}


def run_tests():
    results = {name: [] for name in ENDPOINTS}
    errors = {name: 0 for name in ENDPOINTS}

    print(f"Running {NUM_REQUESTS} requests against {BASE_URL}...")
    print()

    for i in range(NUM_REQUESTS):
        endpoint_name = random.choice(list(ENDPOINTS.keys()))
        fn = ENDPOINTS[endpoint_name]
        elapsed, status = fn()
        if 200 <= status < 300:
            results[endpoint_name].append(elapsed * 1000)  # ms
        else:
            errors[endpoint_name] += 1

        if (i + 1) % 25 == 0:
            print(f"  [{i+1}/{NUM_REQUESTS}] done...")

    print()
    print("=" * 90)
    print(f"  PERFORMANCE RESULTS — {BASE_URL}")
    print(f"  {NUM_REQUESTS} total requests, random endpoint distribution")
    print("=" * 90)
    print()
    print(f"  {'Endpoint':<25} {'Reqs':>5} {'Err':>4} {'Min (ms)':>10} {'Avg (ms)':>10} {'Med (ms)':>10} {'Max (ms)':>10} {'P95 (ms)':>10}")
    print(f"  {'-'*25} {'-'*5} {'-'*4} {'-'*10} {'-'*10} {'-'*10} {'-'*10} {'-'*10}")

    all_times = []
    total_errors = 0

    for name in ENDPOINTS:
        times = results[name]
        err = errors[name]
        total_errors += err
        all_times.extend(times)

        if times:
            mn = min(times)
            avg = statistics.mean(times)
            med = statistics.median(times)
            mx = max(times)
            p95 = sorted(times)[int(len(times) * 0.95)] if len(times) > 1 else mx
            print(f"  {name:<25} {len(times):>5} {err:>4} {mn:>10.2f} {avg:>10.2f} {med:>10.2f} {mx:>10.2f} {p95:>10.2f}")
        else:
            print(f"  {name:<25} {0:>5} {err:>4} {'—':>10} {'—':>10} {'—':>10} {'—':>10} {'—':>10}")

    print(f"  {'-'*25} {'-'*5} {'-'*4} {'-'*10} {'-'*10} {'-'*10} {'-'*10} {'-'*10}")

    if all_times:
        mn = min(all_times)
        avg = statistics.mean(all_times)
        med = statistics.median(all_times)
        mx = max(all_times)
        p95 = sorted(all_times)[int(len(all_times) * 0.95)]
        print(f"  {'TOTAL':<25} {len(all_times):>5} {total_errors:>4} {mn:>10.2f} {avg:>10.2f} {med:>10.2f} {mx:>10.2f} {p95:>10.2f}")

    print()
    print("=" * 90)


if __name__ == "__main__":
    run_tests()
