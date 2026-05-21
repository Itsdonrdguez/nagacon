from __future__ import annotations

import argparse
import threading

from app.core.config import settings
from app.services.search_jobs import worker_loop


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the NagaCon search job worker.")
    parser.add_argument("--once", action="store_true", help="Process queued jobs once, then exit.")
    parser.add_argument(
        "--poll-seconds",
        type=float,
        default=None,
        help="Override the queue polling interval in seconds.",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=None,
        help="Number of worker threads to run in this process.",
    )
    args = parser.parse_args()

    if args.once:
        processed = worker_loop(poll_seconds=args.poll_seconds, max_jobs=1)
        print(f"Processed {processed} queued job(s).")
        return 0

    concurrency = max(1, int(args.concurrency or getattr(settings, "SEARCH_JOB_MAX_CONCURRENCY", 4) or 4))
    print(
        "Starting NagaCon search job worker "
        f"(poll={args.poll_seconds if args.poll_seconds is not None else getattr(settings, 'SEARCH_JOB_POLL_SECONDS', 2.0)}s, "
        f"concurrency={concurrency})."
    )
    threads: list[threading.Thread] = []
    for index in range(concurrency):
        thread = threading.Thread(
            target=worker_loop,
            kwargs={"poll_seconds": args.poll_seconds, "max_jobs": None},
            daemon=False,
            name=f"nagacon-worker-{index + 1}",
        )
        thread.start()
        threads.append(thread)
    for thread in threads:
        thread.join()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
