"""Run every shipped test suite and report one combined result.

    python3 tests/run_all.py        (from the app root)
    py tests\\run_all.py            (on Mohamed's Windows PC)

Runs, in order:
  1. tests/test_business.py  — stdlib unittest (FEFO, unit conversion,
     shift/drawer, credit limits, partial payments, PIN header-only,
     PWA routes, cert resolution).
  2. tests/test_v57.py       — legacy check-style suite from the v5.7
     business-logic review (kept as-is, paths adapted to the app root).
  3. tests/test_v58.py       — legacy check-style suite from the v5.8
     staged-deletion work (kept as-is, paths adapted).
  4. tests/test_server_v57.py — legacy HTTP check-style suite for the
     mobile server (kept as-is, paths adapted).

Exit 0 only if ALL suites pass. The legacy suites are NOT unittest
modules (they run checks at import time), so they are executed as
subprocesses, never through unittest discovery.
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.dirname(HERE)


def run(name, cmd):
    print("\n===== %s =====" % name)
    print("  $ %s" % " ".join(cmd))
    r = subprocess.run(cmd, cwd=APP)
    print("  -> exit %d" % r.returncode)
    return r.returncode


def main():
    results = []
    results.append(("test_business.py (unittest)", run(
        "test_business.py (unittest)",
        [sys.executable, "-m", "unittest", "discover",
         "-s", "tests", "-p", "test_business.py", "-v"])))
    for name in ("test_v57.py", "test_v58.py", "test_server_v57.py", "test_v68_harmony.py"):
        results.append((name, run(name, [sys.executable,
                                         os.path.join("tests", name)])))
    print("\n===== SUMMARY =====")
    failed = [n for n, c in results if c != 0]
    for n, c in results:
        print("  %s: %s" % ("PASS" if c == 0 else "FAIL", n))
    if failed:
        print("FAILED: %s" % ", ".join(failed))
        return 1
    print("ALL SUITES PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
