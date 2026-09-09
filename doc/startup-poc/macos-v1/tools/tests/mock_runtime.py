#!/usr/bin/env python3
"""Small direct-runtime substitute for startup_lab.py tests."""

import os
import sys


if "--version" in sys.argv:
    print("mock-runtime 1.0")
    raise SystemExit(0)

fd = os.environ.get("STARTUP_LAB_READY_FD")
if fd:
    os.write(int(fd), b"1")
raise SystemExit(0)
