import importlib.util
from pathlib import Path
import unittest


ROOT = Path(__file__).parents[1]
SPEC = importlib.util.spec_from_file_location(
    "parser_modbus_under_test", ROOT / "solarmodbus" / "parser_modbus.py"
)
PARSER_MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PARSER_MODULE)
ModbusValueParser = PARSER_MODULE.ModbusValueParser


class ModbusValueParserTests(unittest.TestCase):
    def setUp(self):
        self.parser = ModbusValueParser({})

    def parse(self, values, rule, scale=1):
        registers = list(range(100, 100 + len(values)))
        item = {
            "name": "Test value",
            "registers": registers,
            "rule": rule,
            "scale": scale,
        }
        raw_registers = dict(zip(registers, values))
        return self.parser.parse_item(item, raw_registers)

    def test_rule_1_decodes_unsigned_16_bit_value(self):
        self.assertEqual(self.parse([0x1234], rule=1), 0x1234)

    def test_rule_2_decodes_signed_16_bit_values(self):
        self.assertEqual(self.parse([100], rule=2), 100)
        self.assertEqual(self.parse([0xFFFF], rule=2), -1)

    def test_rule_1_decodes_all_words_low_word_first(self):
        self.assertEqual(self.parse([0x5678, 0x1234], rule=1), 0x12345678)

    def test_rule_3_decodes_unsigned_32_bit_value_low_word_first(self):
        self.assertEqual(self.parse([0x5678, 0x1234], rule=3), 0x12345678)

    def test_rule_4_decodes_signed_32_bit_values_low_word_first(self):
        self.assertEqual(self.parse([0x5678, 0x1234], rule=4), 0x12345678)
        self.assertEqual(self.parse([0xFFFF, 0xFFFF], rule=4), -1)

    def test_scale_is_applied_after_combining_registers(self):
        self.assertEqual(self.parse([1783, 0], rule=3, scale=0.1), 178.3)

    def test_observed_deye_lifetime_counters_decode_correctly(self):
        observed = {
            "battery_charge": ([1794, 0], 179.4),
            "battery_discharge": ([1648, 0], 164.8),
            "energy_sold": ([2, 0], 0.2),
            "load_consumption": ([4354, 0], 435.4),
        }

        for name, (registers, expected) in observed.items():
            with self.subTest(name=name):
                self.assertAlmostEqual(
                    self.parse(registers, rule=3, scale=0.1), expected
                )

    def test_alert_registers_keep_low_word_bit_numbering(self):
        definition = {
            "parameters": [
                {
                    "items": [
                        {
                            "name": "Alert",
                            "class": "enum",
                            "registers": [103, 104, 105, 106],
                            "rule": 3,
                            "lookup": [
                                {"key": 0, "value": "OK"},
                                {"bit": 17, "value": "AC Over-current failure"},
                                {"key": "default", "value": "Problem"},
                            ],
                        }
                    ]
                }
            ]
        }
        parser = ModbusValueParser(definition)

        result = parser.parse_all({103: 0, 104: 0b10, 105: 0, 106: 0})

        self.assertEqual(result["Alert"], "AC Over-current failure")


if __name__ == "__main__":
    unittest.main()
