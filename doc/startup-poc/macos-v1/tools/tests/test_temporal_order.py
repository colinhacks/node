from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from startup_order import TextSymbol, parse_nm_text
import temporal_order


class TemporalOrderTest(unittest.TestCase):
    def test_preserves_actual_order_comments_and_exact_prefix(self):
        output, audit = temporal_order.map_temporal_order(
            "# tool comment\n_z\na\n", [TextSymbol(1, "_a"), TextSymbol(2, "__z")])
        self.assertEqual(output, "# tool comment\n__z\n_a\n")
        self.assertEqual([row["address"] for row in audit], [2, 1])

    def test_rejects_ambiguous_names_aliases_data_and_undefined_symbols(self):
        symbols = parse_nm_text("10 T _a\n10 T _alias\n20 t _dup\n30 t _dup\n"
                                "40 D _data\n U _undefined\n")
        output, audit = temporal_order.map_temporal_order(
            "a\nalias\ndup\ndata\nundefined\n", symbols)
        self.assertEqual(output, "_a\n")
        self.assertEqual([row["disposition"] for row in audit],
                         ["accepted", "alias-address", "symbol-collision",
                          "missing-text-symbol", "missing-text-symbol"])

    def test_duplicate_profile_names_are_all_omitted(self):
        output, audit = temporal_order.map_temporal_order(
            "# one.cc\nlocal\n# two.cc\nlocal\n", [TextSymbol(1, "_local")])
        self.assertEqual(output, "# one.cc\n# two.cc\n")
        self.assertTrue(all(row["disposition"] == "duplicate-profile-name" for row in audit))

    def test_does_not_strip_source_qualifiers_or_guess_underscores(self):
        output, audit = temporal_order.map_temporal_order(
            "src.cc;fn\n_fn\n", [TextSymbol(1, "_fn")])
        self.assertEqual(output, "\n")
        self.assertTrue(all(row["disposition"] == "missing-text-symbol" for row in audit))

    def test_rejects_malformed_or_empty_input(self):
        for raw in ("# only comment\n", "one two", "file.o:name", "name # inline", "a\0b"):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                temporal_order.map_temporal_order(raw, [])

    def test_requires_nonzero_temporal_counts(self):
        self.assertEqual(temporal_order.temporal_counts(
            "Temporal Profile Traces (samples=811 seen=811)"),
            {"samples": 811, "seen": 811})
        for raw in ("no traces", "Temporal Profile Traces (samples=0 seen=1)",
                    "Temporal Profile Traces (samples=1 seen=0)"):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                temporal_order.temporal_counts(raw)


if __name__ == "__main__":
    unittest.main()
