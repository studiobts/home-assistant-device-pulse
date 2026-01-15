"""ARP Ping implementation for Device Pulse."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from homeassistant.components.network import Adapter
from homeassistant.core import HomeAssistant

from .const import ARP_TIMEOUT
from .utils import get_network_adapter_for_ip

_LOGGER = logging.getLogger(__name__)

class PingDataARP:
    """Handle ARP ping requests."""

    def __init__(self, hass: HomeAssistant, ip_address: str, count: int = 1) -> None:
        """Initialize the ARP ping handler."""
        self.hass = hass
        self.ip_address = ip_address
        self.count = count
        self.is_alive = False
        self.data: dict[str, Any] | None = None
        self._adapter: Adapter | None = None

    async def async_update(self) -> None:
        """Send ARP request to check if the host is alive."""
        if not self._adapter:
            self._adapter, _, __ = await get_network_adapter_for_ip(self.hass, self.ip_address)

        # Use arping command to check if the host responds to ARP
        # -c: count,
        # -w: timeout in seconds
        # -I: interface
        cmd = ["arping", "-c", str(self.count), "-w", str(ARP_TIMEOUT), "-I", self._adapter.get("name"), self.ip_address]

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                process.communicate(), timeout=(ARP_TIMEOUT * 3)
            )

            # arping returns 0 if at least one response was received
            self.is_alive = process.returncode == 0

            if self.is_alive:
                # Parse output to extract response time
                output = stdout.decode("utf-8", errors="ignore")
                self.data = self._parse_arping_output(output)
            else:
                self.data = None
                _LOGGER.debug(
                    "ARP ping to %s failed (return-code: %s)",
                    self.ip_address,
                    process.returncode,
                )

        except asyncio.TimeoutError:
            self.is_alive = False
            self.data = None
            _LOGGER.debug("ARP ping to %s timed out", self.ip_address)
        except FileNotFoundError:
            _LOGGER.error("arping command not found. Please install iputils-arping package")
            self.is_alive = False
            self.data = None
        except Exception as err:
            _LOGGER.error("Error during ARP ping to %s: %s",self.ip_address, err)
            self.is_alive = False
            self.data = None

    @staticmethod
    def _parse_arping_output(output: str) -> dict[str, Any]:
        """Parse arping output to extract timing information."""
        data: dict[str, Any] = {}

        lines = output.split("\n")
        response_times = []

        for line in lines:
            # Look for response lines with timing
            if "reply from" in line.lower() and "ms" in line.lower():
                try:
                    # Extract time value (e.g., "0.789ms")
                    parts = line.split()
                    for part in parts:
                        if "ms" in part.lower():
                            time_str = part.replace("ms", "").strip()
                            response_times.append(float(time_str))
                            break
                except (ValueError, IndexError):
                    continue

        if response_times:
            data["min"] = min(response_times)
            data["max"] = max(response_times)
            data["avg"] = sum(response_times) / len(response_times)

        return data


