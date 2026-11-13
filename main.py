"""Synergia — run `python main.py` and pick an engine."""
import argparse
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from synergia.cli import main  # noqa: E402

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Synergia content engine")
    ap.add_argument("--demo", action="store_true",
                    help="Engines A/B use built-in sample scripts (skip the Claude round-trip)")
    ap.add_argument("--debug", action="store_true",
                    help="Safe-zone overlays on images, tracking debug video for Engine C, tracebacks")
    args = ap.parse_args()
    try:
        main(is_demo=args.demo, debug=args.debug)
    except KeyboardInterrupt:
        pass
