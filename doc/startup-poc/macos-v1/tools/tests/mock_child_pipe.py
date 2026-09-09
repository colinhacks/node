#!/usr/bin/env python3
import os
import subprocess
import sys
import time

if "--version" in sys.argv or "--revision" in sys.argv:
    print("mock-child-pipe 1.0")
else:
    subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"], close_fds=False)
    time.sleep(30)
