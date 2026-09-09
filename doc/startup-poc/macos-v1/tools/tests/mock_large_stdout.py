#!/usr/bin/env python3
import sys

if "--version" in sys.argv or "--revision" in sys.argv:
    print("mock-large-stdout 1.0")
else:
    sys.stdout.write("x" * (2 * 1024 * 1024))
