"""Device Pulse Integration."""

import asyncio
from dataclasses import dataclass, field
from functools import partial
import logging
from typing import Any

from homeassistant.components.ping import PingDataICMPLib, PingDataSubProcess, _can_use_icmp_lib_with_privilege
from homeassistant.components import zeroconf
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Event, HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import event
from homeassistant.helpers.typing import ConfigType
from homeassistant.util.hass_dict import HassKey

from . import utils
from . import websocket_api
from .const import (
    CONF_DEVICE_SELECTION_MODE,
    CONF_ENTRY_TYPE,
    CONF_INTEGRATION,
    CONF_GROUP_ID,
    CONF_GROUP_NAME,
    CONF_GROUP_DEVICES_LIST,
    CONF_GROUP_DEVICE_ID,
    CONF_GROUP_DEVICE_NAME,
    CONF_GROUP_DEVICE_HOST,
    CONF_PING_ATTEMPTS_BEFORE_FAILURE,
    CONF_PING_INTERVAL,
    CONF_SELECTED_DEVICES,
    DEFAULT_PING_ATTEMPTS_BEFORE_FAILURE,
    DEFAULT_PING_INTERVAL,
    DEVICE_SELECTION_ALL,
    DEVICE_SELECTION_EXCLUDE,
    DEVICE_SELECTION_INCLUDE,
    DOMAIN,
    ENTITY_TAG_PING_STATUS,
    ENTRY_TYPE_CUSTOM_GROUP,
    ENTRY_TYPE_INTEGRATION,
    ENTRY_TYPE_NETWORK_SUMMARY,
    EVENT_PING_STATUS_UPDATED,
    EVENT_DEVICE_WENT_OFFLINE,
    EVENT_DEVICE_CAME_ONLINE,
    NETWORK_SUMMARY_ENTRY_ID,
    PLATFORMS,
)
from .coordinator import DevicePingCoordinator

_LOGGER = logging.getLogger(__name__)

DATA_CONFIG_KEY: HassKey["ConfigData"] = HassKey(DOMAIN)

CONFIG_SCHEMA = cv.empty_config_schema(DOMAIN)

@dataclass
class ConfigMonitoredIntegrationData:
    """Holds configuration data for a monitored config entry."""

    domain: str
    config_entry_id: str


@dataclass
class ConfigData:
    """Holds configuration data for the Device Pulse integration."""

    ping_privileged: bool | None # Flag to true if privileged ping is available
    integrations: dict[str, utils.IntegrationData]
    monitored: dict[str, ConfigMonitoredIntegrationData] = field(default_factory=dict)


@dataclass
class ConfigMonitoredDeviceData:
    """Holds runtime data for a monitored device."""

    device: dr.DeviceEntry
    coordinator: DevicePingCoordinator


@dataclass
class ConfigEntryRuntimeData:
    """Holds runtime data for a Device Pulse config entry."""

    integration: utils.IntegrationData
    monitored: dict[str, ConfigMonitoredDeviceData] = field(default_factory=dict)
    reload_task: asyncio.Task[Any] | None = None


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the integration."""
    # Determine if privileged ping is available
    ping_privileged = await _can_use_icmp_lib_with_privilege()
    _LOGGER.debug("Privileged ping available: %s", ping_privileged)
    # Build initial list of integrations valid for monitoring
    integrations = await utils.get_valid_integrations_for_monitoring(hass)
    _LOGGER.info("Found %d valid integrations for monitoring: %s",
        len(integrations),
        [integration.friendly_name for integration in integrations.values()]
    )
    # Store in hass data
    hass.data[DATA_CONFIG_KEY] = ConfigData(
        ping_privileged,
        integrations
    )

    # Register listeners for device and entity registry updates
    hass.bus.async_listen(dr.EVENT_DEVICE_REGISTRY_UPDATED, partial(_device_registry_updated, hass=hass))
    hass.bus.async_listen(er.EVENT_ENTITY_REGISTRY_UPDATED, partial(_entity_registry_updated, hass=hass))
    # Register listener for state changes of our entities
    event.async_track_state_change_filtered(
        hass, event.TrackStates(
            all_states=False,
            entities=set(),
            domains={"binary_sensor"}
        ),
        partial(_state_changed, hass=hass)
    )

    websocket_api.async_setup(hass)

    return True


async def async_setup_entry(
    hass: HomeAssistant, config_entry: ConfigEntry[ConfigEntryRuntimeData]
) -> bool:
    """Set up Device Pulse from a config entry."""
    entry_type = config_entry.data.get(CONF_ENTRY_TYPE)
    # Create network summary entry if not already exists
    # Setup device ping coordinators used by all platforms
    if entry_type in [ENTRY_TYPE_INTEGRATION, ENTRY_TYPE_CUSTOM_GROUP]:
        await _ensure_network_summary_entry_exists(hass)

        device_registry = dr.async_get(hass)
        zc = await zeroconf.async_get_instance(hass)

        if entry_type == ENTRY_TYPE_INTEGRATION:
            # Get integration domain to monitor
            domain = config_entry.data.get(CONF_INTEGRATION)
            # Push monitored domain to hass data
            hass.data[DATA_CONFIG_KEY].monitored.update({domain: ConfigMonitoredIntegrationData(domain, config_entry.entry_id)})
            # If domain is not into cached integrations list, update it
            if not domain in hass.data[DATA_CONFIG_KEY].integrations:
                hass.data[DATA_CONFIG_KEY].integrations = await utils.get_valid_integrations_for_monitoring(hass)
            # Get integration data
            integration = hass.data[DATA_CONFIG_KEY].integrations[domain]

            device_mode = config_entry.options.get(CONF_DEVICE_SELECTION_MODE, DEVICE_SELECTION_ALL)
            selected_devices = config_entry.options.get(CONF_SELECTED_DEVICES, [])

            # Find all valid devices related to the monitored integration
            devices = await utils.get_integration_devices_valid(hass, integration)

            _LOGGER.info("[%s] Setting-Up Monitors:", integration.friendly_name)
            _LOGGER.info("[%s]   Mode: %s", integration.friendly_name, device_mode)
            _LOGGER.info("[%s]   Devices: %s", integration.friendly_name, selected_devices or "None")
        else:
            group_id = config_entry.data.get(CONF_GROUP_ID)
            group_name = config_entry.options.get(CONF_GROUP_NAME)
            group_devices_list = config_entry.options.get(CONF_GROUP_DEVICES_LIST)

            devices = []
            for group_device in group_devices_list:
                device = device_registry.async_get_or_create(
                    config_entry_id=config_entry.entry_id,
                    identifiers={(DOMAIN, group_device.get(CONF_GROUP_DEVICE_ID))},
                    name=group_device.get(CONF_GROUP_DEVICE_NAME),
                )
                devices.append(device)

            domain = f"{DOMAIN}_group_{group_id}"
            integration = utils.IntegrationData(domain, group_name, len(devices), True)

            device_mode = None
            selected_devices = []

            _LOGGER.info("[%s] Setting-Up Monitors:", group_name)

        # Create runtime data for the config entry
        config_entry.runtime_data = ConfigEntryRuntimeData(integration)

        ping_attempts_before_failure: int = int(config_entry.options.get(CONF_PING_ATTEMPTS_BEFORE_FAILURE, DEFAULT_PING_ATTEMPTS_BEFORE_FAILURE))
        ping_interval: int = int(config_entry.options.get(CONF_PING_INTERVAL, DEFAULT_PING_INTERVAL))

        _LOGGER.info("[%s]   Attempts Before Failure: %d", integration.friendly_name, ping_attempts_before_failure)
        _LOGGER.info("[%s]   Interval: %ds", integration.friendly_name, ping_interval)
        _LOGGER.info("[%s] Found [%d] valid devices", integration.friendly_name, len(devices))

        # Determine ping client based on privileges
        ping: type[PingDataICMPLib | PingDataSubProcess]
        privileged = hass.data[DATA_CONFIG_KEY].ping_privileged
        ping = PingDataSubProcess if privileged is None else PingDataICMPLib

        disabled_devices = []

        for device in devices:
            # Extract host for the device
            host = await utils.extract_device_host(hass, device, zc)

            if host:
                if device.disabled:
                    disabled_devices.append(device)

                # Based on device mode we have to check if device must be monitored
                if device_mode == DEVICE_SELECTION_EXCLUDE and device.id in selected_devices:
                    _LOGGER.warning("[%s]   Device excluded [%s]", device.name, integration.friendly_name)
                    continue
                if device_mode == DEVICE_SELECTION_INCLUDE and device.id not in selected_devices:
                    _LOGGER.warning("[%s]   Device not included [%s]", device.name, integration.friendly_name)
                    continue

                # Create the coordinator for the device
                coordinator = DevicePingCoordinator(
                    hass,
                    config_entry,
                    integration,
                    device,
                    ping(hass, host, 1, privileged),
                    ping_attempts_before_failure,
                    ping_interval
                )
                await coordinator.async_config_entry_first_refresh()

                config_entry.runtime_data.monitored.update({device.id: ConfigMonitoredDeviceData(device, coordinator)})

                _LOGGER.info(
                    "[%s] Created monitor for [%s] at [%s] - Initial state: {%s}",
                        integration.friendly_name,
                    device.name,
                    host,
                    "CONNECTED" if coordinator.data.is_alive else "DISCONNECTED",
                )
            else:
                _LOGGER.warning("[%s]   Could not extract Host for device [%s]",device.name, integration.friendly_name)

        for disabled_device in disabled_devices:
            _LOGGER.warning("[%s]   Keep device disabled [%s]", disabled_device.name, integration.friendly_name)
            device_registry.async_update_device(disabled_device.id, disabled_by=disabled_device.disabled_by)

    await hass.config_entries.async_forward_entry_setups(config_entry, PLATFORMS)

    return True


async def _device_registry_updated(
    device_event: Event, hass: HomeAssistant
) -> None:
    """Handle device registry updates.

    We have 2 type of events:
    - create: in this case we have to check if any config entries of the
      device belongs to the monitored integration.
      If true, we have to reload to add the related sensors
    - update: the event occurs in case of any change (e.g.: disabled by someone) or
      if the original config entry has been deleted. The device is not delete
      because we have attached our sensors and no "remove" event occurs
    """
    integrations = hass.data[DATA_CONFIG_KEY].integrations
    monitored = hass.data[DATA_CONFIG_KEY].monitored
    action = device_event.data["action"]

    if not (device_id := device_event.data.get("device_id")):
        return

    if action == "remove":
        return

    # Get device registry and device entry
    device_registry = dr.async_get(hass)
    device_entry = device_registry.async_get(device_id)

    if not device_entry:
        return

    reload = False

    # Get the primary config entry for the device
    primary_config_entry = hass.config_entries.async_get_entry(device_entry.primary_config_entry)
    # Check if the device belongs to a monitored integration
    belongs_to_integration = primary_config_entry and primary_config_entry.domain in monitored.keys()
    integration = integrations[primary_config_entry.domain] if belongs_to_integration else None

    if action == "create" and belongs_to_integration:
        # New device for monitored integration, reload configuration
        _LOGGER.info(
            "[%s] Created Device [%s]",
            integration.friendly_name,
            device_entry.name,
        )
        reload = True

    elif action == "update":
        if not belongs_to_integration:
            # Currently not belongs to monitored integrations.
            # Check if the device belonged to a monitored integration before the update.
            # If primary_config_entry is None,
            # and has a config entry which belongs to our integration,
            # the device was deleted from a monitored integration
            belonged_to_integration = False

            if not primary_config_entry:
                for entry_id in device_entry.config_entries:
                    device_config_entry = hass.config_entries.async_get_entry(entry_id)
                    if device_config_entry and device_config_entry.domain == DOMAIN:
                        for monitored_domain, monitored_integration in monitored.items():
                            if device_config_entry.entry_id == monitored_integration.config_entry_id:
                                belonged_to_integration = monitored_domain
                                break
                    if belonged_to_integration:
                        break

            # Devices belonged to monitored integration
            if belonged_to_integration:
                integration = integrations[belonged_to_integration]

                _LOGGER.info(
                    "[%s] Device [%s] no more belongs to integration, "
                    "removing all attached entities",
                    integration.friendly_name,
                    device_entry.name
                )
                # Remove all attached entities
                entity_registry = er.async_get(hass)
                attached_entries = await utils.get_device_entities(
                    hass, device_id, DOMAIN
                )

                for attached_entry in attached_entries:
                    _LOGGER.info(
                        "[%s] Removing attached entity [%s] from device [%s]",
                        integration.friendly_name,
                        attached_entry.name or attached_entry.original_name,
                        device_entry.name,
                    )
                    entity_registry.async_remove(attached_entry.entity_id)

                # Now if device do not belongs on other integrations than this one,
                # we can safely delete it
                if not any(
                    (config_entry := hass.config_entries.async_get_entry(entry_id))
                    and config_entry.domain != DOMAIN
                    for entry_id in device_entry.config_entries
                ):
                    device_registry.async_remove_device(device_id)
                    _LOGGER.info(
                        "[%s] Device [%s] no more belongs to any other integration and "
                        "has been removed",
                        integration.friendly_name,
                        device_entry.name,
                    )

                reload = True

        elif event_changes_has_key(device_event, "disabled_by"):
            # Device belongs to monitored integration and was enabled,
            # find all entities and synchronize status
            _LOGGER.info(
                "[%s] Device [%s] has been [%s], "
                "synchronizing entities status",
                integration.friendly_name,
                device_entry.name,
                "disabled" if device_entry.disabled else "enabled",
            )
            entity_registry = er.async_get(hass)
            attached_entries = await utils.get_device_entities(
                hass, device_id, DOMAIN
            )

            for attached_entry in attached_entries:
                if (
                    not device_entry.disabled
                    and attached_entry.disabled_by is er.RegistryEntryDisabler.USER
                ):
                    _LOGGER.warning(
                        "[%s] Skipping enable for entity [%s] since was disabled by USER",
                        integration.friendly_name,
                        attached_entry.name or attached_entry.original_name,
                    )
                    continue

                if device_entry.disabled != attached_entry.disabled:
                    disabled_by = (
                        er.RegistryEntryDisabler.INTEGRATION
                        if device_entry.disabled
                        else None
                    )
                    entity_registry.async_update_entity(
                        attached_entry.entity_id,
                        disabled_by=disabled_by,
                    )

    if reload:
        _LOGGER.info("[%s] Reloading config entry", integration.friendly_name)
        config_entry = hass.config_entries.async_get_entry(monitored[integration.domain].config_entry_id)

        # Prevent multiple reloads
        if config_entry.runtime_data.reload_task:
            config_entry.runtime_data.reload_task.cancel()

        # Schedule reload with a small delay
        async def delayed_reload() -> None:
            await asyncio.sleep(2)
            await hass.config_entries.async_reload(config_entry.entry_id)
            _LOGGER.info("[%s] Config entry reloaded!", integration.friendly_name)

        config_entry.runtime_data.reload_task = hass.async_create_task(delayed_reload())


async def _entity_registry_updated(
    entity_event: Event, hass: HomeAssistant
) -> None:
    """Handle updates to the entity registry.

    Once a config entry is disabled, it is disabled only if all config entries associated
    to the device are disabled. Since we have attached our config entry to the device and the entry
    is not disabled, the device remains enabled.
    To handle this case, we have to listen to entity registry updates and check if the config entry
    associated to the updated entity is disabled. If true, and after checking some conditions,
    we have to disable the device.
    """
    monitored = hass.data[DATA_CONFIG_KEY].monitored
    entity_id = entity_event.data.get("entity_id")

    # Only events related to disabled_by changes are relevant
    if (
        not entity_id
        or entity_event.data.get("action") != "update"
        # The updated is not related to a disabled_by change
        or not event_changes_has_key(entity_event, "disabled_by")
        # The entity has been enabled
        or entity_event.data.get("changes").get("disabled_by") is not None
    ):
        return

    entity_registry = er.async_get(hass)
    updated_entity = entity_registry.async_get(entity_id)
    if not updated_entity:
        _LOGGER.debug("No entity entry found into registry with id [%s]", entity_id)
        return
    if not updated_entity.config_entry_id:
        _LOGGER.debug("No config_entry_id found for entity entry [%s]", entity_id)
        return
    # If the updated entity belongs to our config entries, nothing to do
    if updated_entity.config_entry_id in [
        monitored_integration.config_entry_id
        for monitored_integration in monitored.values()
    ]:
        return

    # Get config entry for the updated entity
    updated_entity_config_entry = hass.config_entries.async_get_entry(
        updated_entity.config_entry_id
    )

    if not updated_entity_config_entry:
        _LOGGER.debug("No config entry found for entity entry [%s]", entity_id)
        return

    # If config entry associated to the updated entity does not belong to our
    # monitored integration or the updated entity is not associated to any device,
    # nothing to do
    if (
        updated_entity_config_entry.domain not in monitored.keys()
        or not updated_entity.device_id
    ):
        return

    # Get our config entry involved
    config_entry = hass.config_entries.async_get_entry(monitored[updated_entity_config_entry.domain].config_entry_id)

    # If config entry associated to the updated entity is disabled and config entry of
    # our integration is still enabled, we have to check if the device associated with the
    # updated entity has as primary config entry the updated entity config entry and
    # his platform is the monitored integration.
    # If true, and there are no other config entries associated to the device that are
    # enabled, we have to disable the device.
    if updated_entity_config_entry.disabled_by and not config_entry.disabled_by:
        device_registry = dr.async_get(hass)
        device_entry = device_registry.async_get(updated_entity.device_id)
        if not device_entry:
            _LOGGER.debug(
                "No device entry found into registry with id [%s]",
                updated_entity.device_id,
            )
            return
        # Device primary config entry is not the updated entity config entry, nothing to do
        if device_entry.primary_config_entry != updated_entity.config_entry_id:
            return
        # Now check if there are other config entries associated to the device that are enabled
        # if not we have to disable the device
        if not any(
            entry_id not in [config_entry.entry_id, updated_entity.config_entry_id]
            and (other_config_entry := hass.config_entries.async_get_entry(entry_id))
            and not other_config_entry.disabled_by
            for entry_id in device_entry.config_entries
        ):
            _LOGGER.info(
                "Disabling device [%s] as no other config entries are enabled",
                device_entry.name,
            )
            device_registry.async_update_device(
                device_entry.id,
                disabled_by=dr.DeviceEntryDisabler.CONFIG_ENTRY,
            )


async def _state_changed(
    state_event: Event[event.EventStateChangedData],
    hass: HomeAssistant,
) -> None:
    old_state = state_event.data.get("old_state")
    new_state = state_event.data.get("new_state")
    # We are only looking for state changes
    if old_state and new_state and old_state.state == new_state.state:
        return

    entity_registry = er.async_get(hass)
    # Get entity entry from the registry
    if not (entity_entry := entity_registry.async_get(state_event.data.get("entity_id"))):
        return

    # Check if the entity belongs to integration and is the ping status entity
    if not utils.is_tagged_entity_entry(entity_entry, ENTITY_TAG_PING_STATUS):
        return

    _LOGGER.debug(
        "State changed for entity [%s] from [%s] to [%s]",
        entity_entry.name or entity_entry.original_name,
        old_state.state if old_state else None,
        new_state.state if new_state else None,
    )

    hass.bus.async_fire(EVENT_PING_STATUS_UPDATED, state_event.data)


async def _ensure_network_summary_entry_exists(hass: HomeAssistant) -> None:
    """Ensure network summary entry exists."""
    for entry in hass.config_entries.async_entries(DOMAIN):
        if entry.unique_id == NETWORK_SUMMARY_ENTRY_ID:
            return

    _LOGGER.info("Creating network summary entry")
    await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": "network_summary"},
        data={CONF_ENTRY_TYPE: ENTRY_TYPE_NETWORK_SUMMARY},
    )


def event_changes_has_key(evt: Event, key: str) -> bool:
    """Check if changes dict has disabled_by key."""
    changes = evt.data.get("changes")

    return isinstance(changes, dict) and key in changes


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_INTEGRATION:
        domain = entry.data.get(CONF_INTEGRATION)
        hass.data[DATA_CONFIG_KEY].monitored.pop(domain)

    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle removal of an entry."""

