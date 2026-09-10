#!/usr/bin/env python3
"""Create a narrow reviewable header candidate without editing a source tree."""
import argparse
import difflib
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("source", type=Path)
parser.add_argument("output", type=Path)
args = parser.parse_args()
relative = Path("deps/v8/src/snapshot/snapshot-source-sink.h")
original = (args.source / relative).read_text()
old = """    uint32_t answer = data_[position_];
    answer |= data_[position_ + 1] << 8;
    answer |= data_[position_ + 2] << 16;
    answer |= data_[position_ + 3] << 24;"""
new = """    uint32_t answer = base::ReadLittleEndianValue<uint32_t>(
        reinterpret_cast<Address>(data_ + position_));"""
assert original.count(old) == 1
candidate = original.replace(old, new).replace(
    '#include "src/base/logging.h"',
    '#include "src/base/logging.h"\n#include "src/base/memory.h"')
output = args.output / "include/src/snapshot/snapshot-source-sink.h"
output.parent.mkdir(parents=True, exist_ok=True)
output.write_text(candidate)
patch = "".join(difflib.unified_diff(
    original.splitlines(True), candidate.splitlines(True),
    fromfile=f"a/{relative}", tofile=f"b/{relative}"))
test = (Path(__file__).parent / "test_snapshot_uint30.cc").read_text()
patch += "".join(difflib.unified_diff(
    [], test.splitlines(True), fromfile="/dev/null",
    tofile="b/test/cctest/test_snapshot_uint30.cc"))
(args.output / "candidate.patch").write_text(patch)
