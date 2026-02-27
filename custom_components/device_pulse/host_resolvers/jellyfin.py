import logging
from urllib.parse import urlparse

from .base import BaseHostResolver

from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers import device_registry as dr

_LOGGER = logging.getLogger(__name__)

class JellyfinResolver(BaseHostResolver):
    @staticmethod
    def resolve(config_entry: ConfigEntry, device: dr.DeviceEntry) -> str | None:
        url = config_entry.data.get("url", None)
        parsed = urlparse(url)

        if (host := parsed.hostname):
            _LOGGER.debug("Found Host [%s] for Jellyfin device [%s]", host, device.name)
            return host

        _LOGGER.debug("Found URL [%s] for Jellyfin device [%s], but wasn't able to retrieve host from it", url, device.name)
        return None
