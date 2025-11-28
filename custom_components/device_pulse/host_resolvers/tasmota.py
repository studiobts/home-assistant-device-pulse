import logging

from .base import BaseHostResolver

from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers import device_registry as dr

_LOGGER = logging.getLogger(__name__)

class TasmotaResolver(BaseHostResolver):
    @staticmethod
    def resolve(config_entry: ConfigEntry, device: dr.DeviceEntry) -> str | None:
        return BaseHostResolver.device_configuration_url(device)
