#!/usr/bin/env python3
"""Cost per 1,000 requests + SLO error budget (Task 7).

Reads a Locust stats CSV (results/loadtest_stats.csv, from the standard
run in tools/locustfile.py) and the rate card (data/rate_card.json),
and prints every step of the cost calculation. Billed on the CPU and
memory *limits* of each running replica, for every hour it runs,
whether busy or not -- see the rate card's billing_rule.

  locust -f tools/locustfile.py --headless --users 4 --spawn-rate 4 \
    --run-time 2m --host http://localhost:8080 --csv results/loadtest
  .venv/bin/python scripts/cost.py --stats results/loadtest_stats.csv \
    --replicas 2 --cpu-limit 1 --mem-limit 1

SLO used here (measured from the same Locust run):
  99% of /parse requests return HTTP 200, over the 2-minute run window.
  Error budget = 1% of the requests in the window, in requests.
  Budget used = the failure count from the Locust stats.
"""
import argparse
import csv
import json
from pathlib import Path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stats", default="results/loadtest_stats.csv")
    ap.add_argument("--rate-card", default="data/rate_card.json")
    ap.add_argument("--replicas", type=int, default=2)
    ap.add_argument("--cpu-limit", type=float, default=1.0, help="vCPU limit per replica")
    ap.add_argument("--mem-limit", type=float, default=1.0, help="GiB memory limit per replica")
    ap.add_argument("--slo-availability", type=float, default=99.0)
    ap.add_argument("--out", default="results/cost.json")
    a = ap.parse_args()

    rate = json.loads(Path(a.rate_card).read_text(encoding="utf-8"))
    with open(a.stats, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    agg = next(r for r in rows if r["Name"] == "Aggregated")
    requests = int(agg["Request Count"])
    failures = int(agg["Failure Count"])
    rps = float(agg["Requests/s"])
    p50 = float(agg["Median Response Time"])
    p95 = float(agg["95%"])

    hourly_per_replica = a.cpu_limit * rate["vcpu_hour"] + a.mem_limit * rate["gib_memory_hour"]
    hourly_total = a.replicas * hourly_per_replica
    rph = rps * 3600
    cost_per_1000 = hourly_total / rph * 1000 if rph else float("inf")
    budget = requests * (100 - a.slo_availability) / 100

    print(f"Locust run: {requests} requests, {failures} failures, {rps:.2f} req/s")
    print(f"  p50 latency {p50:.0f} ms, p95 latency {p95:.0f} ms")
    print(f"Step 1: hourly cost per replica = {a.cpu_limit} vCPU x INR {rate['vcpu_hour']:.2f}"
          f" + {a.mem_limit} GiB x INR {rate['gib_memory_hour']:.2f} = INR {hourly_per_replica:.2f}")
    print(f"Step 2: {a.replicas} replicas x INR {hourly_per_replica:.2f} = INR {hourly_total:.2f} / hour")
    print(f"Step 3: requests per hour = {rps:.2f} req/s x 3600 = {rph:.0f}")
    print(f"Step 4: cost per 1,000 requests = INR {hourly_total:.2f} / {rph:.0f} x 1000"
          f" = INR {cost_per_1000:.4f}")
    print(f"SLO: {a.slo_availability:.0f}% availability over the 2-minute window")
    print(f"  error budget = 1% of {requests} requests = {budget:.1f} requests")
    print(f"  budget used = {failures} failures ({failures / budget * 100:.1f}% of budget)" if budget else "")

    out = {
        "requests": requests, "failures": failures, "requests_per_second": rps,
        "p50_ms": p50, "p95_ms": p95,
        "hourly_cost_per_replica_inr": round(hourly_per_replica, 4),
        "replicas": a.replicas, "hourly_cost_total_inr": round(hourly_total, 4),
        "requests_per_hour": round(rph, 1),
        "cost_per_1000_requests_inr": round(cost_per_1000, 4),
        "slo_availability_pct": a.slo_availability,
        "error_budget_requests": round(budget, 1),
        "error_budget_used_requests": failures,
    }
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"wrote {a.out}")


if __name__ == "__main__":
    main()
