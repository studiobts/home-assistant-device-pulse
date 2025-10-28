"""Sensor platform for Device Pulse - Network Summary."""

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CONF_ENTRY_TYPE,
    CONF_SENSORS_INTEGRATION_SUMMARY_ENABLED,
    CONF_SENSORS_DISCONNECTED_SINCE_ENABLED,
    CONF_SENSORS_FAILED_PINGS_ENABLED,
    CONF_SENSORS_LAST_RESPONSE_TIME_ENABLED,
    DEFAULT_SENSORS_INTEGRATION_SUMMARY_ENABLED,
    DEFAULT_SENSORS_DISCONNECTED_SINCE_ENABLED,
    DEFAULT_SENSORS_FAILED_PINGS_ENABLED,
    DEFAULT_SENSORS_LAST_RESPONSE_TIME_ENABLED,
    ENTRY_TYPE_NETWORK_SUMMARY,
)
from .entities import (
    DeviceDisconnectedSinceSensor,
    DeviceFailedPingsSensor,
    DeviceLastResponseTimeSensor,
)
from .network_status import TotalDevicesCountSensor, TotalDevicesDisconnectedCountSensor
from .utils import remove_config_entry_orphan_entities


async def async_setup_entry(hass: HomeAssistant, config_entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    """Set up the sensor platform."""
    # Create sensors for network summary entry
    if config_entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_NETWORK_SUMMARY:
        async_add_entities([TotalDevicesCountSensor(hass), TotalDevicesDisconnectedCountSensor(hass)])
        return

    sensors = []
    # Get settings from config entry
    integration = config_entry.runtime_data.integration

    if config_entry.options.get(CONF_SENSORS_FAILED_PINGS_ENABLED, DEFAULT_SENSORS_FAILED_PINGS_ENABLED):
        sensors.append(DeviceFailedPingsSensor)

    if config_entry.options.get(CONF_SENSORS_DISCONNECTED_SINCE_ENABLED, DEFAULT_SENSORS_DISCONNECTED_SINCE_ENABLED):
        sensors.append(DeviceDisconnectedSinceSensor)

    if config_entry.options.get(CONF_SENSORS_LAST_RESPONSE_TIME_ENABLED, DEFAULT_SENSORS_LAST_RESPONSE_TIME_ENABLED):
        sensors.append(DeviceLastResponseTimeSensor)

    entities = [
        sensor(monitored.coordinator, monitored.device, integration)
        for monitored in config_entry.runtime_data.monitored.values()
        for sensor in sensors
    ]

    if config_entry.options.get(CONF_SENSORS_INTEGRATION_SUMMARY_ENABLED, DEFAULT_SENSORS_INTEGRATION_SUMMARY_ENABLED):
        entities.append(TotalDevicesCountSensor(hass, config_entry))
        entities.append(TotalDevicesDisconnectedCountSensor(hass, config_entry))

    if entities:
        async_add_entities(entities)

    # Clean up orphan entities
    remove_config_entry_orphan_entities(hass, config_entry, entities, "sensor")
