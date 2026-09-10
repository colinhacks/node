#!/usr/bin/env python3
"""Validate the back-reference reservation model against opcode diagnostics."""

import argparse
import json
import pathlib
import sys

MINIMUM_CAPACITY = 2048
MAXIMUM_CAPACITY = 32768
ESTIMATED_BYTES_PER_BACK_REF = 32


def capacity(payload_bytes: int) -> int:
    return max(MINIMUM_CAPACITY, min(MAXIMUM_CAPACITY,
                                    payload_bytes // ESTIMATED_BYTES_PER_BACK_REF))


def find_sections(value):
    if isinstance(value, dict):
        if "payload_bytes" in value and ("objects" in value or "new_objects" in value):
            yield value
        for child in value.values():
            yield from find_sections(child)
    elif isinstance(value, list):
        for child in value:
            yield from find_sections(child)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("opcodes_json", type=pathlib.Path)
    parser.add_argument("--source", type=pathlib.Path,
                        help="patched deserializer.cc to inspect")
    args = parser.parse_args()
    if args.source:
        source = args.source.read_text()
        required = ("kEstimatedBytesPerBackRef = 32",
                    "kMinimumBackRefCapacity = 2048",
                    "kMaximumBackRefCapacity = 32768",
                    "back_refs_.reserve(initial_back_ref_capacity)")
        missing = [needle for needle in required if needle not in source]
        if missing:
            raise AssertionError(f"candidate source is missing: {missing}")

    expected = {(1546504, 26833): "startup", (305968, 8211): "shared",
                (614640, 16662): "context"}
    found = {}
    for section in find_sections(json.loads(args.opcodes_json.read_text())):
        payload = section["payload_bytes"]
        objects_field = section.get("objects", section.get("new_objects"))
        if isinstance(objects_field, dict):
            objects = sum(entry["count"] for entry in objects_field.values())
        else:
            objects = objects_field
        label = expected.get((payload, objects))
        if label:
            found[label] = (payload, objects)
    if set(found) != set(expected.values()):
        raise AssertionError(f"expected snapshot sections not found: {found}")
    for label in ("startup", "shared", "context"):
        payload, objects = found[label]
        reserved = capacity(payload)
        assert reserved >= objects, (label, reserved, objects)
        print(f"{label}: payload={payload} objects={objects} reserve={reserved} "
              f"spare={reserved - objects}")
    print("PASS: all recorded Node snapshot sections fit without back_refs_ growth")
    return 0


if __name__ == "__main__":
    sys.exit(main())
