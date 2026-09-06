"""Base entity classes for the Device Pulse custom integration.

Provides abstract base classes and event handling for ping monitor entities.
"""

from abc import ABC, abstractmethod
import asyncio
import logging

from custom_components.device_pulse import ConfigEntryRuntimeData
from custom_components.device_pulse.const import (
    DOMAIN,
    EVENT_PING_STATUS_UPDATED,
)
from custom_components.device_pulse.utils import IntegrationData

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.event import EventStateChangedData

_LOGGER = logging.getLogger(__name__)


class NetworkStatusEntity(Entity, ABC):
    """Base class for all sensors."""

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: ConfigEntry[ConfigEntryRuntimeData] | None = None,
    ) -> None:
        """Initialize the sensor."""
        self.hass = hass
        self.config_entry: ConfigEntry | None = config_entry
        self.integration: IntegrationData = config_entry.runtime_data.integration if config_entry else None
        # Track a single in-flight _update task per entity so bursts of events
        # (e.g. mass entity registry churn during a reload/restart) do not pile
        # up one task per event.
        self._update_task: asyncio.Task | None = None

    async def async_added_to_hass(self) -> None:
        """Register callbacks when entity is added."""

        async def initial_update() -> None:
            await asyncio.sleep(5)
            self._async_schedule_update()

        # Track the initial update so it is cancelled when the entity is
        # removed during an unload/reload.
        initial_update_task = self.hass.async_create_task(initial_update())

        def cancel_initial_update() -> None:
            initial_update_task.cancel()

        self.async_on_remove(cancel_initial_update)

        self.async_on_remove(
            self.hass.bus.async_listen(
                EVENT_PING_STATUS_UPDATED,
                self._state_changed,
            )
        )

        self.async_on_remove(
            self.hass.bus.async_listen(
                er.EVENT_ENTITY_REGISTRY_UPDATED,
                self._entity_registry_updated,  # type: ignore  # noqa: PGH003
            )
        )

        # Make sure a pending _update task does not outlive the entity when it
        # is removed during an unload/reload.
        self.async_on_remove(self._async_cancel_update_task)

    @callback
    def _async_cancel_update_task(self) -> None:
        """Cancel a pending update task, if any."""
        if self._update_task is not None:
            self._update_task.cancel()
            self._update_task = None

    @callback
    def _async_schedule_update(self) -> None:
        """Schedule a single _update run.

        If an update is already scheduled or in-flight, this is a no-op to
        coalesce bursts of events into a single run.
        """
        if self._update_task is not None and not self._update_task.done():
            return

        self._update_task = self.hass.async_create_task(self._async_run_update())

    async def _async_run_update(self) -> None:
        """Run _update and clear the task reference when done."""
        try:
            await self._update()
        finally:
            self._update_task = None

    @callback
    def _entity_registry_updated(self, event: Event) -> None:
        """Handle entity registry updates."""
        action = event.data.get("action")
        entity_registry = er.async_get(self.hass)
        entity_id = event.data.get("entity_id")

        if action in ("create", "update"):
            # Check for entity before update
            entity_entry = entity_registry.async_get(entity_id)
            if (
                entity_entry
                and entity_entry.platform == DOMAIN
                and entity_entry.domain == "binary_sensor"
            ):
                _LOGGER.debug(
                    "Entity Registry event [%s] for [%s], updating count",
                    action,
                    entity_id,
                )
                self._async_schedule_update()
        elif action == "remove":
            _LOGGER.debug(
                "Entity Registry event [%s] for [%s], updating count", action, entity_id
            )
            self._async_schedule_update()

    @abstractmethod
    @callback
    def _state_changed(self, event: Event[EventStateChangedData]) -> None:
        pass

    @abstractmethod
    async def _update(self) -> None:
        pass

    @property
    def device_info(self) -> dict:
        """Return device info for grouping."""
        if self.integration:
            return {
                "identifiers": {(DOMAIN, f"{self.integration.domain}_summary")},
                "name": f"{self.integration.friendly_name} Devices Summary Helpers",
            }

        return {
            "identifiers": {(DOMAIN, "network_summary")},
            "name": "Network Summary Helpers",
        }
