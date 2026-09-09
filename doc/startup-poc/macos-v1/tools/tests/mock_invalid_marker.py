#!/usr/bin/env python3
import os
import sys

if "--version" in sys.argv or "--revision" in sys.argv:
    print("mock-invalid-marker 1.0")
else:
    os.write(int(os.environ["STARTUP_LAB_READY_FD"]), b"x")
