#!/usr/bin/env python3
"""
Sieve Prime Finder — Segmented Sieve of Eratosthenes.

Runs inside a GitHub Actions workflow. Each invocation runs for
SESSION_SECONDS (default 300 s = 5 min), picks up where the last run
left off (state stored in state.json), and regenerates index.html with
a live report.

Schedule: 12 runs/day × 5 min = 60 min/day, triggered by GitHub Actions
cron every 2 hours (00:00, 02:00, … 22:00 UTC).

Usage:
    python sieve_prime_finder.py            # run a full 5-minute session
    python sieve_prime_finder.py --test 5  # run for 5 seconds (smoke test)
"""

import json
import os
import time
import math
import datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
SESSION_SECONDS = int(os.environ.get("SESSION_SECONDS", "300"))
SEGMENT_SIZE    = int(os.environ.get("SEGMENT_SIZE", "50000"))   # numbers per segment
KEEP_PRIMES     = 1000
STATE_FILE      = Path("state.json")
REPORT_FILE     = Path("index.html")

SLOTS_UTC = list(range(0, 24, 2))  # 00,02,04,…,22

# ---------------------------------------------------------------------------
# State persistence
# ---------------------------------------------------------------------------
def load_state():
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return {
        "low": 2,               # start of next segment
        "count": 0,              # total primes found
        "last_prime": None,
        "last_tested": None,
        "primes": [],            # last KEEP_PRIMES primes
        "last_run_iso": None,
        "total_sessions": 0,
        "total_runtime_s": 0.0,
        "max_n": 0,             # highest number checked
    }

def save_state(state):
    STATE_FILE.write_text(json.dumps(state, indent=2))

# ---------------------------------------------------------------------------
# Simple sieve — all primes up to limit (for base primes)
# ---------------------------------------------------------------------------
def simple_sieve(limit):
    """Return list of all primes up to `limit` using basic Sieve of Eratosthenes."""
    if limit < 2:
        return []
    sieve = bytearray([1]) * (limit + 1)  # 1 = prime candidate, 0 = composite
    sieve[0] = 0
    sieve[1] = 0
    for i in range(2, int(limit ** 0.5) + 1):
        if sieve[i]:
            for j in range(i * i, limit + 1, i):
                sieve[j] = 0
    return [i for i in range(2, limit + 1) if sieve[i]]

# ---------------------------------------------------------------------------
# Segmented sieve — find primes in [low, high)
# ---------------------------------------------------------------------------
def segmented_sieve(low, high, base_primes):
    """
    Find all primes in [low, high) using the Segmented Sieve of Eratosthenes.
    `base_primes` = all primes up to sqrt(high).
    Returns (list_of_primes, segment_bytearray).
    """
    if low < 2:
        low = 2
    size = high - low
    segment = bytearray([1]) * size  # 1 = prime candidate, 0 = composite

    for p in base_primes:
        if p * p > high:
            break
        # First multiple of p in [low, high)
        start = max(p * p, ((low + p - 1) // p) * p)
        for j in range(start, high, p):
            segment[j - low] = 0

    primes = [low + i for i in range(size) if segment[i]]
    return primes, segment

# ---------------------------------------------------------------------------
# Search loop
# ---------------------------------------------------------------------------
def run_search(state, duration_s):
    """Process segments for `duration_s` seconds, updating state in place."""
    deadline = time.monotonic() + duration_s
    flush_counter = 0

    while time.monotonic() < deadline:
        low  = state["low"]
        high = low + SEGMENT_SIZE

        # Ensure base primes cover sqrt(high)
        sqrt_high = int(math.isqrt(high)) + 1
        # Recompute base primes if needed (cheap, done rarely)
        base_primes = simple_sieve(sqrt_high)

        primes_in_segment, _ = segmented_sieve(low, high, base_primes)

        state["count"] += len(primes_in_segment)
        state["last_tested"] = high - 1
        state["max_n"] = max(state.get("max_n", 0), high - 1)

        if primes_in_segment:
            state["last_prime"] = primes_in_segment[-1]
            state["primes"].extend(primes_in_segment)
            if len(state["primes"]) > KEEP_PRIMES:
                state["primes"] = state["primes"][-KEEP_PRIMES:]

        state["low"] = high
        flush_counter += 1

        # Periodic flush
        if flush_counter >= 5:
            save_state(state)
            flush_counter = 0

    save_state(state)

# ---------------------------------------------------------------------------
# Report generation (index.html)
# ---------------------------------------------------------------------------
def next_slot_utc(now_iso):
    now = datetime.datetime.fromisoformat(now_iso.replace("Z", "+00:00"))
    for h in SLOTS_UTC:
        slot = now.replace(hour=h, minute=0, second=0, microsecond=0)
        if slot > now:
            return slot.strftime("%Y-%m-%d %H:%M UTC")
    tomorrow = now + datetime.timedelta(days=1)
    return tomorrow.replace(hour=0, minute=0, second=0, microsecond=0).strftime("%Y-%m-%d %H:%M UTC")

def generate_report(state):
    last_prime  = state["last_prime"]
    last_tested = state["last_tested"]
    count       = state["count"]
    primes      = state["primes"][-KEEP_PRIMES:]
    last_run    = state["last_run_iso"]
    next_run    = next_slot_utc(last_run) if last_run else "—"
    sessions    = state.get("total_sessions", 0)
    runtime     = state.get("total_runtime_s", 0.0)
    max_n       = state.get("max_n", 0)

    last_prime_s  = f"{last_prime:,}"   if last_prime  is not None else "—"
    last_tested_s = f"{last_tested:,}"  if last_tested is not None else "—"
    last_run_s    = last_run[:19] + " UTC" if last_run else "—"

    primes_html = "\n".join(
        f'<span class="{"latest" if i == len(primes) - 1 else ""}">{p:,} </span>'
        for i, p in enumerate(primes)
    )

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Sieve Prime Finder — Live Report</title>
<style>
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  :root {{
    --bg:#f4f1ea; --card:#ffffff; --ink:#1a1a2e; --muted:#6c7293;
    --accent:#e84393; --accent2:#6c5ce7; --green:#00b894;
    --amber:#fdcb6e; --border:rgba(108,114,147,0.15);
  }}
  body {{
    font-family:'Inter',-apple-system,'Segoe UI',sans-serif;
    background:var(--bg); color:var(--ink); min-height:100vh;
    display:flex; flex-direction:column; align-items:center; padding:40px 20px;
  }}
  .wrapper {{ width:100%; max-width:820px; }}
  .header {{ text-align:center; margin-bottom:32px; }}
  .header .badge {{
    display:inline-block; background:linear-gradient(135deg,var(--accent),var(--accent2));
    color:#fff; font-size:0.7rem; font-weight:700; letter-spacing:2px;
    text-transform:uppercase; padding:6px 18px; border-radius:20px; margin-bottom:14px;
  }}
  .header h1 {{ font-size:2.2rem; font-weight:800; letter-spacing:-0.5px; }}
  .header p {{ color:var(--muted); font-size:0.9rem; margin-top:6px; }}
  .status-pill {{ display:flex; align-items:center; gap:8px; justify-content:center; margin-bottom:24px; }}
  .status-pill .dot {{ width:10px; height:10px; border-radius:50%; background:var(--green); animation:blink 1s infinite; }}
  @keyframes blink {{ 0%,100%{{opacity:1}} 50%{{opacity:0.3}} }}
  .status-pill span {{ font-size:0.85rem; color:var(--muted); font-weight:500; }}
  .stat-grid {{
    display:grid; grid-template-columns:repeat(auto-fit,minmax(170px,1fr));
    gap:16px; margin-bottom:28px;
  }}
  .stat-card {{
    background:var(--card); border-radius:16px; padding:20px;
    box-shadow:0 2px 12px rgba(0,0,0,0.04); border:1px solid var(--border);
    position:relative; overflow:hidden;
  }}
  .stat-card::before {{
    content:''; position:absolute; top:0; left:0; width:4px; height:100%; background:var(--accent2);
  }}
  .stat-card.green::before {{ background:var(--green); }}
  .stat-card.amber::before {{ background:var(--amber); }}
  .stat-card.pink::before {{ background:var(--accent); }}
  .stat-card .label {{ font-size:0.68rem; color:var(--muted); text-transform:uppercase; letter-spacing:1.2px; margin-bottom:8px; font-weight:600; }}
  .stat-card .value {{ font-size:1.5rem; font-weight:700; color:var(--ink); font-family:'Courier New',monospace; word-break:break-all; }}
  .prime-list-section h3 {{ font-size:0.78rem; color:var(--muted); text-transform:uppercase; letter-spacing:1.2px; margin-bottom:10px; font-weight:600; }}
  #primeList {{
    background:var(--card); border-radius:16px; padding:20px;
    box-shadow:0 2px 12px rgba(0,0,0,0.04); border:1px solid var(--border);
    max-height:260px; overflow-y:auto; font-family:'Courier New',monospace;
    font-size:0.82rem; line-height:1.8; columns:5; column-gap:16px;
  }}
  #primeList span {{ color:var(--accent2); display:inline-block; break-inside:avoid; }}
  #primeList span.latest {{ color:var(--accent); font-weight:700; font-size:0.9rem; }}
  .footer {{ margin-top:28px; text-align:center; color:var(--muted); font-size:0.75rem; }}
  .footer code {{ background:var(--border); padding:2px 8px; border-radius:4px; font-size:0.72rem; }}
  #primeList::-webkit-scrollbar {{ width:6px; }}
  #primeList::-webkit-scrollbar-thumb {{ background:var(--border); border-radius:6px; }}
</style>
</head>
<body>
  <div class="wrapper">
    <div class="header">
      <span class="badge">Sieve of Eratosthenes</span>
      <h1>🪶 Sieve Prime Finder</h1>
      <p>Runs 12 sessions × 5 minutes every 2 hours via GitHub Actions — 60 min/day total.</p>
    </div>

    <div class="status-pill">
      <span class="dot"></span>
      <span>Server-side segmented sieve • last updated {last_run_s}</span>
    </div>

    <div class="stat-grid">
      <div class="stat-card green">
        <div class="label">Last Prime Found</div>
        <div class="value">{last_prime_s}</div>
      </div>
      <div class="stat-card amber">
        <div class="label">Last Tested Number</div>
        <div class="value">{last_tested_s}</div>
      </div>
      <div class="stat-card pink">
        <div class="label">Total Primes Found</div>
        <div class="value">{count:,}</div>
      </div>
      <div class="stat-card">
        <div class="label">Highest Number Checked</div>
        <div class="value">{max_n:,}</div>
      </div>
      <div class="stat-card amber">
        <div class="label">Last Run (UTC)</div>
        <div class="value">{last_run_s}</div>
      </div>
      <div class="stat-card green">
        <div class="label">Next Run (UTC)</div>
        <div class="value">{next_run}</div>
      </div>
    </div>

    <div class="prime-list-section">
      <h3>Last {len(primes)} Primes (most recent highlighted)</h3>
      <div id="primeList">
{primes_html}
      </div>
    </div>

    <div class="footer">
      Uses the <strong>Segmented Sieve of Eratosthenes</strong> — processes numbers in segments, marking multiples of each prime.
      Runs server-side via GitHub Actions. State persists across runs via <code>state.json</code> committed to the repo.
      Sessions: {sessions} | Total runtime: {runtime:.0f}s
    </div>
  </div>
</body>
</html>
"""
    REPORT_FILE.write_text(html)

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    import argparse
    parser = argparse.ArgumentParser(description="Sieve prime finder (GitHub Actions).")
    parser.add_argument("--test", type=int, metavar="SECS",
                        help="run for only SECS seconds (smoke test)")
    args = parser.parse_args()
    duration = args.test if args.test else SESSION_SECONDS

    state = load_state()

    print(f"=== Sieve Prime Finder Session ===")
    print(f"  Resuming from n = {state['low']:,}")
    print(f"  Primes found so far: {state['count']:,}")
    print(f"  Segment size: {SEGMENT_SIZE:,}")
    print(f"  Running for {duration}s …")

    t0 = time.monotonic()
    run_search(state, duration)
    elapsed = time.monotonic() - t0

    state["last_run_iso"]    = datetime.datetime.now(datetime.timezone.utc).isoformat()
    state["total_sessions"]  = state.get("total_sessions", 0) + 1
    state["total_runtime_s"] = state.get("total_runtime_s", 0.0) + elapsed

    save_state(state)
    generate_report(state)

    print(f"  Done in {elapsed:.1f}s")
    print(f"  Last tested:  {state['last_tested']:,}")
    print(f"  Last prime:   {state['last_prime']:,}")
    print(f"  Total primes: {state['count']:,}")
    print(f"  Max number:   {state['max_n']:,}")
    print(f"  Sessions:     {state['total_sessions']}")
    print(f"  State saved → {STATE_FILE}")
    print(f"  Report saved → {REPORT_FILE}")

if __name__ == "__main__":
    main()
