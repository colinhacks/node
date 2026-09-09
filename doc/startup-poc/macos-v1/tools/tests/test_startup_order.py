from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import startup_order


class StartupOrderTest(unittest.TestCase):
    def test_parses_profile_records_and_uses_maximum_block_count(self):
        functions = startup_order.parse_profdata_show("""Counters:
  path/a.cc;_hot:
    Hash: 1
    Counters: 2
    Block counts: [3, 17]
  _cold:
    Hash: 2
    Counters: 1
    Block counts: [0]
""")
        self.assertEqual(functions, [startup_order.ProfileFunction("path/a.cc;_hot", 17),
                                     startup_order.ProfileFunction("_cold", 0)])

    def test_profile_without_block_counts_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "no function block counts"):
            startup_order.parse_profdata_show("Counters:\n  _missing:\n    Hash: 1\n")

    def test_nm_parser_retains_only_defined_text_symbols(self):
        symbols = startup_order.parse_nm_text("""0000000100000000 T __hot
0000000100000004 t _local
                 U __external
0000000100000008 D _data
""")
        self.assertEqual(symbols, [startup_order.TextSymbol(0x100000000, "__hot"),
                                   startup_order.TextSymbol(0x100000004, "_local")])

    def test_exact_macho_prefix_mapping_and_source_qualifier(self):
        functions = [startup_order.ProfileFunction("src/a.cc;_hot", 8)]
        symbols = [startup_order.TextSymbol(0x10, "__hot")]
        matches, omissions = startup_order.map_functions(functions, symbols)
        self.assertEqual(omissions, [])
        self.assertEqual(matches[0].emitted_symbol, "__hot")
        self.assertEqual(matches[0].source_qualifier, "src/a.cc")
        self.assertEqual(matches[0].rank, 1)

    def test_collisions_are_omitted_not_arbitrarily_chosen(self):
        functions = [startup_order.ProfileFunction("_hot", 8)]
        symbols = [startup_order.TextSymbol(0x10, "__hot"),
                   startup_order.TextSymbol(0x20, "__hot")]
        matches, omissions = startup_order.map_functions(functions, symbols)
        self.assertEqual(matches, [])
        self.assertEqual(omissions[0].reason, "symbol-collision")

    def test_same_address_alias_is_omitted_after_highest_score(self):
        functions = [startup_order.ProfileFunction("_a", 2),
                     startup_order.ProfileFunction("_b", 9)]
        symbols = [startup_order.TextSymbol(0x10, "__a"),
                   startup_order.TextSymbol(0x10, "__b")]
        matches, omissions = startup_order.map_functions(functions, symbols)
        self.assertEqual([match.emitted_symbol for match in matches], ["__b"])
        self.assertEqual(omissions[0].reason, "alias-address")
        self.assertEqual(omissions[0].profile_name, "_a")

    def test_zero_and_missing_symbols_are_audited(self):
        functions = [startup_order.ProfileFunction("_zero", 0),
                     startup_order.ProfileFunction("_missing", 3)]
        matches, omissions = startup_order.map_functions(functions, [])
        self.assertEqual(matches, [])
        self.assertEqual([(item.profile_name, item.reason) for item in omissions],
                         [("_missing", "missing-symbol"), ("_zero", "zero-score")])

    def test_order_file_records_final_not_temporary_output_path(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            provenance = {"inputs": {"binary": {"sha256": "binary"},
                                     "profile": {"sha256": "profile"}}}
            path = root / "temporary" / "startup-order-64.txt"
            path.parent.mkdir()
            record = startup_order.write_order_file(
                path, [startup_order.Match("_a", "", 1, 1, "__a", 1)], 64,
                provenance)
            self.assertEqual(record["selected"], 1)
            self.assertIn("__a", path.read_text())

    def test_artifact_manifest_uses_final_directory_after_atomic_rename(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            profile = root / "profile.profdata"
            binary = root / "node"
            tool = root / "llvm-profdata"
            nm = root / "nm"
            for path in (profile, binary, tool, nm):
                path.write_bytes(b"input")
            output = root / "orders"

            def command_output(command):
                if command[1] == "show":
                    return "  _hot:\n    Block counts: [4, 9]\n"
                return "0000000100000000 T __hot\n"

            with patch.object(startup_order, "run_command", side_effect=command_output):
                report = startup_order.create_order_artifacts(profile, binary, tool, nm, output)
            self.assertEqual(report["orders"]["64"]["path"],
                             str(output.resolve() / "startup-order-64.txt"))
            self.assertTrue((output / "report.json").is_file())


if __name__ == "__main__":
    unittest.main()
