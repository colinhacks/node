#!/usr/bin/env python3
"""Generate and run the fixed native startup/throughput comparison."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time


def select_plan(plan, names=None, rounds=None, seed=None):
    result = dict(plan)
    if names is not None:
        known = {item['name'] for item in plan['workloads']}
        if not names or len(names) != len(set(names)) or set(names) - known:
            raise ValueError('Workload selection is empty, duplicated, or unknown')
        result['workloads'] = [item for item in plan['workloads'] if item['name'] in names]
    if rounds is not None:
        if rounds < 1:
            raise ValueError('Round count must be positive')
        result['rounds'] = rounds
    if seed is not None:
        result['seed'] = seed
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--artifact', action='append', required=True)
    parser.add_argument('--startup-workload', action='append')
    parser.add_argument('--throughput-workload', action='append')
    parser.add_argument('--startup-rounds', type=int)
    parser.add_argument('--throughput-rounds', type=int)
    parser.add_argument('--seed', type=int)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    tools = Path(__file__).resolve().parent
    events = []

    def run(name, command, env=None):
        start = time.time()
        with (output / (name + '.log')).open('xb') as log:
            result = subprocess.run(list(map(str, command)), env=env,
                                    stdout=log, stderr=subprocess.STDOUT)
        row = dict(name=name, command=list(map(str, command)), started=start,
                   seconds=time.time() - start, exit=result.returncode)
        events.append(row)
        (output / 'events.json').write_text(json.dumps(events, indent=2), encoding='utf-8')
        print(json.dumps(row), flush=True)
        return result.returncode

    def host_snapshot(name):
        command = (['powershell', '-NoProfile', '-NonInteractive', '-Command',
                    'Get-Date -Format o; Get-Process | Sort-Object CPU -Descending | Select-Object -First 30 Name,Id,CPU,WorkingSet; Get-CimInstance Win32_OperatingSystem | Select-Object Caption,Version,FreePhysicalMemory; Get-CimInstance Win32_Processor | Select-Object Name,NumberOfCores,NumberOfLogicalProcessors']
                   if os.name == 'nt' else ['sh', '-c',
                    'date -u; uptime; free -m; ps -eo pid,comm,pcpu,pmem,args --sort=-pcpu | head -n 35; cat /proc/self/status; cat /proc/pressure/cpu'])
        run(name, command)

    config = output / 'configs'
    command = [sys.executable, tools / 'make-bench-configs.py', '--source',
               args.source.resolve(), '--output', config]
    for artifact in args.artifact:
        command.extend(['--artifact', artifact])
    if run('configuration', command):
        return 1
    for phase in ('startup', 'throughput'):
        path = config / (phase + '.json')
        original = json.loads(path.read_text())
        plan = select_plan(original, getattr(args, phase + '_workload'),
                           getattr(args, phase + '_rounds'), args.seed)
        if plan != original:
            path.with_suffix('.original.json').write_text(json.dumps(original, indent=2) + '\n')
            path.write_text(json.dumps(plan, indent=2) + '\n')
    scripts = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
               for p in (Path(__file__), tools / 'paired_bench.py', tools / 'make-bench-configs.py')}
    (output / 'instrument-hashes.json').write_text(json.dumps(scripts, indent=2), encoding='utf-8')
    host_snapshot('host-before')
    environment = {k: v for k, v in os.environ.items()
                   if not k.upper().startswith(('NODE_', '__NUB_'))}
    environment.pop('LLVM_PROFILE_FILE', None)
    for name in ('identity-control', 'startup', 'throughput'):
        run(name, [sys.executable, tools / 'paired_bench.py', '--config',
                   config / (name + '.json'), '--output', output / name], environment)
    host_snapshot('host-after')
    return int(any(event['exit'] for event in events))


if __name__ == '__main__':
    raise SystemExit(main())
