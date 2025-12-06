"""ARP Ping implementation for Device Pulse."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

async def is_arping_available(hass: HomeAssistant) -> bool:
    """Check if arping command is available on the system."""
    import shutil

    try:
        # Check if arping is in PATH
        # noinspection PyUnresolvedReferences,PyTypeChecker
        arping_path = await hass.async_add_executor_job(shutil.which, "arping")
        if arping_path:
            _LOGGER.debug("arping command found at: %s", arping_path)
            return True

        _LOGGER.debug("arping command not found in system PATH")
        return False
    except Exception as err:
        _LOGGER.warning("Error checking arping availability: %s", err)
        return False


class PingDataARP:
    """Handle ARP ping requests."""

    def __init__(self, hass: HomeAssistant, ip_address: str, count: int = 1) -> None:
        """Initialize the ARP ping handler."""
        self.hass = hass
        self.ip_address = ip_address
        self.count = count
        self.is_alive = False
        self.data: dict[str, Any] | None = None

    async def async_update(self) -> None:
        """Send ARP request to check if the host is alive."""
        # Use arping command to check if the host responds to ARP
        # -c: count,
        # -w: timeout in seconds
        cmd = ["arping", "-c", str(self.count), "-w", "1", self.ip_address]

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                process.communicate(), timeout=5
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


