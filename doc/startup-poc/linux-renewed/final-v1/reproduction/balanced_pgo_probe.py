#!/usr/bin/env python3
"""Create a balanced Linux LLVM PGO profile and held-out native gate plans.

This is a measurement input generator, not a build driver.  It never changes a
source checkout or an executable.  ``train`` runs only an instrumented binary
and writes a frozen ``node.profdata``.  After a separately-built PGO-use binary
exists, ``gate`` writes and runs interleaved held-out startup and throughput
comparisons through the existing native paired-benchmark runner.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import time


SEED = 20260909
STARTUP_TRAINING = (
    ('eval-empty', ('-e', '')),
    ('empty-cjs', ('__EMPTY_CJS__',)),
    ('empty-mjs', ('__EMPTY_MJS__',)),
)
STARTUP_REPETITIONS = 12
PGO_DURATION_MS = '15000'
STEADY_REPETITIONS = 4


def sha256(path: Path) -> str:
  digest = hashlib.sha256()
  with path.open('rb') as source:
    for chunk in iter(lambda: source.read(1024 * 1024), b''):
      digest.update(chunk)
  return digest.hexdigest()


def executable(value: str) -> Path:
  path = Path(value).expanduser().resolve()
  if not path.is_file() or not os.access(path, os.X_OK):
    raise argparse.ArgumentTypeError(f'must be an executable file: {value}')
  return path


def existing_dir(value: str) -> Path:
  path = Path(value).expanduser().resolve()
  if not path.is_dir():
    raise argparse.ArgumentTypeError(f'must be a directory: {value}')
  return path


def existing_file(value: str) -> Path:
  path = Path(value).expanduser().resolve()
  if not path.is_file():
    raise argparse.ArgumentTypeError(f'must be a file: {value}')
  return path


def empty_output(value: str) -> Path:
  path = Path(value).expanduser().resolve()
  if path.exists():
    raise argparse.ArgumentTypeError(f'must not already exist: {path}')
  return path


def sanitized_environment(profile_pattern: str | None = None) -> tuple[dict[str, str], list[str]]:
  environment = dict(os.environ)
  removed = sorted(key for key in environment if key.startswith(('NODE_', '__NUB_')))
  for key in removed:
    environment.pop(key)
  environment.update(NO_COLOR='1', FORCE_COLOR='0', TZ='UTC')
  if profile_pattern is not None:
    environment['LLVM_PROFILE_FILE'] = profile_pattern
  return environment, removed


def command_record(command: list[str], cwd: Path, environment: dict[str, str], log: Path) -> dict:
  started = time.monotonic()
  result = subprocess.run(command, cwd=cwd, env=environment, stdin=subprocess.DEVNULL,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                          timeout=240, check=False)
  log.write_text('$ ' + ' '.join(map(str, command)) + '\n\n[stdout]\n' + result.stdout +
                 '\n[stderr]\n' + result.stderr + f'\n[exit={result.returncode}]\n')
  record = {'command': command, 'cwd': str(cwd), 'exit': result.returncode,
            'seconds': round(time.monotonic() - started, 3), 'log': str(log),
            'log_sha256': sha256(log)}
  if result.returncode:
    raise RuntimeError(f'training command failed: {log}')
  if 'LLVM Profile Error:' in result.stderr:
    raise RuntimeError(f'profile runtime reported an error: {log}')
  return record


def git_identity(source: Path) -> dict:
  result = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=source, capture_output=True,
                          text=True, check=False)
  if result.returncode:
    raise ValueError(f'not a Git checkout: {source}')
  status = subprocess.run(['git', 'status', '--porcelain'], cwd=source, capture_output=True,
                          text=True, check=False)
  if status.returncode or status.stdout:
    raise ValueError(f'training source must be clean: {source}')
  return {'path': str(source), 'head': result.stdout.strip()}


def training_cases(source: Path, fixtures: Path) -> list[tuple[str, list[str]]]:
  fixtures.mkdir()
  empty_cjs = fixtures / 'empty.cjs'
  empty_mjs = fixtures / 'empty.mjs'
  empty_cjs.write_bytes(b'')
  empty_mjs.write_bytes(b'')
  cases: list[tuple[str, list[str]]] = []
  for repeat in range(STARTUP_REPETITIONS):
    for name, args in STARTUP_TRAINING:
      actual = [str(empty_cjs) if item == '__EMPTY_CJS__' else str(empty_mjs) if item == '__EMPTY_MJS__' else item for item in args]
      cases.append((f'startup-{name}-{repeat:02d}', actual))
  scripts = sorted(path for path in (source / 'tools' / 'pgo').glob('pgo-*.js')
                   if path.name != 'pgo-run-all.js')
  if len(scripts) != 11:
    raise ValueError(f'expected 11 checked-in PGO scripts, found {len(scripts)}')
  cases.extend((f'pgo-{script.stem}', [str(script)]) for script in scripts)
  benchmark = source / 'benchmark' / 'run.js'
  if not benchmark.is_file():
    raise ValueError('source lacks benchmark/run.js')
  # Deliberately different from the held-out gate inputs below. These values
  # are declared benchmark dimensions, so profile collection cannot depend on
  # permissive command-line override behavior.
  for repeat in range(STEADY_REPETITIONS):
    cases.append((f'buffer-profile-{repeat:02d}', [str(benchmark), '--format', 'csv', '--filter', 'buffer-from.js', '--set', 'source=array', '--set', 'len=100', '--set', 'n=800000', 'buffers']))
    cases.append((f'decode-profile-{repeat:02d}', [str(benchmark), '--format', 'csv', '--filter', 'text-decoder.js', '--set', 'encoding=windows-1252', '--set', 'ignoreBOM=0', '--set', 'fatal=0', '--set', 'type=Buffer', '--set', 'content=one-byte-string', '--set', 'len=256', '--set', 'n=1000', 'util']))
  return cases


def train(args: argparse.Namespace) -> int:
  output = args.output
  output.mkdir(parents=True)
  raw = output / 'raw'
  logs = output / 'logs'
  raw.mkdir(); logs.mkdir()
  identity = git_identity(args.source)
  profile_pattern = str(raw / '%m-%p.profraw')
  environment, removed = sanitized_environment(profile_pattern)
  cases = training_cases(args.source, output / 'fixtures')
  report = {'schema': 1, 'kind': 'balanced-linux-llvm-pgo-training', 'seed': SEED,
            'source': identity, 'instrumented_node': {'path': str(args.node), 'sha256': sha256(args.node)},
            'llvm_profdata': {'path': str(args.llvm_profdata), 'sha256': sha256(args.llvm_profdata)},
            'environment_removed': removed, 'profile_pattern': profile_pattern,
            'policy': {'startup_repetitions': STARTUP_REPETITIONS, 'pgo_duration_ms': PGO_DURATION_MS,
                       'steady_repetitions': STEADY_REPETITIONS,
                       'training_buffer': 'array/100/800000', 'training_decoder': 'windows-1252/256/1000'},
            'cases': [], 'status': 'running'}
  try:
    for index, (name, invocation) in enumerate(cases):
      log = logs / f'{index:03d}-{name}.log'
      case_environment = dict(environment)
      if name.startswith('pgo-'):
        case_environment['PGO_TRAINING_DURATION'] = PGO_DURATION_MS
      report['cases'].append({'name': name, **command_record([str(args.node), *invocation], args.source, case_environment, log)})
    profiles = sorted(raw.glob('*.profraw'))
    if not profiles or any(path.stat().st_size == 0 for path in profiles):
      raise RuntimeError('training did not create nonempty raw profiles')
    profile = output / 'node.profdata'
    merged = subprocess.run([str(args.llvm_profdata), 'merge', '-o', str(profile), *map(str, profiles)],
                            stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=240, check=False)
    merge_log = logs / 'merge.log'
    merge_log.write_text('$ ' + ' '.join([str(args.llvm_profdata), 'merge', '-o', str(profile), *map(str, profiles)]) + '\n\n[stdout]\n' + merged.stdout + '\n[stderr]\n' + merged.stderr + f'\n[exit={merged.returncode}]\n')
    if merged.returncode or not profile.is_file() or profile.stat().st_size == 0:
      raise RuntimeError(f'profile merge failed: {merge_log}')
    report.update(status='pass', raw_profiles=[{'path': str(path), 'sha256': sha256(path), 'bytes': path.stat().st_size} for path in profiles], profile={'path': str(profile), 'sha256': sha256(profile), 'bytes': profile.stat().st_size}, merge_log={'path': str(merge_log), 'sha256': sha256(merge_log)})
  except BaseException as error:
    report.update(status='fail', error=str(error))
    (output / 'report.json').write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
    raise
  (output / 'report.json').write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
  print(profile)
  return 0


def gate_configs(source: Path, control: Path, candidate: Path) -> tuple[dict, dict]:
  artifacts = {'source-control': str(control), 'pgo-use': str(candidate)}
  startup = [
      ('help', ['--help']),
      ('first-intl', ['-e', "require('node:assert/strict').equal(new Intl.DateTimeFormat('en-US',{timeZone:'UTC',year:'numeric'}).format(0),'1970')"]),
      ('first-windows1252', ['-e', "require('node:assert/strict').equal(new TextDecoder('windows-1252').decode(Uint8Array.of(128)),String.fromCodePoint(8364))"]),
      ('worker', ['-e', "const {Worker}=require('node:worker_threads');const w=new Worker('require(\"node:worker_threads\").parentPort.postMessage(42)',{eval:true});w.once('message',v=>{require('node:assert/strict').equal(v,42);w.terminate()})"]),
      ('http-ready', ['-e', "const s=require('node:http').createServer();s.listen(0,'127.0.0.1',()=>{require('node:assert/strict').ok(s.address().port>0);s.close()})"]),
  ]
  startup_config = {'schema': 1, 'artifacts': artifacts, 'seed': SEED ^ 0x51A7, 'warmups': 10, 'rounds': 350, 'timeout_seconds': 60,
                    'workloads': [dict(name=name, argv=argv, cwd=str(source), metric={'kind': 'process-lifetime'}) for name, argv in startup]}
  benchmark = source / 'benchmark' / 'run.js'
  throughput = [
      ('buffer-from-heldout', 'buffers/buffer-from.js', ['source=array', 'len=2048', 'n=800000']),
      ('decode-windows1252-heldout', 'util/text-decoder.js', ['encoding=windows-1252', 'ignoreBOM=0', 'fatal=0', 'type=Buffer', 'content=one-byte-string', 'len=16384', 'n=10000']),
  ]
  throughput_config = {'schema': 1, 'artifacts': artifacts, 'seed': SEED ^ 0xBEEF, 'warmups': 3, 'rounds': 30, 'timeout_seconds': 180,
                       'workloads': [dict(name=name, argv=[str(benchmark), '--format', 'csv', '--filter', Path(relative).name, *[part for setting in settings for part in ('--set', setting)], relative.split('/')[0]], cwd=str(source), metric={'kind': 'node-csv-throughput', 'expected_filename': relative}) for name, relative, settings in throughput]}
  return startup_config, throughput_config


def paired_ratio(summary: dict, metric_kind: str) -> dict:
  if not summary:
    raise ValueError('missing workload summary')
  if summary.get('metric_kind') != metric_kind:
    raise ValueError(f'expected {metric_kind} metric, got {summary.get("metric_kind")!r}')
  for ratio in summary.get('paired_ratios', {}).values():
    if ratio and ratio.get('left_artifact') == 'pgo-use' and ratio.get('right_artifact') == 'source-control':
      return ratio
  raise ValueError('missing pgo-use/source-control paired ratio')


def evaluate_gate_reports(startup_report: dict, throughput_report: dict) -> dict:
  """Apply the declared directional screening criteria to paired-bench reports."""
  criteria = {
      'startup': ('process-lifetime', ('help', 'first-intl', 'first-windows1252', 'worker', 'http-ready')),
      'throughput': ('node-csv-throughput', ('buffer-from-heldout', 'decode-windows1252-heldout')),
  }
  reports = {'startup': startup_report, 'throughput': throughput_report}
  evaluations = []
  for group, (metric_kind, names) in criteria.items():
    report = reports[group]
    report_ok = report.get('verdict') == 'pass'
    for name in names:
      evaluation = {'group': group, 'workload': name, 'report_verdict': report.get('verdict')}
      try:
        ratio = paired_ratio(report.get('summaries', {}).get(name, {}), metric_kind)
        evaluation['ratio'] = ratio
        if group == 'startup':
          accepted = ratio['median_ratio'] < 1 and ratio['bootstrap_95_ci_high'] < 1
          evaluation['criterion'] = 'median < 1 and upper_95_ci < 1'
        else:
          accepted = ratio['median_ratio'] >= .95 and ratio['bootstrap_95_ci_low'] >= .90
          evaluation['criterion'] = 'median >= .95 and lower_95_ci >= .90'
        evaluation['accepted'] = bool(report_ok and accepted)
      except (KeyError, TypeError, ValueError) as error:
        evaluation.update(accepted=False, error=str(error))
      evaluations.append(evaluation)
  return {'verdict': 'pass' if all(item['accepted'] for item in evaluations) else 'reject',
          'evaluations': evaluations}


def gate(args: argparse.Namespace) -> int:
  output = args.output
  output.mkdir(parents=True)
  identity = git_identity(args.source)
  startup, throughput = gate_configs(args.source, args.source_control, args.pgo_use)
  manifest = {'schema': 1, 'kind': 'balanced-linux-llvm-pgo-heldout-gate', 'source': identity,
              'source_control': {'path': str(args.source_control), 'sha256': sha256(args.source_control)},
              'pgo_use': {'path': str(args.pgo_use), 'sha256': sha256(args.pgo_use)},
              'held_out_from_training': {'startup': [item['name'] for item in startup['workloads']], 'throughput': [item['name'] for item in throughput['workloads']]},
              'acceptance': {'startup': 'pgo-use/source-control median latency ratio < 1 with upper 95% CI < 1 for every workload', 'throughput': 'pgo-use/source-control median rate ratio >= 0.95 and lower 95% CI >= 0.90 for both workloads; otherwise reject the profile'},
              'scope': 'PGO-only comparison. Build both artifacts from the same clean source tree, toolchain, and configure options; the candidate differs only by --enable-pgo-use and --pgo-profile.'}
  for name, config in (('startup.json', startup), ('throughput.json', throughput)):
    (output / name).write_text(json.dumps(config, indent=2, sort_keys=True) + '\n')
  for label in ('startup', 'throughput'):
    result = subprocess.run([sys.executable, str(args.paired_bench), '--config', str(output / f'{label}.json'), '--output', str(output / label)], check=False)
    if result.returncode:
      manifest['screening'] = {'verdict': 'runner-failed', 'failed_group': label}
      (output / 'manifest.json').write_text(json.dumps(manifest, indent=2, sort_keys=True) + '\n')
      return 1
  startup_report = json.loads((output / 'startup' / 'report.json').read_text())
  throughput_report = json.loads((output / 'throughput' / 'report.json').read_text())
  manifest['reports'] = {label: {'path': str(output / label / 'report.json'),
                                 'sha256': sha256(output / label / 'report.json')}
                         for label in ('startup', 'throughput')}
  manifest['screening'] = evaluate_gate_reports(startup_report, throughput_report)
  (output / 'manifest.json').write_text(json.dumps(manifest, indent=2, sort_keys=True) + '\n')
  print(output / 'manifest.json')
  return 0 if manifest['screening']['verdict'] == 'pass' else 1


def verify_graph(args: argparse.Namespace) -> int:
  """Check a configured Ninja graph before spending time on a full build."""
  config = ast.literal_eval(args.config.read_text())
  variables = config.get('variables') if isinstance(config, dict) else None
  if not isinstance(variables, dict):
    raise ValueError(f'invalid config.gypi: {args.config}')
  commands = args.commands.read_text()
  expected = {'enable_pgo_generate': 'true', 'enable_pgo_use': 'false'}
  if args.graph_phase == 'use':
    expected = {'enable_pgo_generate': 'false', 'enable_pgo_use': 'true'}
  actual = {key: variables.get(key) for key in expected}
  if actual != expected:
    raise ValueError(f'PGO config flags differ: expected {expected}, got {actual}')
  if '-flto' in commands:
    raise ValueError('PGO-only graph unexpectedly contains an LTO flag')
  if args.graph_phase == 'generate':
    if '-fprofile-generate' not in commands or '-fprofile-update=atomic' not in commands:
      raise ValueError('instrumented graph lacks required LLVM profile-generate flags')
    if '-fprofile-use=' in commands:
      raise ValueError('instrumented graph unexpectedly consumes a profile')
  else:
    profile = str(args.profile.resolve())
    configured = variables.get('node_pgo_profile')
    try:
      configured_paths = shlex.split(configured)
    except (TypeError, ValueError) as error:
      raise ValueError('config.gypi has an invalid quoted profile path') from error
    if len(configured_paths) != 1 or configured_paths[0].replace('$$', '$') != profile:
      raise ValueError('config.gypi does not retain the supplied absolute profile path')
    if ('-fprofile-use=' not in commands or
        (profile not in commands and profile.replace('$', '$$') not in commands)):
      raise ValueError('PGO-use graph lacks the supplied LLVM profile flag')
    if '-fprofile-generate' in commands:
      raise ValueError('PGO-use graph unexpectedly contains instrumentation flags')
  report = {'schema': 1, 'phase': args.graph_phase, 'config': {'path': str(args.config), 'sha256': sha256(args.config)},
            'commands': {'path': str(args.commands), 'sha256': sha256(args.commands)}, 'variables': actual,
            'profile': None if args.graph_phase == 'generate' else {'path': str(args.profile), 'sha256': sha256(args.profile)},
            'verdict': 'pass'}
  args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
  print(args.output)
  return 0


def main() -> int:
  parser = argparse.ArgumentParser(description=__doc__)
  subparsers = parser.add_subparsers(dest='phase', required=True)
  training = subparsers.add_parser('train')
  training.add_argument('--source', type=existing_dir, required=True)
  training.add_argument('--node', type=executable, required=True)
  training.add_argument('--llvm-profdata', type=executable, required=True)
  training.add_argument('--output', type=empty_output, required=True)
  gate_parser = subparsers.add_parser('gate')
  gate_parser.add_argument('--source', type=existing_dir, required=True)
  gate_parser.add_argument('--source-control', type=executable, required=True)
  gate_parser.add_argument('--pgo-use', type=executable, required=True)
  gate_parser.add_argument('--paired-bench', type=existing_file, required=True)
  gate_parser.add_argument('--output', type=empty_output, required=True)
  graph = subparsers.add_parser('verify-graph')
  graph.add_argument('--graph-phase', choices=('generate', 'use'), required=True)
  graph.add_argument('--config', type=existing_file, required=True)
  graph.add_argument('--commands', type=existing_file, required=True)
  graph.add_argument('--profile', type=existing_file)
  graph.add_argument('--output', type=empty_output, required=True)
  args = parser.parse_args()
  if args.phase == 'train':
    return train(args)
  if args.phase == 'gate':
    return gate(args)
  if args.graph_phase == 'use' and args.profile is None:
    parser.error('--profile is required for --graph-phase=use')
  if args.graph_phase == 'generate' and args.profile is not None:
    parser.error('--profile is valid only for --graph-phase=use')
  return verify_graph(args)


if __name__ == '__main__':
  raise SystemExit(main())
