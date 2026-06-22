from __future__ import annotations

import argparse
import json

from . import runner


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", nargs="?", default="collect", choices=["collect", "send-report", "print-report"])
    args = parser.parse_args()

    if args.action == "collect":
        data = runner.collect_all()
        print(json.dumps({"status": data["overall_status"], "generated_at": data["generated_at"]}))
        return 0
    if args.action == "send-report":
        return runner.send_report()
    if args.action == "print-report":
        print(runner.print_report())
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

