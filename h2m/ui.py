"""Affichage console et petits formatages."""
import sys


def info(m):
    print(f"\x1b[36m→\x1b[0m {m}", flush=True)


def good(m):
    print(f"\x1b[32m✓\x1b[0m {m}", flush=True)


def warn(m):
    print(f"\x1b[33m! {m}\x1b[0m", flush=True)


def die(m):
    print(f"\x1b[31m✗ {m}\x1b[0m", flush=True)
    sys.exit(1)


def human_size(n):
    for u in ("o", "Ko", "Mo", "Go"):
        if n < 1024 or u == "Go":
            return f"{n:.0f} {u}" if u == "o" else f"{n:.1f} {u}"
        n /= 1024


def fmt_time(s):
    s = int(s)
    return f"{s // 60}:{s % 60:02d}"
