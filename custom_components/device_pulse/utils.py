"""Utility functions for Device Pulse integration."""
from dataclasses import dataclass
import ipaddress
import logging
import re

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.loader import async_get_integration
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_registry import RegistryEntry as EntityEntry

from .const import (
    DOMAIN,
    HOST_PARAM_NAMES,
    CONF_ENTRY_TYPE,
    ENTRY_TYPE_CUSTOM_GROUP,
    CONF_GROUP_DEVICES_LIST,
    CONF_GROUP_DEVICE_ID,
    CONF_GROUP_DEVICE_HOST,
)
from .host_resolvers import resolve as resolve_host

_LOGGER = logging.getLogger(__name__)

@dataclass
class IntegrationData:
    """Holds integration data."""
    domain: str
    friendly_name: str
    device_count: int

async def get_valid_integrations_for_monitoring(hass: HomeAssistant) -> dict[str, IntegrationData]:
    """Find all integrations that have devices with a hostname or IP address in the configuration."""
    device_registry = dr.async_get(hass)
    integrations: dict[str, IntegrationData] = {}

    all_devices = list(device_registry.devices.values())

    async def _get_integration_name(domain: str) -> str:
        try:
            integration = await async_get_integration(hass, domain)
        except Exception:  # noqa: BLE001
            return domain.replace("_", " ").title()
        else:
            return integration.name

    for device in all_devices:
        if not is_device_valid_for_monitoring(hass, device):
            continue
        # Get the primary config entry for the device
        config_entry = hass.config_entries.async_get_entry(device.primary_config_entry)
        # Check if the configuration contains a valid Host parameter
        has_host = await extract_device_host(hass, device, config_entry) is not None

        if has_host and config_entry.domain not in integrations:
            # Get the friendly name of the integration
            friendly_name = await _get_integration_name(config_entry.domain)
            integrations[config_entry.domain] = IntegrationData(config_entry.domain, friendly_name, 0)

        if has_host:
            # Increment the device count for the integration
            integrations[config_entry.domain].device_count += 1

    return integrations

async def get_device_entities(
    hass: HomeAssistant,
    device_id: str,
    platform: str | None = None,
    domain: str | None = None,
) -> list[EntityEntry]:
    """Return a list of EntityEntry objects associated with a given device_id.

    Optionally filter by platform (integration providing the entity)
    or by domain (entity domain, e.g. 'sensor', 'switch', etc.).
    """
    entity_registry = er.async_get(hass)
    entity_entries = []

    for entity_entry in entity_registry.entities.values():
        if entity_entry.device_id != device_id:
            continue

        if platform is not None and entity_entry.platform != platform:
            continue

        if domain is not None and entity_entry.domain != domain:
            continue

        entity_entries.append(entity_entry)

    return entity_entries


def remove_config_entry_orphan_entities(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    entities: list[Entity],
    domain: str,
) -> None:
    """Remove orphan entities for a given config entry."""
    entity_registry = er.async_get(hass)
    integration = config_entry.runtime_data.integration
    valid_unique_ids = [valid_entry.unique_id for valid_entry in entities]

    # Find all entities for this config entry that are not in the valid list
    orphan_entities = [
        entity_entry
        for entity_entry in entity_registry.entities.values()
        if (
            entity_entry.config_entry_id == config_entry.entry_id
            and entity_entry.unique_id not in valid_unique_ids
            and entity_entry.platform == DOMAIN
            and entity_entry.domain == domain
        )
    ]

    for orphan_entity in orphan_entities:
        entity_registry.async_remove(orphan_entity.entity_id)
        _LOGGER.warning(
            "[%s] Removed orphan entity [%s]",
            integration.friendly_name,
            orphan_entity.name or orphan_entity.original_name,
        )

    # Clean up orphan devices
    device_registry = dr.async_get(hass)
    devices = dr.async_entries_for_config_entry(device_registry, config_entry.entry_id)

    for device in devices:
        # Check if the device has entities associated
        device_entities = [
            device_entity
            for device_entity in er.async_entries_for_device(
                entity_registry, device.id, include_disabled_entities=True
            )
            if device_entity.platform == DOMAIN
        ]

        if not device_entities:
            device_registry.async_update_device(
                device.id, remove_config_entry_id=config_entry.entry_id
            )
            _LOGGER.warning(
                "[%s] Unlinked orphan device [%s]",
                integration.friendly_name,
                device.name_by_user or device.name,
            )


async def get_integration_devices_valid(hass: HomeAssistant, integration: IntegrationData) -> list:
    """Find all valid devices for the integration including disabled ones."""
    device_registry = dr.async_get(hass)

    return [
        device
        for device in device_registry.devices.values()
        if is_device_valid_for_monitoring(hass, device, integration)
    ]


def is_device_valid_for_monitoring(
    hass: HomeAssistant,
    device: dr.DeviceEntry,
    integration: IntegrationData | None = None,
) -> bool:
    """Check if device is valid for monitoring."""
    entry = hass.config_entries.async_get_entry(device.primary_config_entry)
    if not entry:
        _LOGGER.info(
            "Device not valid: %s (primary_config_entry %s not found)",
            device.name,
            device.primary_config_entry,
        )
        return False

    # Skip our own devices
    if entry.domain == DOMAIN:
        return False

    # Exclude devices connected through another device
    if device.via_device_id:
        _LOGGER.info(
            "Device not valid: %s (connected via_device_id: %s)",
            device.name,
            device.via_device_id,
        )
        return False

    if not device.primary_config_entry:
        _LOGGER.info("Device not valid: %s (no primary_config_entry)", device.name)
        return False

    # Filter device by integration
    if integration and entry.domain != integration.domain:
        _LOGGER.debug(
            "Device not valid: %s (config entry domain %s does not match %s)",
            device.name,
            entry.domain,
            integration.domain,
        )
        return False

    return True


def is_tagged_entity_entry(entry: EntityEntry, tag: str) -> bool:
    """Check if entity is a tagged entity entry of the integration."""
    return (
        entry
        and entry.platform == DOMAIN
        and tag in entry.unique_id
    )


def is_valid_hostname_or_ip(value) -> bool:
    # Prova IPv4
    try:
        ipaddress.IPv4Address(value)
        return True
    except ValueError:
        pass

    # Check hostname (RFC 1123)
    hostname_regex = re.compile(
        r"^(?=.{1,253}$)(?!-)[A-Za-z0-9-]{1,63}(?<!-)(\.(?!-)[A-Za-z0-9-]{1,63}(?<!-))*$"
    )
    if hostname_regex.match(value):
        return True

    return False

async def extract_device_host(
    hass: HomeAssistant, device: dr.DeviceEntry, config_entry: ConfigEntry | None = None
) -> str | None:
    """Extract Host for device based on integration type."""
    # Get the primary config entry for the device
    config_entry = config_entry or hass.config_entries.async_get_entry(
        device.primary_config_entry
    )

    host = None

    if config_entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_CUSTOM_GROUP:
        group_devices = config_entry.options.get(CONF_GROUP_DEVICES_LIST)
        for group_device in group_devices:
            if next(iter(device.identifiers))[1] == group_device.get(CONF_GROUP_DEVICE_ID):
                host = group_device.get(CONF_GROUP_DEVICE_HOST)
                break
    # Check if there is a Host Resolver for the integration
    elif host := await resolve_host(config_entry, device):
        _LOGGER.debug("Found Host '%s' with host resolver for device %s", host, device.name)
    else:
        for param_name in HOST_PARAM_NAMES:
            if param_name in config_entry.data:
                host = config_entry.data[param_name]
                _LOGGER.debug("Found Host '%s' in data parameter '%s' for device %s",host, param_name, device.name)
                break
            if param_name in config_entry.options:
                host = config_entry.options[param_name]
                _LOGGER.debug("Found Host '%s' in options parameter '%s' for device %s",host, param_name, device.name)
                break

    # Validate the host value
    return host if host and is_valid_hostname_or_ip(host) else None

def format_duration(seconds: float) -> str:
    """Convert a duration in seconds into a human-readable string (%d %h %m %s)."""
    seconds = round(seconds)
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, secs = divmod(rem, 60)

    parts: list[str] = []
    if days:
        parts.append(f"{days}d")
    if hours or days:
        parts.append(f"{hours}h")
    if minutes or hours or days:
        parts.append(f"{minutes}m")

    parts.append(f"{secs}s")

    return " ".join(parts)
