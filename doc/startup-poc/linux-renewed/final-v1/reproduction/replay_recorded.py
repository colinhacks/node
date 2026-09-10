#!/usr/bin/env python3
"""Revalidate public raw samples and reproduce the recorded Linux tables."""

import argparse
import gzip
import json
from pathlib import Path
import shutil
import statistics
import subprocess
import sys
import tempfile

from verify_manifest import verify


def first_js(root):
    summary = json.loads(gzip.decompress((root / 'first-js/summary.json.gz').read_bytes()))
    rows = [json.loads(line) for line in gzip.decompress(
        (root / 'first-js/raw.jsonl.gz').read_bytes()).decode().splitlines()]
    groups = {}
    positive = set()
    for row in rows:
        assert row['status'] == 'ok' and row['exit_code'] == 0
        artifact = row['artifact']
        assert row['artifact_sha256'] == summary['artifacts'][artifact]['sha256_before']
        if row['phase'] == 'preflight':
            assert row['case'] == 'positive_delay' and artifact not in positive
            assert row['positive_busywait_ns'] >= summary['busywait_ns']
            positive.add(artifact)
            continue
        assert row['phase'] in ('measured', 'warmup')
        assert row['case'] in ('cjs', 'esm', 'eval')
        group = groups.setdefault((artifact, row['case'], row['phase']), {})
        assert row['round'] not in group
        group[row['round']] = row
    assert positive == set(summary['artifacts'])
    assert len(groups) == len(summary['artifacts']) * 3 * 2
    for (artifact, case, phase), group in groups.items():
        assert set(group) == set(range(summary['rounds'] if phase == 'measured' else summary['warmups']))
        if phase == 'measured':
            for metric in ('first_js_ms', 'process_lifetime_ms', 'total_ms'):
                actual = statistics.median(row[metric] for row in group.values())
                assert actual == summary['summaries'][case][metric]['samples'][artifact]['median']
    return len(rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--package', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    root = args.package.resolve(strict=True)
    verify(root)
    assert not args.output.exists(), 'output already exists'
    count = first_js(root)
    with tempfile.TemporaryDirectory(prefix='linux-evidence-replay-') as directory:
        matrix = Path(directory) / 'matrix'
        memory = Path(directory) / 'memory'
        for phase in ('identity-control', 'startup', 'throughput', 'release-references', 'first-js', 'memory'):
            target = (memory if phase == 'memory' else matrix / phase if phase in ('release-references', 'first-js')
                      else matrix / 'comparison' / phase)
            target.mkdir(parents=True)
            for source in sorted((root / phase).glob('*.gz')):
                with gzip.open(source, 'rb') as stream, (target / source.stem).open('wb') as output:
                    shutil.copyfileobj(stream, output)
        shutil.copyfile(root / 'events.json', matrix / 'events.json')
        subprocess.run([sys.executable, '-B', str(root / 'tools/summarize-final-linux.py'),
                        '--matrix', str(matrix), '--memory', str(memory),
                        '--output', str(args.output.resolve())], check=True)
    assert (args.output / 'TABLES.md').read_bytes() == (root / 'TABLES.md').read_bytes()
    print(f'replayed all tables; verified {count} first-JavaScript records')


if __name__ == '__main__':
    main()
