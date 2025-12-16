"""Utility functions for Device Pulse integration."""
from dataclasses import dataclass
import ipaddress
import logging
import re
import socket
from zeroconf.asyncio import AsyncServiceInfo

from homeassistant.config_entries import ConfigEntry, SOURCE_ZEROCONF
from homeassistant.components import zeroconf
from homeassistant.components.network import async_get_adapters, async_get_source_ip, Adapter
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
    custom_group: bool

async def get_valid_integrations_for_monitoring(hass: HomeAssistant) -> dict[str, IntegrationData]:
    """Find all integrations that have devices with a hostname or IP address in the configuration."""
    device_registry = dr.async_get(hass)
    zc = await zeroconf.async_get_instance(hass)
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
        if not is_device_valid_for_monitoring(hass, device_registry, device):
            continue
        # Get the primary config entry for the device
        device_config_entry = hass.config_entries.async_get_entry(device.primary_config_entry)
        # Check if the configuration contains a valid Host parameter
        has_host = await extract_device_host(hass, device, zc, device_config_entry) is not None

        if has_host and device_config_entry.domain not in integrations:
            # Get the friendly name of the integration
            friendly_name = await _get_integration_name(device_config_entry.domain)
            integrations[device_config_entry.domain] = IntegrationData(device_config_entry.domain, friendly_name, 0, False)

        if has_host:
            # Increment the device count for the integration
            integrations[device_config_entry.domain].device_count += 1

    return integrations

async def _async_get_host_from_zeroconf(zc: zeroconf.models.HaZeroconf, config_entry: ConfigEntry) -> str | None:
    try:
        service_type = config_entry.discovery_keys["zeroconf"][0].key[0]
        service_name = config_entry.discovery_keys["zeroconf"][0].key[1]
    except Exception:
        _LOGGER.warning("Unable to get zeroconf discovery info for [%s][%s]: %s", config_entry.domain, config_entry.title, config_entry.discovery_keys)
        return None

    service_info = AsyncServiceInfo(service_type, service_name)

    if await service_info.async_request(zc, timeout=1500):
        for address in service_info.addresses:
            if len(address) == 4:
                return str(ipaddress.IPv4Address(address))

    return None

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
        if is_device_valid_for_monitoring(hass, device_registry, device, integration)
    ]


def is_device_valid_for_monitoring(
    hass: HomeAssistant,
    device_registry: dr.DeviceRegistry,
    device: dr.DeviceEntry,
    integration: IntegrationData | None = None,
) -> bool:
    device_name = device.name_by_user or device.name

    """Check if device is valid for monitoring."""
    if not device.primary_config_entry:
        _LOGGER.info("Device not valid: %s (no primary_config_entry)", device_name)
        return False

    entry = hass.config_entries.async_get_entry(device.primary_config_entry)
    if not entry:
        _LOGGER.info(
            "Device not valid: %s (primary_config_entry %s not found)",
            device_name,
            device.primary_config_entry,
        )
        return False

    # Skip our own devices
    if entry.domain == DOMAIN:
        return False

    # Filter device by integration
    if integration and entry.domain != integration.domain:
        return False

    # Exclude devices connected through another device
    if device.via_device_id:
        # If the parent device's primary config entry is different from the current device's,
        # the current device is considered valid. This ensures that devices managed by different
        # config entries are not excluded, even if they are linked as parent/child.
        # For example, the Fritz!Box integration performs internal matching to associate devices
        # (e.g., a Tasmota device connected via Wi-Fi to the router) as children of its own devices.
        # This logic prevents such associations from invalidating the current device.
        connected_device = device_registry.async_get(device.via_device_id)
        if connected_device and connected_device.primary_config_entry == device.primary_config_entry:
            _LOGGER.debug(
                "Device not valid: %s (connected via_device_id: %s, %s)",
                device_name,
                device.via_device_id,
                connected_device.name_by_user or connected_device.name,
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

def is_valid_ip(value: str) -> bool:
    """Check if a value is a valid IPv4 address."""
    try:
        ipaddress.IPv4Address(value)
        return True
    except ValueError:
        return False

def is_valid_hostname_or_ip(value) -> bool:
    """Check if a value is a valid hostname or IP address."""
    if is_valid_ip(value):
        return True

    # Check hostname (RFC 1123)
    hostname_regex = re.compile(
        r"^(?=.{1,253}$)(?!-)[A-Za-z0-9-]{1,63}(?<!-)(?:\.(?!-)[A-Za-z0-9-]{1,63}(?<!-))*\.?$"
    )
    if hostname_regex.match(value):
        return True

    return False

async def extract_device_host(
    hass: HomeAssistant, device: dr.DeviceEntry, zc: zeroconf.models.HaZeroconf, device_config_entry: ConfigEntry | None = None
) -> str | None:
    """Extract Host for device based on integration type."""
    # Get the primary config entry for the device
    device_config_entry = device_config_entry or hass.config_entries.async_get_entry(
        device.primary_config_entry
    )

    host = None

    if device_config_entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_CUSTOM_GROUP:
        group_devices = device_config_entry.options.get(CONF_GROUP_DEVICES_LIST)
        for group_device in group_devices:
            if next(iter(device.identifiers))[1] == group_device.get(CONF_GROUP_DEVICE_ID):
                host = group_device.get(CONF_GROUP_DEVICE_HOST)
                break
    # Check if there is a Host Resolver for the integration
    elif host := await resolve_host(device_config_entry, device):
        _LOGGER.debug("Found Host '%s' with host resolver for device %s", host, device.name)
    else:
        for param_name in HOST_PARAM_NAMES:
            if param_name in device_config_entry.data:
                host = device_config_entry.data[param_name]
                _LOGGER.debug("Found Host '%s' in data parameter '%s' for device %s",host, param_name, device.name)
                break
            if param_name in device_config_entry.options:
                host = device_config_entry.options[param_name]
                _LOGGER.debug("Found Host '%s' in options parameter '%s' for device %s",host, param_name, device.name)
                break

    # Last chance, check if device was added through zeroconf and query it
    if not host and device_config_entry.source == SOURCE_ZEROCONF:
        if host := await _async_get_host_from_zeroconf(zc, device_config_entry):
            _LOGGER.debug("Found Host '%s' from zeroconf for device %s", host, device.name)

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


async def resolve_hostname_to_ip(hass: HomeAssistant, hostname: str) -> str | None:
    """Resolve a hostname to an IP address."""
    try:
        # Use executor to avoid blocking the event loop
        ip_address = await hass.async_add_executor_job(
            socket.gethostbyname, hostname
        )
        _LOGGER.debug("Resolved hostname %s to IP %s", hostname, ip_address)
        return ip_address
    except socket.gaierror as err:
        _LOGGER.debug("Failed to resolve hostname %s: %s", hostname, err)
        return None
    except Exception as err:
        _LOGGER.warning("Unexpected error resolving hostname %s: %s", hostname, err)
        return None

async def is_arping_available(hass: HomeAssistant) -> bool:
    """Check if arping command is available on the system."""
    import shutil

    try:
        # Check if arping is in PATH
        # noinspection PyUnresolvedReferences,PyTypeChecker
        arping_path = await hass.async_add_executor_job(shutil.which, "arping")
        if arping_path:
            _LOGGER.debug("arping command found at: %s", arping_path)
            return True

        _LOGGER.debug("arping command not found in system PATH")
        return False
    except Exception as err:
        _LOGGER.warning("Error checking arping availability: %s", err)
        return False

async def get_network_adapter_for_ip(hass: HomeAssistant, ip_address: str) -> tuple[Adapter | None, str | None, int | None]:
    """Get the network adapter for an IP address, returns also HA IP address and netmask."""
    ha_ip = await async_get_source_ip(hass, target_ip=ip_address)
    if not ha_ip:
        _LOGGER.debug("Cannot determine Home Assistant IP address")
        return None, None, None

    # Get network adapters information to retrieve actual subnet mask
    adapters = await async_get_adapters(hass)
    if not adapters:
        _LOGGER.debug("Cannot retrieve network adapters information")
        return None, None, None

    # Find the adapter that has the HA IP and get its subnet mask
    for adapter in adapters:
        for ip_info in adapter.get("ipv4", []):
            if ip_info.get("address") == ha_ip:
                return adapter, ha_ip, ip_info.get("network_prefix")

    return None, None, None


async def is_host_in_local_subnet(hass: HomeAssistant, host: str) -> bool | str:
    """Check if a host (IP or hostname) is in the same subnet as Home Assistant.
    If true, returns the IP address of the host. Otherwise, returns False.
    """
    try:
        # Resolve the hostname if needed
        if not is_valid_ip(host):
            host_ip = await resolve_hostname_to_ip(hass, host)
            if not host_ip:
                _LOGGER.debug("Cannot determine subnet for hostname %s: resolution failed", host)
                return False
        else:
            host_ip = host

        # Find the adapter that has the HA IP and get its subnet mask
        adapter, ha_ip, ha_netmask = await get_network_adapter_for_ip(hass, host_ip)
        if not adapter:
            _LOGGER.debug("Cannot determine subnet for IP %s: no matching adapter found", host_ip)
            return False

        # Create networks with actual subnet mask
        host_network = ipaddress.IPv4Network(f"{host_ip}/{ha_netmask}", strict=False)
        ha_network = ipaddress.IPv4Network(f"{ha_ip}/{ha_netmask}", strict=False)

        in_same_subnet = host_network == ha_network

        _LOGGER.debug(
            "Subnet check: host=%s (%s), HA=%s (%s), mask=/%s, same_subnet=%s",
            host,
            host_network,
            ha_ip,
            ha_network,
            ha_netmask,
            in_same_subnet,
        )

        return host_ip if in_same_subnet else False

    except (ValueError, ipaddress.AddressValueError) as err:
        _LOGGER.debug("Error checking subnet for %s: %s", host, err)
        return False
    except Exception as err:
        _LOGGER.warning("Unexpected error checking subnet for %s: %s", host, err)
        return False


async def check_devices_support_arp_ping(
    hass: HomeAssistant, devices: list[dr.DeviceEntry], zc: zeroconf.models.HaZeroconf
) -> tuple[bool, str | None]:
    """Check if at least one device in the list supports ARP ping (is in the local subnet).

    Returns:
        tuple[bool, str | None]: (supports_arp, reason_if_not_supported)
    """
    # First, check if arping is available
    if not await is_arping_available(hass):
        _LOGGER.debug("arping not available, ARP ping not supported")
        return False, "arping_not_installed"

    # Then check if any device is in the local subnet
    for device in devices:
        host = await extract_device_host(hass, device, zc)
        if host and await is_host_in_local_subnet(hass, host):
            return True, None

    return False, "no_local_devices"

