import logging

from .base import BaseHostResolver

from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers import device_registry as dr

_LOGGER = logging.getLogger(__name__)

class LocalTuyaResolver(BaseHostResolver):
    @staticmethod
    def resolve(config_entry: ConfigEntry, device: dr.DeviceEntry) -> str | None:
        tuya_device_id = next(iter(device.identifiers))[1].removeprefix("local_")
        tuya_devices = config_entry.data.get("devices", {})

        if (
            (config_entry_device := tuya_devices.get(tuya_device_id))
            and (host := config_entry_device.get("host"))
        ):
            _LOGGER.debug("Found Host [%s] for Local Tuya device [%s]", host, device.name)
            return host

        return None

