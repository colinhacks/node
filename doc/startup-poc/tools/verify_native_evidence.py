#!/usr/bin/env python3
"""Export and verify a small, explicit, sanitized native-evidence package."""

from __future__ import annotations
import argparse
import gzip
import hashlib
import json
import math
import re
import statistics
import sys
from pathlib import Path
from typing import Any

SCHEMA = 1
NAME = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
SAFE = {".json", ".jsonl", ".cjs", ".mjs", ".py"}
BAD = {".pem", ".key", ".crt", ".p12", ".profile", ".dmp", ".dump", ".core", ".sqlite"}
SECRET = re.compile(
    r'(?i)(?:api[_-]?key|access[_-]?token|refresh[_-]?token|private[_-]?key|'
    r'client[_-]?secret|secret|password|authorization)["\x27]?\s*[:=]|'
    r'-----BEGIN [A-Z ]*PRIVATE KEY-----|["\x27]type["\x27]\s*:\s*["\x27]service_account'
)
# Only redact the recorded cloud-host family. Do not alter ordinary runner filenames.
HOST = re.compile(r"(?i)\bnode-startup-(?:linux|win)-[a-z0-9-]+\b")
PATH = re.compile(
    r"(?:/Users/[^\s\"']+|/home/[^\s\"']+|/opt/node-startup(?:-[a-z0-9]+)?[^\s\"']*|[A-Za-z]:[\\/][^\s\"']+)"
)


def req(v, m):
    if not v:
        raise ValueError(m)


def digest(v):
    return hashlib.sha256(v).hexdigest()


def canon(v):
    return (
        json.dumps(v, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n"
    ).encode()


def gz(v):
    return gzip.compress(v, mtime=0)


def name(v, label="name"):
    req(isinstance(v, str) and NAME.fullmatch(v), f"invalid {label}: {v!r}")
    return v


def rel(v, label):
    req(isinstance(v, str) and v and "\\" not in v, f"invalid {label} path")
    p = Path(v)
    req(
        not p.is_absolute()
        and ".." not in p.parts
        and "." not in p.parts
        and p.suffix in SAFE
        and p.suffix not in BAD,
        f"unsafe or unselected {label} path: {v}",
    )
    return p


def clean_string(v):
    n = 0

    def path(m):
        nonlocal n
        n += 1
        x = m.group(0)
        if x.startswith("/opt/node-startup"):
            q = re.match(r"/opt/node-startup(?:-[a-z0-9]+)?", x, re.I)
            return "<workspace>" + x[q.end() :]
        if x.startswith("/Users/") or x.startswith("/home/"):
            z = x.split("/", 3)
            return "<home>" + ("/" + z[3] if len(z) == 4 else "")
        normalized = x[3:].replace("\\", "/")
        if normalized.lower().startswith("users/"):
            parts = normalized.split("/", 2)
            return "<home>" + ("/" + parts[2] if len(parts) == 3 else "")
        return "<windows-path>/" + normalized

    v = PATH.sub(path, v)
    v, k = HOST.subn("<redacted-host>", v)
    return v, n + k


def clean(v):
    if isinstance(v, str):
        return clean_string(v)
    if isinstance(v, list):
        out = []
        n = 0
        for x in v:
            y, k = clean(x)
            out.append(y)
            n += k
        return out, n
    if isinstance(v, dict):
        out = {}
        n = 0
        for k, x in v.items():
            q, m = clean_string(k)
            req(q not in out, f"redaction key collision: {q}")
            y, z = clean(x)
            out[q] = y
            n += m + z
        return out, n
    return v, 0


def source_file(root, p):
    q = (root / p).resolve(strict=True)
    try:
        q.relative_to(root)
    except ValueError:
        raise ValueError(f"selected symlink escapes source root: {p}")
    req(q.is_file() and not (root / p).is_symlink(), f"selected path is not a regular file: {p}")
    return q


def spec_files(spec):
    req(
        spec.get("schema") == 1 and isinstance(spec.get("inputs"), list) and spec["inputs"],
        "input spec schema must be 1",
    )
    out = []
    ins = []
    seen = set()
    for x in spec["inputs"]:
        req(
            isinstance(x, dict) and set(x) <= {"kind", "name", "report", "raw", "files"},
            "unknown input-spec field",
        )
        k = x.get("kind")
        n = name(x.get("name"), "input name")
        req(k in {"paired", "first-js"} and n not in seen, "invalid or duplicate input")
        seen.add(n)
        a, b = rel(x.get("report"), "report"), rel(x.get("raw"), "raw")
        req(a.suffix == ".json" and b.suffix == ".jsonl", f"{n}: report/raw extensions")
        out += [
            (f"evidence/{n}/{'summary.json.gz' if k=='first-js' else 'report.json.gz'}", a, 1),
            (f"evidence/{n}/raw.jsonl.gz", b, 1),
        ]
        req(isinstance(x.get("files", []), list), f"{n}: files must be list")
        for f in x.get("files", []):
            p = rel(f, "supporting")
            out.append((f"evidence/{n}/files/{p.name}.gz", p, 0))
        ins.append({"kind": k, "name": n})
    req(len({x[0] for x in out}) == len(out), "input spec maps two sources to one destination")
    return out, ins


def export(source, spec_path, out):
    source = source.resolve(strict=True)
    req(source.is_dir() and not source.is_symlink(), "source must be a real directory")
    req(not out.exists(), f"output already exists: {out}")
    files, ins = spec_files(json.loads(spec_path.read_text()))
    out.mkdir(parents=True)
    manifest = []
    total = 0
    for dest, p, is_json in files:
        raw = source_file(source, p).read_bytes()
        text = raw.decode("utf8")
        req(not SECRET.search(text), f"suspicious secret marker: {p}")
        if is_json or p.suffix in {".json", ".jsonl"}:
            if p.suffix == ".json":
                v, n = clean(json.loads(raw))
                data = canon(v)
            else:
                n = 0
                rows = []
                for line in raw.splitlines():
                    v, k = clean(json.loads(line))
                    rows.append(v)
                    n += k
                data = b"".join(canon(v) for v in rows)
        else:
            req(
                not PATH.search(text) and not HOST.search(text),
                f"supporting executable input has confidential path: {p}",
            )
            data, n = raw, 0
        pub = gz(data)
        target = out / dest
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(pub)
        manifest.append(
            {
                "path": dest,
                "origin_sha256": digest(raw),
                "origin_bytes": len(raw),
                "published_sha256": digest(pub),
                "published_bytes": len(pub),
                "decompressed_sha256": digest(data),
                "decompressed_bytes": len(data),
                "redactions": n,
            }
        )
        total += n
    (out / "manifest.json").write_bytes(
        canon({"schema": 1, "inputs": ins, "files": manifest, "redactions": total})
    )
    print(
        json.dumps({"files": len(files), "output": str(out), "redactions": total}, sort_keys=True)
    )


def pfile(root, v):
    req(
        isinstance(v, str) and v.startswith("evidence/") and v.endswith(".gz"),
        f"unsafe manifest path: {v}",
    )
    rel(v[:-3], "manifest")
    candidate = root / v
    resolved = candidate.resolve(strict=True)
    try:
        resolved.relative_to(root)
    except ValueError:
        raise ValueError(f"package path escapes root: {v}")
    req(resolved.is_file() and not candidate.is_symlink(), f"missing package file: {v}")
    return resolved


def close(a, b):
    return (
        math.isclose(a, b, rel_tol=1e-12, abs_tol=1e-12)
        if isinstance(a, (int, float)) and not isinstance(a, bool)
        else a == b
    )


def pct(x, p):
    x = sorted(x)
    q = (len(x) - 1) * p
    i, j = math.floor(q), math.ceil(q)
    return x[i] if i == j else x[i] * (j - q) + x[j] * (q - i)


def universe(rows, expected, label):
    seen = set()
    for r in rows:
        k = (r.get("phase"), r.get("case", r.get("workload")), r.get("artifact"), r.get("round"))
        req(
            k in expected and k not in seen and isinstance(r.get("status"), str),
            f"{label}: unknown or duplicate raw row",
        )
        seen.add(k)
    req(seen == expected, f"{label}: raw-row coverage mismatch")


def paired(report, rows, n):
    req(
        report.get("schema") == 1
        and isinstance(report.get("rounds"), int)
        and isinstance(report.get("warmups"), int),
        f"{n}: unsupported paired schema",
    )
    arts, works, sums = report.get("artifacts"), report.get("workloads"), report.get("summaries")
    req(
        isinstance(arts, dict) and isinstance(works, dict) and set(works) == set(sums or {}),
        f"{n}: unsupported paired layout",
    )
    req(len(arts) >= 2, f"{n}: paired report needs at least two artifacts")
    req(
        all(
            x.get("metric_kind") in {"process-lifetime", "json-throughput", "node-csv-throughput"}
            for x in works.values()
        ),
        f"{n}: unsupported metric kind",
    )
    exp = {
        (ph, w, a, r)
        for ph, c in {"warmup": report["warmups"], "measured": report["rounds"]}.items()
        for w in works
        for a in arts
        for r in range(c)
    }
    universe(rows, exp, n)
    for r in rows:
        req(
            r.get("metric_kind") == works[r["workload"]]["metric_kind"],
            f"{n}: metric kind mismatch",
        )
    req(
        report.get("failure_count") == sum(r["status"] != "ok" for r in rows),
        f"{n}: failure_count mismatch",
    )
    checked = 0
    for w, s in sums.items():
        expected_pairs = {
            f"{left}_over_{right}"
            for index, left in enumerate(sorted(arts))
            for right in sorted(arts)[index + 1 :]
        }
        req(
            s.get("metric_kind") == works[w]["metric_kind"]
            and set(s.get("samples", {})) == set(arts),
            f"{n}/{w}: summary layout",
        )
        req(set(s.get("paired_ratios", {})) == expected_pairs, f"{n}/{w}: paired scope")
        selected = [r for r in rows if r["phase"] == "measured" and r["workload"] == w]
        for a, e in s["samples"].items():
            x = [
                r["metric_value"]
                for r in selected
                if r["artifact"] == a and r["status"] == "ok" and r.get("metric_value") is not None
            ]
            actual = {
                "n": len(x),
                "median": statistics.median(x) if x else None,
                "p50": statistics.median(x) if x else None,
                "p95": pct(x, 0.95) if x else None,
                "min": min(x) if x else None,
                "max": max(x) if x else None,
            }
            req(
                set(e) == set(actual) and all(close(actual[k], e[k]) for k in actual),
                f"{n}/{w}/{a}: sample summary mismatch",
            )
            checked += 1
        for label, e in s.get("paired_ratios", {}).items():
            if e is None:
                continue
            l, r = e.get("left_artifact"), e.get("right_artifact")
            left = {
                x["round"]: x["metric_value"]
                for x in selected
                if x["artifact"] == l and x["status"] == "ok"
            }
            right = {
                x["round"]: x["metric_value"]
                for x in selected
                if x["artifact"] == r and x["status"] == "ok"
            }
            same = sorted(set(left) & set(right))
            q = [left[i] / right[i] for i in same if right[i] > 0]
            req(
                l in arts
                and r in arts
                and label == f"{l}_over_{r}"
                and same == e.get("paired_rounds")
                and len(q) == e.get("n")
                and close(statistics.median(q), e.get("median_ratio")),
                f"{n}/{w}/{label}: paired median mismatch",
            )
            checked += 1
    return checked


def first(report, rows, n):
    req(
        report.get("schema") == 1
        and isinstance(report.get("rounds"), int)
        and isinstance(report.get("warmups"), int),
        f"{n}: unsupported first-JS schema",
    )
    arts, sums = report.get("artifacts"), report.get("summaries")
    cases = ("cjs", "esm", "eval")
    req(
        isinstance(arts, dict) and set(sums or {}) == set(cases),
        f"{n}: unsupported first-JS layout",
    )
    req(len(arts) >= 2, f"{n}: first-JS report needs at least two artifacts")
    exp = {
        (ph, c, a, r)
        for ph, cs, count in (
            ("preflight", ("positive_delay",), 1),
            ("warmup", cases, report["warmups"]),
            ("measured", cases, report["rounds"]),
        )
        for c in cs
        for a in arts
        for r in range(count)
    }
    universe(rows, exp, n)
    req(
        report.get("failure_count") == sum(r["status"] != "ok" for r in rows),
        f"{n}: failure_count mismatch",
    )
    checked = 0
    for c, metrics in sums.items():
        req(
            set(metrics) == {"first_js_ms", "total_ms", "process_lifetime_ms"},
            f"{n}/{c}: unsupported first-JS metrics",
        )
        selected = [r for r in rows if r["phase"] == "measured" and r["case"] == c]
        for metric, block in metrics.items():
            expected_pairs = {
                frozenset((left, right))
                for index, left in enumerate(arts)
                for right in list(arts)[index + 1 :]
            }
            req(set(block.get("samples", {})) == set(arts), f"{n}/{c}/{metric}: summary layout")
            actual_pairs = set()
            for a, e in block["samples"].items():
                x = [
                    r.get(metric)
                    for r in selected
                    if r["artifact"] == a and r["status"] == "ok" and r.get(metric) is not None
                ]
                actual = {
                    "n": len(x),
                    "median": statistics.median(x) if x else None,
                    "p95": pct(x, 0.95) if x else None,
                }
                req(
                    set(e) == set(actual) and all(close(actual[k], e[k]) for k in actual),
                    f"{n}/{c}/{metric}/{a}: sample summary mismatch",
                )
                checked += 1
            for label, e in block.get("paired_ratios", {}).items():
                if e is None:
                    continue
                l, r = e.get("left_artifact"), e.get("right_artifact")
                left = {
                    x["round"]: x.get(metric)
                    for x in selected
                    if x["artifact"] == l and x["status"] == "ok"
                }
                right = {
                    x["round"]: x.get(metric)
                    for x in selected
                    if x["artifact"] == r and x["status"] == "ok"
                }
                same = sorted(set(left) & set(right))
                q = [left[i] / right[i] for i in same if right[i] > 0]
                req(
                    l in arts
                    and r in arts
                    and label == f"{l}_over_{r}"
                    and same == e.get("paired_rounds")
                    and len(q) == e.get("n")
                    and close(statistics.median(q), e.get("median_ratio")),
                    f"{n}/{c}/{metric}/{label}: paired median mismatch",
                )
                actual_pairs.add(frozenset((l, r)))
                checked += 1
            req(actual_pairs == expected_pairs, f"{n}/{c}/{metric}: paired scope")
    return checked


def verify(root):
    root = root.resolve(strict=True)
    m = json.loads((root / "manifest.json").read_text())
    req(
        m.get("schema") == 1
        and isinstance(m.get("files"), list)
        and isinstance(m.get("inputs"), list),
        "unsupported manifest schema",
    )
    seen = set()
    for e in m["files"]:
        req(
            set(e)
            == {
                "path",
                "origin_sha256",
                "origin_bytes",
                "published_sha256",
                "published_bytes",
                "decompressed_sha256",
                "decompressed_bytes",
                "redactions",
            }
            and e["path"] not in seen,
            "unsupported manifest file entry",
        )
        seen.add(e["path"])
        data = pfile(root, e["path"]).read_bytes()
        req(
            digest(data) == e["published_sha256"] and len(data) == e["published_bytes"],
            f"archive hash mismatch: {e['path']}",
        )
        raw = gzip.decompress(data)
        req(
            digest(raw) == e["decompressed_sha256"] and len(raw) == e["decompressed_bytes"],
            f"decompressed hash mismatch: {e['path']}",
        )
        req(
            not SECRET.search(raw.decode("utf8", "replace")),
            f"suspicious secret marker: {e['path']}",
        )
    input_names = set()
    expected_files = set()
    for item in m["inputs"]:
        req(
            set(item) == {"kind", "name"} and item["kind"] in {"paired", "first-js"},
            "unsupported manifest input",
        )
        item_name = name(item["name"], "manifest input name")
        req(item_name not in input_names, "duplicate manifest input name")
        input_names.add(item_name)
        report = "summary.json.gz" if item["kind"] == "first-js" else "report.json.gz"
        expected_files.update(
            {f"evidence/{item_name}/{report}", f"evidence/{item_name}/raw.jsonl.gz"}
        )
    req(expected_files <= seen, "input report or raw stream is absent from manifest")
    checked = 0
    for i in m["inputs"]:
        req(
            set(i) == {"kind", "name"} and i["kind"] in {"paired", "first-js"},
            "unsupported manifest input",
        )
        n = name(i["name"], "manifest input name")
        base = f"evidence/{n}/"
        report = "summary.json.gz" if i["kind"] == "first-js" else "report.json.gz"
        r = json.loads(gzip.decompress(pfile(root, base + report).read_bytes()))
        rows = [
            json.loads(x)
            for x in gzip.decompress(pfile(root, base + "raw.jsonl.gz").read_bytes()).splitlines()
        ]
        checked += (first if i["kind"] == "first-js" else paired)(r, rows, n)
    print(
        json.dumps({"files_verified": len(m["files"]), "summary_checks": checked}, sort_keys=True)
    )


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)
    x = sub.add_parser("export")
    x.add_argument("--source", type=Path, required=True)
    x.add_argument("--spec", type=Path, required=True)
    x.add_argument("--output", type=Path, required=True)
    x = sub.add_parser("verify")
    x.add_argument("--package", type=Path, required=True)
    a = p.parse_args(argv)
    try:
        if a.command == "export":
            export(a.source, a.spec, a.output)
        else:
            verify(a.package)
    except (OSError, ValueError, json.JSONDecodeError, gzip.BadGzipFile) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
