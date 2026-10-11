#!/usr/bin/env python3
"""Replay an existing GTFS dataset on Linux with two isolated local workers.

Run from the repository root, with its dependencies installed. Uses no external
network services. Provide a disposable local copy of a dataset: load_feed may
create its normal cache. Production data directories must not be passed here.
Example:
  python scripts/benchmark_schedule_memory.py --dataset /fixtures/feed \
      --provider PROVIDER_ID --stop STOP_ID --output /tmp/baseline.json
"""

import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import statistics
import subprocess
import sys
import tempfile
import time

import httpx


SERVER = '''
import os
from datetime import datetime
from pathlib import Path
from app.schedule_explorer.backend import main

main.DOWNLOAD_DIR = Path(os.environ["BENCHMARK_METADATA"])
class Clock(datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2025, 1, 15, 12, 0, 0, tzinfo=tz)
main.datetime = Clock
loads = 0
original_load = main.load_feed
def load(path):
    global loads
    loads += 1
    return original_load(path)
main.load_feed = load
app = main.app
@app.middleware("http")
async def identify(request, call_next):
    response = await call_next(request)
    response.headers["X-Benchmark-Pid"] = str(os.getpid())
    response.headers["X-Benchmark-Loads"] = str(loads)
    return response
'''


def memory(pid):
    try:
        lines = Path(f"/proc/{pid}/smaps_rollup").read_text().splitlines()[1:]
        values = {k: int(v.split()[0]) for k, v in (line.split(":", 1) for line in lines)}
        return {k: values[k] for k in ("Pss", "SwapPss", "Rss")}
    except FileNotFoundError:
        raise RuntimeError(f"Worker {pid} exited during the replay")


def normalize(value):
    if isinstance(value, dict):
        return {k: normalize(v) for k, v in value.items() if k != "performance"}
    if isinstance(value, list):
        return [normalize(v) for v in value]
    return value


async def replay(args, address):
    workers = {}
    expected_errors = dict(item.rsplit(":", 1) for item in args.expected_error)
    async with httpx.AsyncClient(base_url=address, timeout=120, limits=httpx.Limits(max_connections=16, max_keepalive_connections=0)) as client:
        async def get(path, params=None):
            started = time.perf_counter()
            response = await client.get(path, params=params)
            elapsed = time.perf_counter() - started
            if str(response.status_code) != expected_errors.get(path):
                response.raise_for_status()
            if response.is_success:
                workers[int(response.headers["X-Benchmark-Pid"])] = int(response.headers["X-Benchmark-Loads"])
            payload = response.json() if response.is_success else {
                "_http_error": response.status_code, "body": response.text,
            }
            return payload, elapsed

        for _ in range(120):
            try:
                await get("/health")
                break
            except httpx.TransportError:
                await asyncio.sleep(0.25)
        else:
            raise RuntimeError("Workers did not start")
        prefix = f"/api/{args.provider}"
        search = ("/stations/search", {"stop_id": args.stop, "provider_id": args.provider})
        load_started = time.perf_counter()
        for _ in range(8):
            await asyncio.gather(*(get(*search) for _ in range(8)))
            if len(workers) == 2 and all(n >= 1 for n in workers.values()):
                break
        assert len(workers) == 2 and all(n == 1 for n in workers.values()), workers
        load_seconds = time.perf_counter() - load_started
        before = {pid: memory(pid) for pid in workers}
        station_routes, _ = await get(prefix + f"/stations/{args.stop}/routes")
        assert station_routes, "Choose a stop served by at least one route"
        route = next(r for r in station_routes if r.get("terminus_stop_id") != args.stop)
        route_id = route["route_id"]
        destination = route["terminus_stop_id"]
        routes = (prefix + "/routes", {"from_station": args.stop, "to_station": destination, "date": "2025-01-15"})
        waiting = (prefix + "/waiting_times", {"stop_id": args.stop, "download": "true"})
        requests = [
            search,
            ("/stations/search", {"stop_id": args.stop, "provider_id": args.provider, "language": "nl"}),
            (prefix + f"/stations/{args.stop}/routes", {}),
            (prefix + f"/stations/destinations/{args.stop}", {}),
            (prefix + f"/stations/origins/{args.stop}", {}),
            routes,
            (prefix + "/routes", {"from_station": destination, "to_station": args.stop}),
            waiting,
            (prefix + f"/stops/{args.stop}/waiting_times", {"route_id": route_id, "limit": 3, "time_local": "12:00:00"}),
            (prefix + f"/colors/{route_id}", {}),
            (prefix + f"/line_info/{route_id}", {}),
            (prefix + "/routes/find", {"short_name": route["short_name"] or route_id}),
            (prefix + "/stops/bbox", {"min_lat": -90, "max_lat": 90, "min_lon": -180, "max_lon": 180, "count_only": "true"}),
        ]
        correctness = []
        for path, params in requests:
            payload, elapsed = await get(path, params)
            canonical = json.dumps(normalize(payload), sort_keys=True, ensure_ascii=False, separators=(",", ":"))
            correctness.append({"path": path, "params": params, "sha256": hashlib.sha256(canonical.encode()).hexdigest(), "bytes": len(canonical), "seconds": elapsed})
        scenarios = []
        workload = [search, routes, waiting, (prefix + f"/stations/{args.stop}/routes", {})]
        for concurrency in (1, 4, 8):
            semaphore = asyncio.Semaphore(concurrency)
            async def one(index):
                async with semaphore:
                    _, elapsed = await get(*workload[index % len(workload)])
                    return elapsed
            started = time.perf_counter()
            timings = await asyncio.gather(*(one(i) for i in range(args.requests)))
            duration = time.perf_counter() - started
            scenarios.append({"concurrency": concurrency, "requests": len(timings), "seconds": duration,
                "requests_per_second": len(timings) / duration, "p50_seconds": statistics.median(timings),
                "p95_seconds": sorted(timings)[int(0.95 * (len(timings)-1))],
                "worker_memory_kib": {pid: memory(pid) for pid in workers}})
        return {"dataset": args.dataset.name, "provider": args.provider, "workers": workers,
            "expected_errors": expected_errors,
            "load_seconds": load_seconds, "loaded_memory_kib": before, "correctness": correctness,
            "scenarios": scenarios, "final_memory_kib": {pid: memory(pid) for pid in workers}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", required=True, type=Path)
    parser.add_argument("--provider", required=True)
    parser.add_argument("--stop", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--requests", type=int, default=24)
    parser.add_argument("--port", type=int, default=9186)
    parser.add_argument("--expected-error", action="append", default=[], metavar="PATH:STATUS",
                        help="Record a known baseline error explicitly while comparing other endpoints")
    args = parser.parse_args()
    args.dataset = args.dataset.resolve()
    if not Path("/proc/self/smaps_rollup").exists():
        parser.error("Run on Linux (for example in a local container) for PSS and SwapPss measurements")
    with tempfile.TemporaryDirectory(prefix="transit-replay-") as directory:
        root = Path(directory)
        (root / "benchmark_app.py").write_text(SERVER)
        metadata = {"dataset": {"provider_id": args.provider, "provider_name": "Replay",
            "dataset_id": "dataset", "download_path": str(args.dataset), "download_date": "2025-01-09",
            "file_hash": "local-replay", "source_url": "https://example.test/feed.zip"}}
        (root / "datasets_metadata.json").write_text(json.dumps(metadata))
        env = dict(os.environ, BENCHMARK_METADATA=directory, PYTHONHASHSEED="0")
        env["PYTHONPATH"] = os.pathsep.join([str(Path.cwd()), directory, env.get("PYTHONPATH", "")])
        env.setdefault("PROJECT_ROOT", str(root))
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.with_suffix(".server.log").open("w") as log:
            process = subprocess.Popen([sys.executable, "-m", "uvicorn", "benchmark_app:app", "--host", "127.0.0.1",
                "--port", str(args.port), "--workers", "2", "--lifespan", "on", "--no-access-log"], env=env, stdout=log, stderr=log)
            try:
                result = asyncio.run(replay(args, f"http://127.0.0.1:{args.port}"))
                args.output.write_text(json.dumps(result, indent=2) + "\n")
                print(json.dumps(result, indent=2))
            finally:
                process.terminate()
                try:
                    process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()


if __name__ == "__main__":
    main()
