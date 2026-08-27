import importlib.util
from pathlib import Path
import sys
from types import ModuleType
import unittest


ROOT = Path(__file__).parents[1]


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


package = ModuleType("solarmodbus")
package.__path__ = [str(ROOT / "solarmodbus")]
sys.modules["solarmodbus"] = package

homeassistant = ModuleType("homeassistant")
homeassistant_core = ModuleType("homeassistant.core")
homeassistant_core.HomeAssistant = object
homeassistant_helpers = ModuleType("homeassistant.helpers")
homeassistant_coordinator = ModuleType("homeassistant.helpers.update_coordinator")


class DataUpdateCoordinator:
    def __init__(self, hass, **kwargs):
        self.hass = hass


homeassistant_coordinator.DataUpdateCoordinator = DataUpdateCoordinator
sys.modules.update(
    {
        "homeassistant": homeassistant,
        "homeassistant.core": homeassistant_core,
        "homeassistant.helpers": homeassistant_helpers,
        "homeassistant.helpers.update_coordinator": homeassistant_coordinator,
    }
)

pymodbus = ModuleType("pymodbus")
pymodbus_client = ModuleType("pymodbus.client")
pymodbus_client.ModbusTcpClient = object
pymodbus_client.ModbusSerialClient = object
sys.modules.update({"pymodbus": pymodbus, "pymodbus.client": pymodbus_client})

load_module("solarmodbus.const", ROOT / "solarmodbus" / "const.py")
parser_module = load_module(
    "solarmodbus.parser_modbus", ROOT / "solarmodbus" / "parser_modbus.py"
)
coordinator_module = load_module(
    "solarmodbus.coordinator", ROOT / "solarmodbus" / "coordinator.py"
)

ModbusReadRequest = coordinator_module.ModbusReadRequest
ModbusValueParser = parser_module.ModbusValueParser
SolarmodbusCoordinator = coordinator_module.SolarmodbusCoordinator


class Response:
    def __init__(self, registers=None, error=False):
        self.registers = registers
        self._error = error

    def isError(self):
        return self._error


class FakeClient:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []

    def read_holding_registers(self, address, *, count=1, slave=0):
        self.calls.append((0x03, address, count, slave))
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        return response

    def read_input_registers(self, address, *, count=1, slave=0):
        self.calls.append((0x04, address, count, slave))
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        return response


def make_coordinator(definition, slave_id=1):
    coordinator = SolarmodbusCoordinator.__new__(SolarmodbusCoordinator)
    coordinator.definition = definition
    coordinator.slave_id = slave_id
    coordinator.parser = ModbusValueParser(definition)
    coordinator.requests = coordinator._extract_read_requests(definition)
    return coordinator


class RequestTests(unittest.TestCase):
    def test_explicit_requests_parse_and_calculate_count(self):
        coordinator = make_coordinator(
            {
                "requests": [
                    {"start": 0x0003, "end": 0x0070, "mb_functioncode": 0x03}
                ]
            }
        )

        self.assertEqual(
            coordinator.requests, [ModbusReadRequest(0x0003, 0x0070, 0x03)]
        )
        self.assertEqual(coordinator.requests[0].count, 110)

    def test_oversized_request_is_split_without_truncation(self):
        coordinator = make_coordinator(
            {
                "requests": [
                    {"start": 10, "end": 259, "mb_functioncode": 0x04}
                ]
            }
        )

        self.assertEqual(
            coordinator.requests,
            [
                ModbusReadRequest(10, 134, 0x04),
                ModbusReadRequest(135, 259, 0x04),
            ],
        )

    def test_missing_requests_falls_back_to_contiguous_parameter_ranges(self):
        coordinator = make_coordinator(
            {
                "parameters": [
                    {
                        "items": [
                            {"register": 100},
                            {"registers": [101, 102]},
                            {"registers": [105, 106]},
                        ]
                    }
                ]
            }
        )

        self.assertEqual(
            coordinator.requests,
            [
                ModbusReadRequest(100, 102, 0x03),
                ModbusReadRequest(105, 106, 0x03),
            ],
        )

    def test_invalid_requests_fall_back_to_parameter_ranges(self):
        coordinator = make_coordinator(
            {
                "requests": [{"start": 10, "end": 9, "mb_functioncode": 0x03}],
                "parameters": [{"items": [{"registers": 42}]}],
            }
        )

        self.assertEqual(coordinator.requests, [ModbusReadRequest(42, 42, 0x03)])


class ReadTests(unittest.TestCase):
    def test_response_is_mapped_to_absolute_addresses_and_slave_is_passed(self):
        coordinator = make_coordinator({}, slave_id=7)
        client = FakeClient([Response([10, 20, 30])])

        values = coordinator._read_request(
            client, ModbusReadRequest(100, 102, 0x03)
        )

        self.assertEqual(values, {100: 10, 101: 20, 102: 30})
        self.assertEqual(client.calls, [(0x03, 100, 3, 7)])

    def test_fc03_and_fc04_batches_are_merged(self):
        coordinator = make_coordinator(
            {
                "requests": [
                    {"start": 10, "end": 11, "mb_functioncode": 0x03},
                    {"start": 20, "end": 21, "mb_functioncode": 0x04},
                ]
            },
            slave_id=4,
        )
        client = FakeClient([Response([1, 2]), Response([3, 4])])

        values, _ = coordinator._read_requests(client)

        self.assertEqual(values, {10: 1, 11: 2, 20: 3, 21: 4})
        self.assertEqual(
            client.calls, [(0x03, 10, 2, 4), (0x04, 20, 2, 4)]
        )

    def test_partial_failure_preserves_other_batches(self):
        coordinator = make_coordinator(
            {
                "requests": [
                    {"start": 10, "end": 10, "mb_functioncode": 0x03},
                    {"start": 20, "end": 20, "mb_functioncode": 0x03},
                    {"start": 30, "end": 30, "mb_functioncode": 0x03},
                ]
            }
        )
        client = FakeClient([Response([1]), TimeoutError("timeout"), Response([3])])

        values, _ = coordinator._read_requests(client)

        self.assertEqual(values, {10: 1, 30: 3})
        self.assertEqual(len(client.calls), 3)

    def test_current_pymodbus_device_id_keyword_is_supported(self):
        coordinator = make_coordinator({}, slave_id=9)
        calls = []

        class CurrentClient:
            def read_holding_registers(
                self, address, *, count=1, device_id=1, no_response_expected=False
            ):
                calls.append((address, count, device_id))
                return Response([42])

        values = coordinator._read_request(
            CurrentClient(), ModbusReadRequest(50, 50, 0x03)
        )

        self.assertEqual(values, {50: 42})
        self.assertEqual(calls, [(50, 1, 9)])

    def test_unsupported_function_code_is_not_read_as_fc03(self):
        coordinator = make_coordinator({})
        client = FakeClient([])

        values = coordinator._read_request(
            client, ModbusReadRequest(50, 50, 0x06)
        )

        self.assertEqual(values, {})
        self.assertEqual(client.calls, [])


class ParserCompatibilityTests(unittest.TestCase):
    def test_batched_mapping_preserves_parser_output(self):
        definition = {
            "parameters": [
                {
                    "items": [
                        {
                            "name": "Lifetime energy",
                            "registers": [100, 101],
                            "rule": 3,
                            "scale": 0.1,
                        },
                        {
                            "name": "Signed power",
                            "register": 102,
                            "rule": 2,
                        },
                    ]
                }
            ]
        }
        coordinator = make_coordinator(definition)
        client = FakeClient([Response([1, 2, 65535])])
        coordinator.requests = [ModbusReadRequest(100, 102, 0x03)]

        batched_values, _ = coordinator._read_requests(client)
        old_values = {100: 1, 101: 2, 102: 65535}

        self.assertEqual(
            coordinator.parser.parse_all(batched_values),
            coordinator.parser.parse_all(old_values),
        )


if __name__ == "__main__":
    unittest.main()
