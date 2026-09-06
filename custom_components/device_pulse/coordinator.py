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
    DEFAULT_PING_REQUESTS_PER_ATTEMPT,
    DEFAULT_PING_INTERVAL,
    DEFAULT_LOG_LEVEL_DEVICE_OFFLINE,
    DEFAULT_LOG_LEVEL_FAILED_PINGS,
    EVENT_DEVICE_CAME_ONLINE,
    EVENT_DEVICE_WENT_OFFLINE,
    EVENT_TOTAL_FAILED_PINGS_RESET,
    PING_METHOD_ARP,
    PING_METHOD_ICMP
)
from .arping import PingDataARP
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
        host_source: str,
        ping: PingDataICMPLib | PingDataSubProcess | PingDataARP,
        ping_attempts_before_failure: int = DEFAULT_PING_ATTEMPTS_BEFORE_FAILURE,
        ping_requests_per_attempt: int = DEFAULT_PING_REQUESTS_PER_ATTEMPT,
        ping_interval: int = DEFAULT_PING_INTERVAL,
        log_level_failed_pings: int = DEFAULT_LOG_LEVEL_FAILED_PINGS,
        log_level_device_offline: int = DEFAULT_LOG_LEVEL_DEVICE_OFFLINE,
    ) -> None:
        """Initialize the coordinator."""
        self.integration: IntegrationData = integration
        self.device_entry: DeviceEntry = device_entry
        self.host_source: str = host_source
        self.ping = ping
        self.ping_interval = ping_interval * 1000  # Convert to milliseconds
        self.ping_attempts_before_failure = ping_attempts_before_failure
        self.ping_requests_per_attempt = ping_requests_per_attempt
        self.failed_pings = 0
        self.failed_started_at = None
        self.total_failed_pings = 0
        self.total_failed_pings_started_at = dt_util.now().isoformat()
        self.last_response_time = None
        self._first_update = True
        self._log_level_failed_pings = log_level_failed_pings
        self._log_level_device_offline = log_level_device_offline

        # Backoff handling: once a device has been failing for more than
        # ping_attempts_before_failure consecutive polls we slow the polling
        # down (up to ping_interval * backoff_max_factor) instead of spawning
        # a subprocess at full rate forever. The interval is restored as soon
        # as the device responds again.
        self._backoff_max_factor = 4
        self._base_ping_interval_ms = ping_interval * 1000
        self._active_backoff_factor = 1

        # Remove unnecessary logs from inner coordinator methods
        if _LOGGER.isEnabledFor(logging.DEBUG):
            inner_logger = logging.getLogger(f"%s.inner" % __name__)
            inner_logger.setLevel(logging.INFO)
        else:
            inner_logger = _LOGGER

        super().__init__(
            hass,
            inner_logger,
            config_entry=config_entry,
            name=f"Ping {ping.ip_address}",
            update_interval=self._calculate_update_interval(),
        )

    async def _async_update_data(self) -> PingResult:
        """Fetch data from ping."""
        await self.ping.async_update()

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
                round(self.ping.data.get("avg"), 3) if self.ping.data else None
            )
            # Device responded again: restore the base polling interval.
            if self._active_backoff_factor != 1:
                self._active_backoff_factor = 1
                _LOGGER.info(
                    "[%s] Device [%s][%s] back online, polling interval restored",
                    self.integration.friendly_name,
                    self.device_entry.name,
                    self.ping.ip_address,
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
            self.total_failed_pings += 1
            self.last_response_time = None

            # Once the failure threshold has been exceeded, slow the polling
            # down instead of spawning a subprocess at full rate forever. The
            # interval grows linearly with the number of extra consecutive
            # failures up to ping_interval * backoff_max_factor.
            if self.failed_pings > self.ping_attempts_before_failure:
                extra = self.failed_pings - self.ping_attempts_before_failure
                factor = min(extra + 1, self._backoff_max_factor)
                if factor != self._active_backoff_factor:
                    self._active_backoff_factor = factor
                    _LOGGER.log(
                        self._log_level_failed_pings,
                        "[%s] Device [%s][%s] slowing down polling "
                        "(interval x%d) after %d consecutive failures",
                        self.integration.friendly_name,
                        self.device_entry.name,
                        self.ping.ip_address,
                        factor,
                        self.failed_pings,
                    )

            _LOGGER.log(
                self._log_level_failed_pings,
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
                _LOGGER.log(
                    self._log_level_device_offline,
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
                _LOGGER.log(
                    self._log_level_device_offline,
                    "[%s] Device [%s][%s] is now OFFLINE (%d consecutive failed pings)",
                    self.integration.friendly_name,
                    self.device_entry.name,
                    self.ping.ip_address,
                    self.failed_pings,
                )

            # This is not the first update, but we haven't reached the failure threshold yet
            elif self.data.is_alive:
                _LOGGER.log(
                    self._log_level_failed_pings,
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

        # Adjust the next update interval based on the current backoff state.
        self.update_interval = self._calculate_update_interval()

        return PingResult(
            is_alive=is_alive,
            ip_address=self.ping.ip_address,
            data=self.ping.data or {},
        )

    def reset_total_failed_pings(self, entity_id: str) -> None:
        """Reset the total failed ping counter."""
        old_total_failed_pings = self.total_failed_pings
        old_count_started_at = self.total_failed_pings_started_at

        self.total_failed_pings = 0
        self.total_failed_pings_started_at = dt_util.now().isoformat()
        self.async_update_listeners()

        self.hass.bus.async_fire(EVENT_TOTAL_FAILED_PINGS_RESET, {
            "entity_id": entity_id,
            "device_id": self.device_entry.id,
            "old_total_failed_pings": old_total_failed_pings,
            "new_total_failed_pings": self.total_failed_pings,
            "old_count_started_at": old_count_started_at,
            "new_count_started_at": self.total_failed_pings_started_at,
            "reset_at": self.total_failed_pings_started_at,
        })

    def _calculate_update_interval(self) -> timedelta:
        """Calculate next update interval with jitter to distribute requests evenly.

        When the device has been failing for more than the failure threshold,
        the base interval is multiplied by the active backoff factor.
        """
        base_interval = self._base_ping_interval_ms * self._active_backoff_factor
        variation = base_interval * 0.05  # 5% variation
        jittered_interval = base_interval + random.uniform(-variation, variation)

        return timedelta(milliseconds=jittered_interval)

    @property
    def ping_method(self) -> str:
        """Return the ping method being used (ICMP or ARP)."""
        if isinstance(self.ping, PingDataARP):
            return PING_METHOD_ARP
        return PING_METHOD_ICMP
