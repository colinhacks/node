import gzip
import json
from pathlib import Path
import tempfile
import unittest

from replay_recorded import first_js


class FirstJavaScriptReplayTest(unittest.TestCase):
    def check(self, mutation=None):
        summaries = {case: {metric: {'samples': {'baseline': {'median': 1.0}}}
                           for metric in ('first_js_ms', 'process_lifetime_ms', 'total_ms')}
                     for case in ('cjs', 'esm', 'eval')}
        summary = dict(rounds=1, warmups=1, busywait_ns=25000000,
                       artifacts={'baseline': {'sha256_before': 'recorded'}}, summaries=summaries)
        rows = [dict(artifact='baseline', artifact_sha256='recorded', status='ok', exit_code=0,
                     case='positive_delay', phase='preflight', round=0, positive_busywait_ns=25000000)]
        for case in summaries:
            for phase in ('measured', 'warmup'):
                rows.append(dict(artifact='baseline', artifact_sha256='recorded', status='ok', exit_code=0,
                                 case=case, phase=phase, round=0, first_js_ms=1.0,
                                 process_lifetime_ms=1.0, total_ms=1.0))
        if mutation:
            mutation(summary, rows)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'first-js').mkdir()
            (root / 'first-js/summary.json.gz').write_bytes(gzip.compress(json.dumps(summary).encode()))
            (root / 'first-js/raw.jsonl.gz').write_bytes(gzip.compress(
                ('\n'.join(map(json.dumps, rows)) + '\n').encode()))
            return first_js(root)

    def test_valid_records(self):
        self.assertEqual(self.check(), 7)

    def test_rejects_corrupt_records(self):
        mutations = (
            lambda summary, rows: rows.append(rows[-1]),
            lambda summary, rows: rows.pop(),
            lambda summary, rows: rows[1].update(artifact_sha256='changed'),
            lambda summary, rows: rows[1].update(first_js_ms=2.0),
            lambda summary, rows: rows[0].update(positive_busywait_ns=1),
            lambda summary, rows: rows[1].update(status='failed'),
        )
        for index, mutation in enumerate(mutations):
            with self.subTest(index=index), self.assertRaises(AssertionError):
                self.check(mutation)
