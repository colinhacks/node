#!/usr/bin/env python3
"""Run a command without inherited Node/Bun wrapper configuration."""

import os
import sys

from startup_lab import sanitized_environment


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit("usage: clean_env.py COMMAND [ARG ...]")
    environment, _ = sanitized_environment("system")
    os.execvpe(sys.argv[1], sys.argv[1:], environment)
