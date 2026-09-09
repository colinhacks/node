#!/usr/bin/env python3
"""Run broad Node release gates without global process cleanup or rebuilding Node."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--artifact', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--jobs', type=int, default=8)
    parser.add_argument('--test-temp-dir', type=Path,
                        help='Short temporary root for Unix socket test paths')
    parser.add_argument('--git-metadata-source', type=Path,
                        help='Base repository for inspecting an archived build source')
    parser.add_argument('--expected-base',
                        help='Required HEAD identity for --git-metadata-source')
    args = parser.parse_args()
    source, artifact, output = (p.resolve() for p in
                                (args.source, args.artifact, args.output))
    git = ['git']
    if args.git_metadata_source:
        metadata = args.git_metadata_source.resolve()
        if not args.expected_base or not (metadata / '.git').is_dir():
            parser.error('--git-metadata-source requires a repository and --expected-base')
        head = subprocess.check_output(['git', '-C', str(metadata), 'rev-parse', 'HEAD'],
                                       text=True).strip()
        if head != args.expected_base:
            parser.error('Metadata repository HEAD differs from --expected-base')
        git += ['--git-dir=' + str(metadata / '.git'), '--work-tree=' + str(source)]
    output.mkdir(parents=True, exist_ok=False)
    build = source / ('Release' if os.name == 'nt' else 'out/Release')
    node = build / ('node.exe' if os.name == 'nt' else 'node')
    original = digest(artifact)
    assert digest(node) == original, 'Test executable differs from retained artifact'
    environment = {k: v for k, v in os.environ.items()
                   if not k.upper().startswith(('NODE_', '__NUB_'))}
    environment.pop('LLVM_PROFILE_FILE', None)
    environment['PATH'] = str(build) + os.pathsep + environment.get('PATH', '')
    environment['npm_config_jobs'] = '2'
    environment['PYTHONUTF8'] = '1'
    environment['GIT_OPTIONAL_LOCKS'] = '0'
    events = []

    def run(label, command, timeout=3600):
        command = list(map(str, command))
        start = time.time()
        with (output / (label + '.log')).open('xb') as log:
            try:
                process = subprocess.Popen(command, cwd=source, env=environment,
                                           stdout=log, stderr=subprocess.STDOUT,
                                           start_new_session=os.name != 'nt')
                code = process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                if os.name == 'nt':
                    subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'],
                                   stdout=log, stderr=subprocess.STDOUT, check=True)
                else:
                    os.killpg(process.pid, signal.SIGKILL)
                process.wait()
                code = 'timeout'
        row = dict(label=label, command=command, started=start,
                   seconds=time.time() - start, exit=code)
        events.append(row)
        with (output / 'events.jsonl').open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(row) + '\n')
        print(json.dumps(row), flush=True)
        return code

    try:
        run('identity', [node, '-p', 'JSON.stringify({platform:process.platform,arch:process.arch,versions:process.versions,config:process.config})'])
        run('source-status', [*git, 'status', '--short'])
        run('source-diff', [*git, 'diff', '--binary', 'HEAD'])
        run('source-base', [*git, 'rev-parse', 'HEAD'])
        (output / 'config.gypi').write_bytes((source / 'config.gypi').read_bytes())
        (output / 'artifact.json').write_text(json.dumps(dict(
            source=str(source), artifact=str(artifact), node=str(node),
            sha256=original, platform=sys.platform), indent=2), encoding='utf-8')
        code = run('doc-dependencies', [node, 'deps/npm/bin/npm-cli.js',
                                        'ci', '--prefix', 'tools/doc'])
        if code == 0:
            run('addon-doc-fixtures', [node, 'tools/doc/addon-verify.mjs',
                '--input', source / 'doc/api/addons.md',
                '--output', source / 'test/addons'])
        for group in ('test/addons', 'test/js-native-api', 'test/node-api',
                      'test/sqlite', 'test/ffi', 'benchmark/napi'):
            run('build-' + group.replace('/', '-'), [sys.executable,
                'tools/build_addons.py', group, '--out-dir', build,
                '--config', 'Release', '--loglevel', 'info'])
        if os.name != 'nt':
            run('build-embedding', ['ninja', '-C', build,
                                    '-j' + str(args.jobs), 'embedtest'])
            run('documentation', ['make', 'doc-only', 'JOBS=' + str(args.jobs)])
        assert (build / ('embedtest.exe' if os.name == 'nt' else 'embedtest')).is_file(), \
            'Embedding test executable must be built before the embedding suite'
        assert digest(node) == original, 'Fixture preparation changed Node'
        native = build / ('cctest.exe' if os.name == 'nt' else 'cctest')
        run('cctest', [native, '--gtest_output=xml:' + str(output / 'cctest.xml')])
        suites = ['default', 'pummel', 'addons', 'ffi', 'js-native-api',
                  'node-api', 'embedding', 'benchmark', 'sqlite', 'doctool']
        temporary = (['--temp-dir', str(args.test_temp_dir.resolve())]
                     if args.test_temp_dir else [])
        run('node-tests', [sys.executable, 'tools/test.py', '--mode=release',
             '--progress=tap', '--flaky-tests=run', '-j' + str(args.jobs),
             *temporary, *suites], timeout=10800)
    finally:
        tap_path = output / 'node-tests.log'
        tap = tap_path.read_text(encoding='utf-8', errors='replace') if tap_path.exists() else ''
        plan = re.findall(r'^1\.\.(\d+)$', tap, re.M)
        failures = re.findall(r'^not ok \d+ (.+)$', tap, re.M)
        unchanged = digest(node) == original and digest(artifact) == original
        passed = bool(plan) and unchanged and all(row['exit'] == 0 for row in events)
        result = dict(passed=passed, artifact_unchanged=unchanged,
                      plan=max(map(int, plan), default=0), failures=failures,
                      skips=len(re.findall(r'^(?:ok|not ok) \d+ [^\n]* # skip\b', tap, re.I | re.M)),
                      todos=len(re.findall(r'^(?:ok|not ok) \d+ [^\n]* # todo\b', tap, re.I | re.M)),
                      events=events,
                      scope='Native release suite selection; not all upstream configurations')
        (output / 'result.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    return 0 if passed else 1


if __name__ == '__main__':
    raise SystemExit(main())
