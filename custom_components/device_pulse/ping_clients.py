"""Ping clients for Device Pulse.

The built-in Home Assistant ping clients only kill their child `ping`
process when the probe times out. When the surrounding refresh task gets
cancelled - which is exactly what the config entry machinery does on
unload/reload/shutdown - the `ping` child process is orphaned and keeps
running until it exits by itself.

This module provides a drop-in replacement for `PingDataSubProcess` that
reaps the child process on cancellation too.
"""

import asyncio
from contextlib import suppress
import logging
import re
from typing import Any

from homeassistant.components.ping.helpers import PingDataSubProcess

_LOGGER = logging.getLogger(__name__)

# Overall timeout for the ping binary, in seconds (matches core ping).
PING_TIMEOUT = 3

PING_MATCHER = re.compile(
    r"(?P<min>\d+.\d+)\/(?P<avg>\d+.\d+)\/(?P<max>\d+.\d+)\/(?P<mdev>\d+.\d+)"
)

PING_MATCHER_BUSYBOX = re.compile(
    r"(?P<min>\d+.\d+)\/(?P<avg>\d+.\d+)\/(?P<max>\d+.\d+)"
)

WIN32_PING_MATCHER = re.compile(r"(?P<min>\d+)ms.+(?P<max>\d+)ms.+(?P<avg>\d+)ms")


class ReapingPingDataSubProcess(PingDataSubProcess):
    """PingDataSubProcess that kills the ping child on cancellation.

    Identical behaviour to the core class but it also reaps the child when
    the task is cancelled (config entry unload/reload or shutdown), so no
    orphaned `ping` processes are left behind during a reload.
    """

    async def async_ping(self) -> dict[str, Any] | None:
        """Send ICMP echo request and return details if success."""
        _LOGGER.debug(
            "Pinging %s with: `%s`", self.ip_address, " ".join(self._ping_cmd)
        )

        pinger = await asyncio.create_subprocess_exec(
            *self._ping_cmd,
            stdin=None,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            close_fds=False,  # required for posix_spawn
        )
        try:
            async with asyncio.timeout(self._count + PING_TIMEOUT):
                out_data, out_error = await pinger.communicate()

            if out_data:
                _LOGGER.debug(
                    "Output of command: `%s`, return code: %s:\n%s",
                    " ".join(self._ping_cmd),
                    pinger.returncode,
                    out_data,
                )
            if out_error:
                _LOGGER.debug(
                    "Error of command: `%s`, return code: %s:\n%s",
                    " ".join(self._ping_cmd),
                    pinger.returncode,
                    out_error,
                )

            if pinger.returncode and pinger.returncode > 1:
                # returncode of 1 means the host is unreachable
                _LOGGER.exception(
                    "Error running command: `%s`, return code: %s",
                    " ".join(self._ping_cmd),
                    pinger.returncode,
                )

            if "max/" not in str(out_data):
                match = PING_MATCHER_BUSYBOX.search(
                    str(out_data).rsplit("\n", maxsplit=1)[-1]
                )
                if match is None:
                    _LOGGER.debug("Could not parse ping output for %s", self.ip_address)
                    return None
                rtt_min, rtt_avg, rtt_max = match.groups()
                return {"min": rtt_min, "avg": rtt_avg, "max": rtt_max}
            match = PING_MATCHER.search(str(out_data).rsplit("\n", maxsplit=1)[-1])
            if match is None:
                _LOGGER.debug("Could not parse ping output for %s", self.ip_address)
                return None
            rtt_min, rtt_avg, rtt_max, rtt_mdev = match.groups()
        except TimeoutError:
            _LOGGER.debug(
                "Timed out running command: `%s`, after: %s",
                " ".join(self._ping_cmd),
                self._count + PING_TIMEOUT,
            )
            await self._kill(pinger)
            return None
        except asyncio.CancelledError:
            # Refresh task cancelled (unload/reload/shutdown): reap the child
            # process instead of leaking it until it exits by itself.
            await self._kill(pinger)
            raise
        except AttributeError as err:
            _LOGGER.debug("Error matching ping output: %s", err)
            return None
        return {"min": rtt_min, "avg": rtt_avg, "max": rtt_max, "mdev": rtt_mdev}

    async def async_update(self) -> None:
        """Retrieve the latest details from the host."""
        self.data = await self.async_ping()
        self.is_alive = self.data is not None

    async def _kill(self, pinger: asyncio.subprocess.Process | None) -> None:
        """Best-effort kill and reap of a subprocess."""
        if pinger is None or pinger.returncode is not None:
            return
        with suppress(TypeError, ProcessLookupError):
            pinger.kill()
        with suppress(TypeError):
            await pinger.wait()
