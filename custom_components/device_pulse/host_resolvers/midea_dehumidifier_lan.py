import logging

from .base import BaseHostResolver

from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers import device_registry as dr

_LOGGER = logging.getLogger(__name__)

class MideaDehumidifierLanResolver(BaseHostResolver):
    @staticmethod
    def resolve(config_entry: ConfigEntry, device: dr.DeviceEntry) -> str | None:
        for config_entry_device in config_entry.data.get("devices", []):
            if (
                config_entry_device.get("discovery") == "LAN"
                and (ip_address := config_entry_device.get("ip_address"))
                and config_entry_device.get("unique_id") == next(iter(device.identifiers))[1]
            ):
                _LOGGER.debug("Found Host [%s] for Midea dehumidifier LAN device [%s]", ip_address, device.name)
                return ip_address

        return None

