"""Coordinator to manage ping updates for devices."""

from dataclasses import dataclass
from datetime import timedelta
import logging
import random
from typing import Any

from homeassistant.components.ping import PingDataICMPLib, PingDataSubProcess
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntry
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .const import (
    DEFAULT_PING_ATTEMPTS_BEFORE_FAILURE,
    DEFAULT_PING_INTERVAL,
    EVENT_DEVICE_CAME_ONLINE,
    EVENT_DEVICE_WENT_OFFLINE,
)
from .utils import IntegrationData, format_duration

_LOGGER = logging.getLogger(__name__)


@dataclass(slots=True, frozen=True)
class PingResult:
    """Dataclass returned by the coordinator."""

    ip_address: str
    is_alive: bool
    data: dict[str, Any]


class DevicePingCoordinator(DataUpdateCoordinator[PingResult]):
    """Coordinator to manage ping updates."""

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: ConfigEntry,
        integration: IntegrationData,
        device_entry: DeviceEntry,
        ping: PingDataICMPLib | PingDataSubProcess,
        ping_attempts_before_failure: int = DEFAULT_PING_ATTEMPTS_BEFORE_FAILURE,
        ping_interval: int = DEFAULT_PING_INTERVAL,
    ) -> None:
        """Initialize the coordinator."""
        self.integration: IntegrationData = integration
        self.device_entry: DeviceEntry = device_entry
        self.ping = ping
        self.ping_interval = ping_interval * 1000  # Convert to milliseconds
        self.ping_attempts_before_failure = ping_attempts_before_failure
        self.failed_pings = 0
        self.failed_started_at = None
        self.last_response_time = None

        self._logger = logging.LoggerAdapter(_LOGGER, {
            "integration": self.integration.friendly_name,
            "device": device_entry.name
        })
        self._first_update = True

        super().__init__(
            hass,
            _LOGGER,
            config_entry=config_entry,
            name=f"Ping {ping.ip_address}",
            update_interval=self._calculate_update_interval(),
        )

    async def _async_update_data(self) -> PingResult:
        """Fetch data from ping."""
        await self.ping.async_update()

        # Adjust the next update interval
        self.update_interval = self._calculate_update_interval()

        is_alive = True

        if self.ping.is_alive:
            if (
                self.data
                and not self.data.is_alive
            ) or self.failed_pings > self.ping_attempts_before_failure:
                self.hass.bus.async_fire(EVENT_DEVICE_CAME_ONLINE, {
                    "device_id": self.device_entry.id,
                    "failed_pings": self.failed_pings,
                    "disconnected_since": self.failed_started_at,
                    "reconnected_at": dt_util.now(),
                })
                _LOGGER.info(
                    "[%s] Device [%s][%s] come back ONLINE after %d consecutive failures (%s)",
                    self.integration.friendly_name,
                    self.device_entry.name,
                    self.ping.ip_address,
                    self.failed_pings,
                    format_duration(
                        (dt_util.now() - self.failed_started_at).total_seconds()
                    ),
                )
            self.failed_pings = 0
            self.failed_started_at = None
            self.last_response_time = (
                self.ping.data.get("avg") if self.ping.data else None
            )
            _LOGGER.debug(
                "[%s] Device [%s][%s] ping successful, response time: %sms",
                self.integration.friendly_name,
                self.device_entry.name,
                self.ping.ip_address,
                self.last_response_time,
            )
        else:
            if not self.failed_pings:
                self.failed_started_at = dt_util.now()

            self.failed_pings += 1
            self.last_response_time = None

            _LOGGER.debug(
                "[%s] Device [%s][%s] ping failed, consecutive failures: %d/%d",
                self.integration.friendly_name,
                self.device_entry.name,
                self.ping.ip_address,
                self.failed_pings,
                self.ping_attempts_before_failure,
            )

            # If it's the first update, consider the device as offline immediately
            # to avoid false positives on startup
            if self._first_update:
                is_alive = False
                _LOGGER.warning(
                    "[%s] Device [%s][%s] initiated OFFLINE",
                    self.integration.friendly_name,
                    self.device_entry.name,
                    self.ping.ip_address
                )

            # If it's the first update, consider the device as offline after the attempts threshold
            elif (
                self.data.is_alive
                and self.failed_pings >= self.ping_attempts_before_failure
            ):
                is_alive = False
                self.hass.bus.async_fire(EVENT_DEVICE_WENT_OFFLINE, {
                    "device_id": self.device_entry.id,
                    "failed_pings": self.failed_pings,
                    "disconnected_since": self.failed_started_at,
                })
                level = (
                    _LOGGER.warning
                    if self.failed_pings == self.ping_attempts_before_failure
                    else _LOGGER.debug
                )
                level(
                    "[%s] Device [%s][%s] is now OFFLINE (%d consecutive failed pings)",
                    self.integration.friendly_name,
                    self.device_entry.name,
                    self.ping.ip_address,
                    self.failed_pings,
                )

            # This is not the first update, but we haven't reached the failure threshold yet
            elif self.data.is_alive:
                _LOGGER.warning(
                    "[%s] Device [%s][%s] ping failed but under failure threshold (%d/%d failed pings)",
                    self.integration.friendly_name,
                    self.device_entry.name,
                    self.ping.ip_address,
                    self.failed_pings,
                    self.ping_attempts_before_failure,
                )

            else:
                is_alive = self.data.is_alive

        if self._first_update:
            self._first_update = False

        return PingResult(
            is_alive=is_alive,
            ip_address=self.ping.ip_address,
            data=self.ping.data or {},
        )

    def _calculate_update_interval(self) -> timedelta:
        """Calculate next update interval with jitter to distribute requests evenly."""
        variation = self.ping_interval * 0.05  # 5% variation
        jittered_interval = self.ping_interval + random.uniform(-variation, variation)

        return timedelta(milliseconds=jittered_interval)
