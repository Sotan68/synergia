"""Synergia — run `python main.py` and pick an engine."""
import argparse
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def upload_due_all() -> None:
    """Background job (Windows Task Scheduler): run the upload job once per profile, each in its own
    process so it uses that profile's YouTube channel, queue and settings."""
    import os
    import subprocess

    from synergia.config import list_profiles

    for name in list_profiles():
        subprocess.run([sys.executable, __file__, "--upload-due", "--profile", name],
                       env={**os.environ, "SYNERGIA_PROFILE_NAME": name},
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def upload_due() -> None:
    """Upload the active profile's queued autopilot videos; log to its cache/autopilot.log."""
    from datetime import datetime

    from synergia.config import CFG
    from synergia.publish import queue

    log = CFG.output.cache_dir / "autopilot.log"
    log.parent.mkdir(parents=True, exist_ok=True)

    def write(msg: str) -> None:
        with log.open("a", encoding="utf-8") as f:
            f.write(f"{datetime.now():%Y-%m-%d %H:%M:%S}  {msg}\n")
        print(msg)

    def on_item(event: str, info: dict) -> None:
        if event == "start":
            write(f"uploading {info['folder']} (goes live {info['publish_at']:%a %d %b %H:%M})")
        elif event == "done":
            write(f"  ok {info['url']}" + ("  (schedule ignored by YouTube)" if info["schedule_dropped"] else ""))
        else:
            write(f"  failed: {info['error']}")

    try:
        s = queue.upload_due(interactive=False, on_item=on_item)
    except Exception as e:  # noqa: BLE001 — a background job has nowhere else to report
        write(f"upload run failed: {e}")
        return
    write(f"run finished: {len(s['uploaded'])} uploaded, {s['left']} still queued"
          + (f"; stopped: {s['stopped']}" if s["stopped"] else ""))


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Synergia content engine")
    ap.add_argument("--demo", action="store_true",
                    help="Engines A/B use built-in sample scripts (skip the Claude round-trip)")
    ap.add_argument("--debug", action="store_true",
                    help="Safe-zone overlays on images, tracking debug video for Engine C, tracebacks")
    ap.add_argument("--gui", action="store_true",
                    help="Open the browser interface instead of the console menu")
    ap.add_argument("--upload-due", action="store_true",
                    help="Upload queued autopilot videos (used by the daily scheduled task)")
    ap.add_argument("--profile", metavar="NAME",
                    help="Use this profile (a folder in profiles/) instead of the active one")
    args = ap.parse_args()
    if args.profile:      # before anything loads the config
        import os
        os.environ["SYNERGIA_PROFILE_NAME"] = args.profile
    if args.upload_due:
        upload_due() if args.profile else upload_due_all()
        sys.exit()
    from synergia.cli import main
    if args.gui:
        from synergia.gui.app import start
        start(is_demo=args.demo, debug=args.debug)
        sys.exit()
    try:
        main(is_demo=args.demo, debug=args.debug)
    except KeyboardInterrupt:
        pass
