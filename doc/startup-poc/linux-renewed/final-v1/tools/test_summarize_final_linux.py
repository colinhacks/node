#!/usr/bin/env python3
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location(
    'summary', Path(__file__).with_name('summarize-final-linux.py'))
summary = importlib.util.module_from_spec(spec)
spec.loader.exec_module(summary)


class SummaryTest(unittest.TestCase):
    def fixture(self):
        pair = dict(left_artifact='a', right_artifact='b', paired_rounds=[0, 1],
                    median_ratio=2.0, bootstrap_95_ci_low=1.5, bootstrap_95_ci_high=2.5)
        report = dict(verdict='pass', failure_count=0, artifact_hash_failures=[],
                      rounds=2, warmups=1, config_sha256='config',
                      workloads={'empty': {'sha256': 'workload'}},
                      artifacts={a: {'sha256_before': a} for a in ('a', 'b')},
                      summaries={'empty': {
                          'samples': {'a': {'n': 2, 'median': 3}, 'b': {'n': 2, 'median': 1.5}},
                          'paired_ratios': {'a_over_b': pair}}})
        rows = [dict(status='ok', workload='empty', artifact=a, phase=phase,
                     round=i, metric_value=(i + 1) * (2 if a == 'a' else 1),
                     config_sha256='config', artifact_sha256=a, workload_sha256='workload')
                for phase, count in (('warmup', 1), ('measured', 2))
                for i in range(count) for a in ('a', 'b')]
        return report, rows

    def validate(self, report, rows):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'report.json').write_text(json.dumps(report))
            (root / 'raw.jsonl').write_text(''.join(json.dumps(row) + '\n' for row in rows))
            return summary.read_phase(root)

    def test_raw_reconstruction(self):
        self.assertEqual(self.validate(*self.fixture())['record_count'], 6)

    def test_missing_sample(self):
        report, rows = self.fixture()
        with self.assertRaises(AssertionError):
            self.validate(report, rows[:-1])

    def test_duplicate_round(self):
        report, rows = self.fixture()
        rows[-1] = copy.deepcopy(rows[-3])
        with self.assertRaises(AssertionError):
            self.validate(report, rows)

    def test_wrong_median(self):
        report, rows = self.fixture()
        report['summaries']['empty']['samples']['a']['median'] += .1
        with self.assertRaises(AssertionError):
            self.validate(report, rows)

    def test_mixed_artifact(self):
        report, rows = self.fixture()
        rows[-1]['artifact_sha256'] = 'wrong'
        with self.assertRaises(AssertionError):
            self.validate(report, rows)

    def test_reciprocal_interval(self):
        report, _ = self.fixture()
        item = report['summaries']['empty']
        self.assertEqual(summary.ratio(item, 'a', 'b'), (2, 1.5, 2.5))
        self.assertEqual(summary.ratio(item, 'b', 'a'), (.5, 1 / 2.5, 1 / 1.5))


if __name__ == '__main__':
    unittest.main()
