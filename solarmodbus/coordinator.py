from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
import inspect
import logging
from time import perf_counter

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from pymodbus.client import ModbusTcpClient, ModbusSerialClient

from .const import DEFAULT_TIMEOUT
from .parser_modbus import ModbusValueParser

LOGGER = logging.getLogger(__name__)

SCAN_INTERVAL = timedelta(seconds=2)
MAX_READ_REGISTERS = 125


@dataclass(frozen=True)
class ModbusReadRequest:
    start: int
    end: int
    function_code: int

    @property
    def count(self) -> int:
        return self.end - self.start + 1


class SolarmodbusCoordinator(DataUpdateCoordinator):
    def __init__(
        self,
        hass: HomeAssistant,
        mode: str,
        host: str | None,
        port: int | None,
        serial_port: str | None,
        slave_id: int,
        definition: dict,
    ):
        super().__init__(
            hass,
            logger=LOGGER,
            name="Solarmodbus Coordinator",
            update_interval=SCAN_INTERVAL,
        )

        self.mode = mode
        self.host = host
        self.port = port
        self.serial_port = serial_port
        self.slave_id = slave_id
        self.definition = definition

        self.parser = ModbusValueParser(definition)
        self.requests = self._extract_read_requests(definition)

        if self.mode == "modbus":
            self._client = ModbusTcpClient(
                host=self.host,
                port=self.port,
                timeout=DEFAULT_TIMEOUT,
            )
        else:
            self._client = ModbusSerialClient(
                port=self.serial_port,
                baudrate=9600,
                parity="N",
                stopbits=1,
                bytesize=8,
                timeout=DEFAULT_TIMEOUT,
            )

    def write_register(self, address, value):
        try:
            self._client.close()
        except Exception:
            pass

        if not self._client.connect():
            raise Exception("Unable to connect for write")

        rr = self._client.write_registers(address, [value])

        self._client.close()
        return rr

    @staticmethod
    def _split_request(request: ModbusReadRequest) -> list[ModbusReadRequest]:
        chunks = []
        for start in range(request.start, request.end + 1, MAX_READ_REGISTERS):
            chunks.append(
                ModbusReadRequest(
                    start=start,
                    end=min(start + MAX_READ_REGISTERS - 1, request.end),
                    function_code=request.function_code,
                )
            )
        return chunks

    def _extract_read_requests(self, definition: dict) -> list[ModbusReadRequest]:
        configured = definition.get("requests")
        if isinstance(configured, list) and configured:
            try:
                requests = [
                    ModbusReadRequest(
                        start=item["start"],
                        end=item["end"],
                        function_code=item["mb_functioncode"],
                    )
                    for item in configured
                ]
                if not all(
                    isinstance(request.start, int)
                    and isinstance(request.end, int)
                    and isinstance(request.function_code, int)
                    and request.start >= 0
                    and request.end >= request.start
                    for request in requests
                ):
                    raise ValueError("invalid request values")
            except (KeyError, TypeError, ValueError):
                LOGGER.warning(
                    "[Solarmodbus] Invalid requests section; deriving read ranges "
                    "from parameter registers"
                )
            else:
                return [
                    chunk
                    for request in requests
                    for chunk in self._split_request(request)
                ]

        addresses = set()
        for group in definition.get("parameters", []):
            for item in group.get("items", []):
                registers = item.get("registers")
                if registers is None:
                    registers = [item.get("register")]
                elif isinstance(registers, int):
                    registers = [registers]
                addresses.update(
                    register for register in registers if isinstance(register, int)
                )

        requests = []
        for address in sorted(addresses):
            if requests and address == requests[-1].end + 1:
                previous = requests[-1]
                requests[-1] = ModbusReadRequest(
                    previous.start, address, previous.function_code
                )
            else:
                requests.append(ModbusReadRequest(address, address, 0x03))

        return [
            chunk for request in requests for chunk in self._split_request(request)
        ]

    def _read_request(self, client, request: ModbusReadRequest) -> dict[int, int]:
        if request.function_code == 0x03:
            method = client.read_holding_registers
        elif request.function_code == 0x04:
            method = client.read_input_registers
        else:
            LOGGER.error(
                "[Solarmodbus] Unsupported Modbus function code 0x%02X for "
                "registers %s-%s",
                request.function_code,
                request.start,
                request.end,
            )
            return {}

        # PyModbus renamed this keyword from slave to device_id in 3.10.
        parameters = inspect.signature(method).parameters
        id_keyword = "device_id" if "device_id" in parameters else "slave"
        response = method(
            request.start,
            count=request.count,
            **{id_keyword: self.slave_id},
        )

        if response.isError() or not getattr(response, "registers", None):
            LOGGER.warning(
                "[Solarmodbus] Failed reading registers %s-%s with function "
                "code 0x%02X: %s",
                request.start,
                request.end,
                request.function_code,
                response,
            )
            return {}

        if len(response.registers) != request.count:
            LOGGER.warning(
                "[Solarmodbus] Read %s registers for range %s-%s; expected %s",
                len(response.registers),
                request.start,
                request.end,
                request.count,
            )

        return {
            request.start + offset: value
            for offset, value in enumerate(response.registers[: request.count])
        }

    def _read_requests(self, client) -> tuple[dict[int, int], float]:
        values = {}
        read_time = 0.0

        for request in self.requests:
            started = perf_counter()
            try:
                values.update(self._read_request(client, request))
            except Exception as err:
                LOGGER.warning(
                    "[Solarmodbus] Exception reading registers %s-%s with "
                    "function code 0x%02X: %s",
                    request.start,
                    request.end,
                    request.function_code,
                    err,
                )
            finally:
                read_time += perf_counter() - started

        return values, read_time

    async def _async_update_data(self):
        poll_started = perf_counter()
        client = self._client

        try:
            client.close()
        except Exception:
            pass

        if not client.connect():
            LOGGER.error("[Solarmodbus] Unable to connect to Modbus device")
            return {}

        try:
            merged, read_time = await self.hass.async_add_executor_job(
                self._read_requests, client
            )
        finally:
            client.close()

        if not merged:
            LOGGER.error("[Solarmodbus] No registers read")
            return {}

        parsing_started = perf_counter()
        parsed = self.parser.parse_all(merged)
        parsing_time = perf_counter() - parsing_started
        LOGGER.debug(
            "Solarmodbus poll: requests=%s modbus_read_time=%.3fs "
            "parsing_time=%.3fs total_time=%.3fs registers=%s",
            len(self.requests),
            read_time,
            parsing_time,
            perf_counter() - poll_started,
            len(merged),
        )
        return parsed
