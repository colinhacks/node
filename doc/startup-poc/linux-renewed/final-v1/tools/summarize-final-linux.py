#!/usr/bin/env python3
"""Validate retained raw samples and emit final Linux comparison tables."""
import argparse
import hashlib
import json
from pathlib import Path
import statistics


def identity(path):
    with path.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    return dict(bytes=path.stat().st_size, sha256=digest)


def read_phase(directory):
    report = json.loads((directory / 'report.json').read_text())
    assert report['verdict'] == 'pass' and report['failure_count'] == 0
    assert not report['artifact_hash_failures']
    rows = [json.loads(line) for line in (directory / 'raw.jsonl').read_text().splitlines()]
    assert all(row['status'] == 'ok' for row in rows)
    expected = (report['rounds'] + report['warmups']) * len(report['workloads']) * len(report['artifacts'])
    assert len(rows) == expected, (directory, len(rows), expected)
    groups = {}
    for row in rows:
        name, artifact, phase = row['workload'], row['artifact'], row['phase']
        assert row['config_sha256'] == report['config_sha256']
        assert row['artifact_sha256'] == report['artifacts'][artifact]['sha256_before']
        assert row['workload_sha256'] == report['workloads'][name]['sha256']
        group = groups.setdefault((name, artifact, phase), {})
        assert row['round'] not in group
        group[row['round']] = row['metric_value']
    for name, summary in report['summaries'].items():
        for artifact, sample in summary['samples'].items():
            values = groups[name, artifact, 'measured']
            assert set(values) == set(range(report['rounds']))
            assert sample['n'] == report['rounds']
            assert sample['median'] == statistics.median(values.values())
            assert set(groups[name, artifact, 'warmup']) == set(range(report['warmups']))
        for pair in summary['paired_ratios'].values():
            left = groups[name, pair['left_artifact'], 'measured']
            right = groups[name, pair['right_artifact'], 'measured']
            assert pair['paired_rounds'] == list(range(report['rounds']))
            assert pair['median_ratio'] == statistics.median(left[i] / right[i] for i in left)
    return dict(report=report, raw_identity=identity(directory / 'raw.jsonl'),
                report_identity=identity(directory / 'report.json'), record_count=len(rows))


def ratio(summary, left, right):
    for pair in summary['paired_ratios'].values():
        low, high = pair['bootstrap_95_ci_low'], pair['bootstrap_95_ci_high']
        if (pair['left_artifact'], pair['right_artifact']) == (left, right):
            return pair['median_ratio'], low, high
        if (pair['left_artifact'], pair['right_artifact']) == (right, left):
            # Reciprocal presentation of the stored paired-ratio estimator.
            return 1 / pair['median_ratio'], 1 / high, 1 / low
    raise ValueError((left, right))


def formatted(values):
    middle, low, high = values
    return f'{middle:.4f} [{low:.4f}, {high:.4f}]'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--matrix', type=Path, required=True)
    parser.add_argument('--memory', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = {'schema': 1, 'phases': {}}
    for name in ('identity-control', 'startup', 'throughput'):
        result['phases'][name] = read_phase(args.matrix / 'comparison' / name)
    result['phases']['references'] = read_phase(args.matrix / 'release-references')
    events = json.loads((args.matrix / 'events.json').read_text())
    assert [event['label'] for event in events] == ['comparison', 'first-js', 'release-references']
    assert all(event['exit'] == 0 for event in events)
    first = json.loads((args.matrix / 'first-js/summary.json').read_text())
    assert first['verdict'] == 'pass' and first['samples_complete'] and first['positive_control_pass']
    memory = json.loads((args.memory / 'report.json').read_text())
    assert memory['summary']['failures'] == 0 and not memory['artifact_mutations']
    assert len(memory['records']) == 7 * 4 * 50
    assert memory['artifacts']['baseline__identity']['sha256_before'] == memory['artifacts']['baseline']['sha256_before']
    memory_groups = {}
    for row in memory['records']:
        key = row['artifact'], row['workload']
        rounds = memory_groups.setdefault(key, set())
        assert row['round'] not in rounds
        rounds.add(row['round'])
    assert len(memory_groups) == 7 * 4
    assert all(rounds == set(range(50)) for rounds in memory_groups.values())
    result.update(events=events, first_js=first, memory_summary=memory['summary'],
                  first_js_identity=identity(args.matrix / 'first-js/summary.json'),
                  memory_identity=identity(args.memory / 'report.json'))
    # The comparison uses one immutable artifact per label across all phases.
    canonical = result['phases']['startup']['report']['artifacts']
    for phase in ('throughput', 'references'):
        for label, artifact in canonical.items():
            actual = result['phases'][phase]['report']['artifacts'][label]
            assert actual['sha256_before'] == artifact['sha256_before'] == actual['sha256_after']
    for label, artifact in canonical.items():
        assert first['artifacts'][label]['sha256_before'] == artifact['sha256_before']
        assert memory['artifacts'][label]['sha256_before'] == artifact['sha256_before']

    lines = ['# Final Linux measurement tables', '',
             'Ratios are paired estimates with 95% bootstrap intervals. Each phase uses its own randomized rounds; margins are not multiplied.', '']
    arms = ['source-control', 'combined-normal', 'pristine-pgo', 'combined-pgo', 'combined-thin-pgo']
    for phase, title in (('startup', 'Startup speedup versus pristine normal'),
                         ('throughput', 'Throughput ratio versus pristine normal')):
        lines += [f'## {title}', '', '| Workload | ' + ' | '.join(arms) + ' |',
                  '| --- | ' + ' | '.join(['---'] * len(arms)) + ' |']
        for name, summary in result['phases'][phase]['report']['summaries'].items():
            values = [ratio(summary, 'baseline', arm) if phase == 'startup'
                      else ratio(summary, arm, 'baseline') for arm in arms]
            lines.append('| ' + name + ' | ' + ' | '.join(map(formatted, values)) + ' |')
        lines.append('')
    for phase in ('startup', 'throughput'):
        pairs = [('combined-normal', 'source-control'), ('combined-pgo', 'combined-normal'),
                 ('combined-pgo', 'pristine-pgo'), ('combined-thin-pgo', 'combined-pgo')]
        lines += [f'## {phase.capitalize()} incremental ratios', '',
                  'Higher means faster. Reciprocal rows invert the stored estimator and its interval.', '',
                  '| Workload | New source / frozen source | PGO / normal | Fork PGO / pristine PGO | Thin PGO / PGO |',
                  '| --- | --- | --- | --- | --- |']
        for name, summary in result['phases'][phase]['report']['summaries'].items():
            values = [ratio(summary, reference, candidate) if phase == 'startup'
                      else ratio(summary, candidate, reference) for candidate, reference in pairs]
            lines.append('| ' + name + ' | ' + ' | '.join(map(formatted, values)) + ' |')
        lines.append('')
    reference = result['phases']['references']['report']
    labels = list(reference['artifacts'])
    lines += ['## Release reference medians in milliseconds', '',
              '| Workload | ' + ' | '.join(labels) + ' |',
              '| --- | ' + ' | '.join(['---'] * len(labels)) + ' |']
    for name, summary in reference['summaries'].items():
        lines.append('| ' + name + ' | ' + ' | '.join(f"{summary['samples'][label]['median']:.3f}" for label in labels) + ' |')
    lines += ['', '## First JavaScript speedup versus pristine normal', '',
              '| Workload | ' + ' | '.join(arms) + ' |',
              '| --- | ' + ' | '.join(['---'] * len(arms)) + ' |']
    for name, item in first['summaries'].items():
        lines.append('| ' + name + ' | ' + ' | '.join(formatted(ratio(item['first_js_ms'], 'baseline', arm)) for arm in arms) + ' |')
    lines += ['', '## Peak RSS medians in KiB', '',
              '| Workload | baseline | ' + ' | '.join(arms) + ' |',
              '| --- | --- | ' + ' | '.join(['---'] * len(arms)) + ' |']
    for name, item in memory['summary']['workloads'].items():
        lines.append('| ' + name + ' | ' + ' | '.join(str(item[arm]['median_peak_rss_kib']) for arm in ['baseline'] + arms) + ' |')
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output / 'RESULTS.json').write_text(json.dumps(result, indent=2, sort_keys=True) + '\n')
    (args.output / 'TABLES.md').write_text('\n'.join(lines) + '\n')
    print(json.dumps({name: phase['record_count'] for name, phase in result['phases'].items()}))


if __name__ == '__main__':
    main()
