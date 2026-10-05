#!/usr/bin/env python3
"""Command-line wrapper around jobbot.scan; see that module for details.

    python3 scripts/ats_scan.py --companies "Stripe,MongoDB,Adobe"
    python3 scripts/ats_scan.py --all --exclude "Salesforce" --max-yoe 3 --json
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from jobbot.scan import main  # noqa: E402

if __name__ == "__main__":
    main()
