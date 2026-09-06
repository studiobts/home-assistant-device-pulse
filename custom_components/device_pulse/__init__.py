"""Device Pulse Integration."""

import asyncio
import contextlib
from dataclasses import dataclass, field
from functools import partial
import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    SIGNAL_CONFIG_ENTRY_CHANGED,
    ConfigEntry,
    ConfigEntryChange,
    ConfigEntryState,
)
from homeassistant.components.ping import PingDataICMPLib, _can_use_icmp_lib_with_privilege
from .ping_clients import ReapingPingDataSubProcess
from homeassistant.components import zeroconf
from homeassistant.const import (
    ATTR_ENTITY_ID,
    ATTR_DEVICE_ID,
    ATTR_AREA_ID,
    ATTR_LABEL_ID,
    ATTR_FLOOR_ID
)
from homeassistant.core import Event, HomeAssistant, ServiceCall
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import event
from homeassistant.helpers import target as target_helpers
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.typing import ConfigType
from homeassistant.util.hass_dict import HassKey

from . import utils
from . import websocket_api
from .arping import PingDataARP
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
    CONF_PING_REQUESTS_PER_ATTEMPT,
    CONF_PING_INTERVAL,
    CONF_PING_METHOD,
    CONF_LOG_LEVEL_DEVICE_OFFLINE,
    CONF_LOG_LEVEL_FAILED_PINGS,
    CONF_SELECTED_DEVICES,
    DEFAULT_PING_ATTEMPTS_BEFORE_FAILURE,
    DEFAULT_PING_REQUESTS_PER_ATTEMPT,
    DEFAULT_PING_INTERVAL,
    DEFAULT_PING_METHOD,
    DEFAULT_LOG_LEVEL_DEVICE_OFFLINE,
    DEFAULT_LOG_LEVEL_FAILED_PINGS,
    DEVICE_SELECTION_ALL,
    DEVICE_SELECTION_EXCLUDE,
    DEVICE_SELECTION_INCLUDE,
    DOMAIN,
    ENTITY_TAG_PING_STATUS,
    ENTITY_TAG_TOTAL_FAILED_PINGS_COUNT,
    ENTRY_TYPE_CUSTOM_GROUP,
    ENTRY_TYPE_INTEGRATION,
    ENTRY_TYPE_NETWORK_SUMMARY,
    EVENT_PING_STATUS_UPDATED,
    EVENT_DEVICE_WENT_OFFLINE,
    EVENT_DEVICE_CAME_ONLINE,
    NETWORK_SUMMARY_ENTRY_ID,
    PING_METHOD_ARP,
    PING_METHOD_ICMP,
    PLATFORMS,
    SERVICE_RESET_TOTAL_FAILED_PINGS,
)
from .coordinator import DevicePingCoordinator

_LOGGER = logging.getLogger(__name__)

DATA_CONFIG_KEY: HassKey["ConfigData"] = HassKey(DOMAIN)

CONFIG_SCHEMA = cv.empty_config_schema(DOMAIN)

RESET_TOTAL_FAILED_PINGS_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_ENTITY_ID): vol.Any(None, cv.entity_ids),
        vol.Optional(ATTR_DEVICE_ID): vol.Any(None, str, [str]),
        vol.Optional(ATTR_AREA_ID): vol.Any(None, str, [str]),
        vol.Optional(ATTR_LABEL_ID): vol.Any(None, str, [str]),
        vol.Optional(ATTR_FLOOR_ID): vol.Any(None, str, [str]),
    },
    extra=vol.ALLOW_EXTRA,
)

@dataclass
class ConfigMonitoredIntegrationData:
    """Holds configuration data for a monitored config entry."""

    domain: str
    config_entry_id: str


@dataclass
class ConfigData:
    """Holds configuration data for the Device Pulse integration."""

    ping_icmp_privileged: bool | None # Flag to true if privileged ICMP ping is available
    ping_arp_available: bool | None # Flag to true if ARP ping is available
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


def _coerce_log_level(value: Any, default: int) -> int:
    """Return a logging level accepted by Logger.log."""
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        if value.isdecimal():
            return int(value)
    return default


async def _async_handle_reset_total_failed_pings_service(
    hass: HomeAssistant,
    call: ServiceCall,
) -> None:
    """Handle the reset total failed pings service."""
    target_selection = target_helpers.TargetSelection(call.data)
    if not target_selection.has_any_target:
        raise ServiceValidationError(
            "No entity, device, area, floor, or label target provided"
        )

    referenced = target_helpers.async_extract_referenced_entity_ids(
        hass,
        target_selection,
        primary_entities_only=False,
    )
    entity_registry = er.async_get(hass)
    entity_ids = referenced.referenced | referenced.indirectly_referenced
    reset_devices: set[str] = set()

    for entity_id in entity_ids:
        entity_entry = entity_registry.async_get(entity_id)
        if not utils.is_tagged_entity_entry(
            entity_entry,
            ENTITY_TAG_TOTAL_FAILED_PINGS_COUNT,
        ):
            continue

        device_id = entity_entry.device_id
        if not device_id:
            raise ServiceValidationError(f"Device not found for entity: {entity_id}")

        if device_id in reset_devices:
            continue

        for config_entry in hass.config_entries.async_entries(DOMAIN):
            runtime_data = getattr(config_entry, "runtime_data", None)
            if (
                runtime_data
                and (monitored := runtime_data.monitored.get(device_id))
            ):
                monitored.coordinator.reset_total_failed_pings(entity_id)
                reset_devices.add(device_id)
                break
        else:
            raise ServiceValidationError(
                f"Device Pulse coordinator not found for entity: {entity_id}"
            )

    if not reset_devices:
        raise ServiceValidationError(
            "No Device Pulse total failed pings sensors found in target"
        )


async def _async_get_or_create_integration(
    hass: HomeAssistant, domain: str, zc: zeroconf.models.HaZeroconf | None = None
) -> utils.IntegrationData:
    """Return integration data, refreshing the cache or creating a fallback."""
    integrations = hass.data[DATA_CONFIG_KEY].integrations
    if integration := integrations.get(domain):
        return integration

    if zc is None:
        zc = await zeroconf.async_get_instance(hass)

    integrations = await utils.get_valid_integrations_for_monitoring(hass, zc)
    hass.data[DATA_CONFIG_KEY].integrations = integrations

    if integration := integrations.get(domain):
        return integration

    friendly_name = await utils.async_get_integration_name(hass, domain)
    integration = utils.IntegrationData(domain, friendly_name, 0, False)
    integrations[domain] = integration
    return integration


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the integration."""
    # Determine if privileged ICMP ping is available
    ping_icmp_privileged = await _can_use_icmp_lib_with_privilege()
    _LOGGER.info("Privileged ICMP ping available: %s", ping_icmp_privileged)

    # Check if arping is available for ARP ping support
    if ping_arp_available := await utils.is_arping_available(hass):
        _LOGGER.info("ARP ping support available (arping command found)")
    else:
        _LOGGER.warning(
            "ARP ping support not available (arping command not found). "
            "Install iputils-arping package to enable ARP ping functionality"
        )

    zc = await zeroconf.async_get_instance(hass)
    # Build initial list of integrations valid for monitoring
    integrations = await utils.get_valid_integrations_for_monitoring(hass, zc)
    _LOGGER.info("Found %d valid integrations for monitoring: %s",
        len(integrations),
        [integration.friendly_name for integration in integrations.values()]
    )
    # Store in hass data
    hass.data[DATA_CONFIG_KEY] = ConfigData(
        ping_icmp_privileged,
        ping_arp_available,
        integrations
    )

    # Register listener for config entry updates
    async_dispatcher_connect(hass, SIGNAL_CONFIG_ENTRY_CHANGED, partial(_config_entry_updated, hass=hass))
    # Register listeners for device registry updates
    hass.bus.async_listen(dr.EVENT_DEVICE_REGISTRY_UPDATED, partial(_device_registry_updated, hass=hass))
    # Register listener for state changes of our entities
    event.async_track_state_change_filtered(
        hass, event.TrackStates(
            all_states=False,
            entities=set(),
            domains={"binary_sensor"}
        ),
        partial(_state_changed, hass=hass)
    )
    # Register service for total failed pings reset
    hass.services.async_register(
        DOMAIN,
        SERVICE_RESET_TOTAL_FAILED_PINGS,
        partial(_async_handle_reset_total_failed_pings_service, hass),
        schema=RESET_TOTAL_FAILED_PINGS_SCHEMA,
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
            if domain not in hass.data[DATA_CONFIG_KEY].integrations:
                hass.data[DATA_CONFIG_KEY].integrations = await utils.get_valid_integrations_for_monitoring(hass, zc)
                _LOGGER.info("Update cache: found %d valid integrations for monitoring: %s",
                    len(hass.data[DATA_CONFIG_KEY].integrations),
                    [integration.friendly_name for integration in hass.data[DATA_CONFIG_KEY].integrations.values()]
                )
            # Get integration data (fallback if still missing)
            integration = await _async_get_or_create_integration(hass, domain, zc)

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
        ping_requests_per_attempt: int = int(config_entry.options.get(CONF_PING_REQUESTS_PER_ATTEMPT, DEFAULT_PING_REQUESTS_PER_ATTEMPT))
        ping_interval: int = int(config_entry.options.get(CONF_PING_INTERVAL, DEFAULT_PING_INTERVAL))
        ping_method: str = config_entry.options.get(CONF_PING_METHOD, DEFAULT_PING_METHOD)
        log_level_failed_pings = _coerce_log_level(
            config_entry.options.get(
                CONF_LOG_LEVEL_FAILED_PINGS, DEFAULT_LOG_LEVEL_FAILED_PINGS
            ),
            DEFAULT_LOG_LEVEL_FAILED_PINGS,
        )
        log_level_device_offline = _coerce_log_level(
            config_entry.options.get(
                CONF_LOG_LEVEL_DEVICE_OFFLINE, DEFAULT_LOG_LEVEL_DEVICE_OFFLINE
            ),
            DEFAULT_LOG_LEVEL_DEVICE_OFFLINE,
        )

        _LOGGER.info("[%s]   Attempts Before Failure: %d", integration.friendly_name, ping_attempts_before_failure)
        _LOGGER.info("[%s]   Requests per Attempt: %d", integration.friendly_name, ping_requests_per_attempt)
        _LOGGER.info("[%s]   Interval: %ds", integration.friendly_name, ping_interval)
        _LOGGER.info("[%s]   Ping Method: %s", integration.friendly_name, ping_method)
        _LOGGER.info("[%s]   Failed Pings Log Level: %s",integration.friendly_name, logging.getLevelName(log_level_failed_pings))
        _LOGGER.info("[%s]   Device Offline Log Level: %s",integration.friendly_name, logging.getLevelName(log_level_device_offline))
        _LOGGER.info("[%s] Found [%d] valid devices", integration.friendly_name, len(devices))

        # Determine the ICMP ping client based on method and privileges.
        # Use ReapingPingDataSubProcess (instead of the core PingDataSubProcess)
        # when pinging via the subprocess so that the child "ping" process is
        # killed when the refresh task gets cancelled on unload/reload/shutdown.
        ping_icmp: type[PingDataICMPLib | ReapingPingDataSubProcess]
        ping_icmp_privileged = hass.data[DATA_CONFIG_KEY].ping_icmp_privileged
        ping_icmp = ReapingPingDataSubProcess if ping_icmp_privileged is None else PingDataICMPLib

        ping_arp: type[PingDataARP] | None = None
        if ping_method == PING_METHOD_ARP:
            # Verify arping is available when the ARP method is selected
            if not hass.data[DATA_CONFIG_KEY].ping_arp_available:
                _LOGGER.error(
                    "[%s] ARP ping method selected but arping command not found. "
                    "Please install iputils-arping package. Falling back to ICMP ping",
                    integration.friendly_name,
                )
            else:
                ping_arp = PingDataARP

        disabled_devices = []

        for device in devices:
            # Extract host for the device
            host, host_source = await utils.extract_device_host(hass, device, zc)

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

                # For ARP ping, check if device ip address is in local subnet,
                # otherwise fallback to ICMP ping
                if ping_arp and (resolved_ip := await utils.is_host_in_local_subnet(hass, host)):
                    ping_instance = PingDataARP(hass, resolved_ip, ping_requests_per_attempt)
                else:
                    ping_instance = ping_icmp(hass, host, ping_requests_per_attempt, ping_icmp_privileged)

                coordinator = DevicePingCoordinator(
                    hass,
                    config_entry,
                    integration,
                    device,
                    host_source,
                    ping_instance,
                    ping_attempts_before_failure,
                    ping_requests_per_attempt,
                    ping_interval,
                    log_level_failed_pings,
                    log_level_device_offline,
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
                _LOGGER.warning("[%s] Could not extract Host for device [%s]",integration.friendly_name, device.name)

        for disabled_device in disabled_devices:
            _LOGGER.warning("[%s] Keep device [%s] disabled", integration.friendly_name, disabled_device.name)
            device_registry.async_update_device(disabled_device.id, disabled_by=disabled_device.disabled_by)

    await hass.config_entries.async_forward_entry_setups(config_entry, PLATFORMS)

    return True


async def _config_entry_updated(
    change: ConfigEntryChange, updated_config_entry: ConfigEntry, hass: HomeAssistant
) -> None:
    """Handle updates to a config entry."""
    monitored = hass.data[DATA_CONFIG_KEY].monitored

    # Only disabled config entry updates are relevant
    if change != ConfigEntryChange.UPDATED or updated_config_entry.disabled_by is None:
        return
    # If the updated config entry belongs to our config entries, nothing to do
    if updated_config_entry.domain == DOMAIN:
        return
    # If the updated config entry does not belong to our monitored integration, nothing to do
    if updated_config_entry.domain not in monitored.keys():
        return

    # Get our config entry involved
    config_entry = hass.config_entries.async_get_entry(monitored[updated_config_entry.domain].config_entry_id)

    # If config entry of our integration is still enabled,
    # and there are no other config entries enabled associated to the devices,
    # we have to disable these devices to remain in sync with the monitored integration.
    if not config_entry.disabled_by:
        device_registry = dr.async_get(hass)
        # Get all devices related to the updated config entry
        devices = dr.async_entries_for_config_entry(device_registry, updated_config_entry.entry_id)
        if not devices:
            _LOGGER.debug(
                "No device entries found into registry for config entry [%s][%s]",
            updated_config_entry.title,
                updated_config_entry.entry_id
            )
            return

        for device_entry in devices:
            # Device primary config entry is not the updated config entry, nothing to do
            if device_entry.primary_config_entry != updated_config_entry.entry_id:
                return
            # Now check if there are other config entries associated to the device that are enabled
            # if not we have to disable the device
            if not any(
                entry_id not in [config_entry.entry_id, updated_config_entry.entry_id]
                and (other_config_entry := hass.config_entries.async_get_entry(entry_id))
                and not other_config_entry.disabled_by
                for entry_id in device_entry.config_entries
            ):
                integrations = hass.data[DATA_CONFIG_KEY].integrations
                integration = integrations.get(updated_config_entry.domain)
                _LOGGER.info(
                    "[%s] Disabling device [%s] as no other config entries are enabled",
                    integration.friendly_name,
                    device_entry.name,
                )
                device_registry.async_update_device(
                    device_entry.id,
                    disabled_by=dr.DeviceEntryDisabler.CONFIG_ENTRY,
                )


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
    integration = (
        await _async_get_or_create_integration(hass, primary_config_entry.domain)
        if belongs_to_integration
        else None
    )

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
                integration = await _async_get_or_create_integration(hass, belonged_to_integration)

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
        if config_entry is None:
            return

        # Prevent multiple reloads. The task is created as a config entry
        # background task so that the core cancels it automatically when the
        # entry is unloaded (during a reload/restart). This avoids a stale
        # reload firing against an already unloaded entry.
        if config_entry.runtime_data.reload_task:
            config_entry.runtime_data.reload_task.cancel()

        # Schedule reload with a small delay
        async def delayed_reload() -> None:
            await asyncio.sleep(2)
            # Skip the reload if the entry is no longer loaded (e.g. the
            # entry was removed/disabled or HA is shutting down meanwhile).
            if hass.is_stopping or config_entry.state != ConfigEntryState.LOADED:
                return
            await hass.config_entries.async_reload(config_entry.entry_id)
            _LOGGER.info("[%s] Config entry reloaded!", integration.friendly_name)

        config_entry.runtime_data.reload_task = config_entry.async_create_background_task(
            hass,
            delayed_reload(),
            name=f"Device Pulse reload {integration.friendly_name}",
            eager_start=True,
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

    # Cancel any pending reload task so it does not fire against an entry that
    # is being (or has just been) unloaded.
    reload_task = getattr(entry, "runtime_data", None) and entry.runtime_data.reload_task
    if reload_task:
        entry.runtime_data.reload_task = None
        reload_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await reload_task

    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle removal of an entry."""
