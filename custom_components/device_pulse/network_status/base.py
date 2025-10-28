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

    async def async_added_to_hass(self) -> None:
        """Register callbacks when entity is added."""

        async def initial_update() -> None:
            await asyncio.sleep(5)
            await self._update()

        self.hass.async_create_task(initial_update())

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
                self.hass.async_create_task(self._update())
        elif action == "remove":
            _LOGGER.debug(
                "Entity Registry event [%s] for [%s], updating count", action, entity_id
            )
            self.hass.async_create_task(self._update())

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
