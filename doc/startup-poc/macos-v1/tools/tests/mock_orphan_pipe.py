#!/usr/bin/env python3
import subprocess
import sys

if "--version" in sys.argv or "--revision" in sys.argv:
    print("mock-orphan-pipe 1.0")
else:
    subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"], close_fds=False)
