"""Binary sensor platform for Device Pulse."""

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import ConfigEntryRuntimeData
from .const import CONF_ENTRY_TYPE, ENTRY_TYPE_NETWORK_SUMMARY
from .entities import DevicePingStatusBinarySensor
from .network_status import AllDevicesOnlineStatusSensor
from .utils import remove_config_entry_orphan_entities

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry[ConfigEntryRuntimeData],
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the binary sensor platform."""
    config_entry_type = config_entry.data.get(CONF_ENTRY_TYPE)

    # Handle network summary entry type
    if config_entry_type == ENTRY_TYPE_NETWORK_SUMMARY:
        async_add_entities([AllDevicesOnlineStatusSensor(hass)])
        return

    entities = [
        DevicePingStatusBinarySensor(monitored.coordinator, monitored.device, config_entry.runtime_data.integration)
        for monitored in config_entry.runtime_data.monitored.values()
    ]

    if entities:
        async_add_entities(entities)

    # Clean up orphan entities
    remove_config_entry_orphan_entities(
        hass, config_entry, entities, "binary_sensor"
    )
