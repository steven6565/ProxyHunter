#!/usr/bin/env python3
"""60-minute controlled stability run against local mock infrastructure.

No public website is contacted. Results are written to output/stability_60min.json.
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

import test_suite as fixtures  # reuses the controlled local fixtures


async def main() -> None:
    runner, target_port = await fixtures.start_target()
    url = f"http://127.0.0.1:{target_port}/check"
    app = fixtures.App()
    storage = app.storage
    storage.conn.execute("DELETE FROM proxies")
    storage.conn.commit()
    gw = fixtures.fresh_gateway(app, fixtures.free_port())
    marker = fixtures.MarkerHTTPProxy("1.1.1.1", "US")
    await marker.start()
    fixtures.add_proxy(storage, "127.0.0.1", marker.port, "http", "US", "1.1.1.1")
    await gw.start()

    started = time.monotonic()
    success = failure = 0
    samples = []

    async def client() -> None:
        nonlocal success, failure
        while time.monotonic() - started < 3600:
            status, _ = await fixtures.request_via_gateway(gw.port, url)
            if status == 200:
                success += 1
            else:
                failure += 1
            await asyncio.sleep(0.25)

    async def reporter() -> None:
        while time.monotonic() - started < 3600:
            await asyncio.sleep(60)
            elapsed = int(time.monotonic() - started)
            rate = success / max(1, success + failure)
            samples.append({"elapsed_s": elapsed, "success": success, "failure": failure, "success_rate": round(rate, 4)})
            data = {
                "status": "running", "elapsed_s": elapsed, "success": success,
                "failure": failure, "success_rate": round(rate, 4), "samples": samples,
            }
            out = fixtures.SRC / "output" / "stability_60min.json"
            out.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
            print(f"[stability] {elapsed}s success={success} failure={failure} rate={rate:.3%}", flush=True)

    await asyncio.gather(*(client() for _ in range(4)), reporter())
    rate = success / max(1, success + failure)
    out = fixtures.SRC / "output" / "stability_60min.json"
    out.write_text(json.dumps({
        "status": "complete", "elapsed_s": int(time.monotonic() - started),
        "success": success, "failure": failure, "success_rate": round(rate, 4), "samples": samples,
    }, indent=2) + "\n", encoding="utf-8")
    await gw.stop()
    await marker.stop()
    await runner.cleanup()
    app.close()
    print(f"[stability] COMPLETE success={success} failure={failure} rate={rate:.3%}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
