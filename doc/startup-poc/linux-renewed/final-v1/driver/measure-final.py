#!/usr/bin/env python3
"""Run the final native comparison, first-JS diagnostic, and release references."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time


def preflight_inputs(source, artifacts, references):
    if not source.is_absolute() or not source.is_dir():
        raise ValueError('--source must name an existing absolute directory')
    suffix = '.exe' if os.name == 'nt' else ''
    paths = {**artifacts,
             'release': references / ('release-node' + suffix),
             'bun': references / ('bun' + suffix)}
    for label, value in paths.items():
        path = Path(value)
        if not path.is_absolute() or not path.is_file():
            raise ValueError(f'{label} must name an existing absolute file: {path}')


def reference_plan(startup, artifacts, final_label, references, all_artifacts=False):
    suffix = '.exe' if os.name == 'nt' else ''
    workloads = []
    for item in startup['workloads']:
        if item['name'] not in ('empty-cjs', 'empty-mjs', 'empty-eval', 'hello'):
            continue
        item = dict(item)
        if item['name'] == 'empty-eval':
            item.update(name='noop-eval', argv=['-e', ';'])
        workloads.append(item)
    selected = dict(artifacts) if all_artifacts else {
        'baseline': artifacts['baseline'], final_label: artifacts[final_label]}
    selected.update(release=str(references / ('release-node' + suffix)),
                    bun=str(references / ('bun' + suffix)))
    return dict(startup, rounds=200, warmups=10, seed=20260916,
                artifacts=selected,
                workloads=workloads)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--references', type=Path, required=True)
    parser.add_argument('--artifact', action='append', required=True)
    parser.add_argument('--final-label', required=True)
    parser.add_argument('--all-reference-artifacts', action='store_true',
                        help='Compare every supplied variant with the release references')
    args = parser.parse_args()
    artifacts = dict(item.split('=', 1) for item in args.artifact)
    if (len(artifacts) != len(args.artifact) or 'baseline' not in artifacts or
            args.final_label not in artifacts or args.final_label in ('baseline', 'release', 'bun') or
            set(artifacts) & {'release', 'bun'}):
        parser.error('Require unique artifact labels, baseline, and a distinct final label')
    try:
        preflight_inputs(args.source, artifacts, args.references)
    except ValueError as error:
        parser.error(str(error))
    args.output.mkdir(parents=True, exist_ok=False)
    scripts = Path(__file__).resolve().parent
    events = []

    def run(label, command):
        command = list(map(str, command))
        started = time.time()
        with (args.output / (label + '.log')).open('xb') as log:
            result = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT)
        events.append(dict(label=label, command=command, started=started,
                           seconds=time.time() - started, exit=result.returncode))
        (args.output / 'events.json').write_text(json.dumps(events, indent=2) + '\n')
        print(json.dumps(events[-1]), flush=True)
        if result.returncode:
            raise RuntimeError(f'{label} failed; original logs retained')

    (args.output / 'driver.sha256').write_text(hashlib.sha256(Path(__file__).read_bytes()).hexdigest() + '\n')
    command = [sys.executable, scripts / 'measure-native.py', '--source', args.source,
               '--output', args.output / 'comparison', '--startup-rounds', '350',
               '--throughput-rounds', '30', '--seed', '20260914']
    for item in args.artifact:
        command += ['--artifact', item]
    run('comparison', command)
    command = [sys.executable, scripts / 'first-js/first_js.py', '--output',
               args.output / 'first-js', '--rounds', '350', '--warmups', '10', '--seed', '20260915']
    for item in args.artifact:
        command += ['--artifact', item]
    # Bun's hrtime epoch is process-relative, unlike Node's OS clock epoch.
    run('first-js', command)
    startup = json.loads((args.output / 'comparison/configs/startup.json').read_text())
    plan = reference_plan(startup, artifacts, args.final_label, args.references,
                          args.all_reference_artifacts)
    path = args.output / 'release-references.json'
    path.write_text(json.dumps(plan, indent=2) + '\n')
    run('release-references', [sys.executable, scripts / 'paired_bench.py',
                               '--config', path, '--output', args.output / 'release-references'])
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
