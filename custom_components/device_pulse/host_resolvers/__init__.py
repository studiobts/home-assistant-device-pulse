import asyncio
import importlib
import pkgutil
from .base import BaseHostResolver

from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers import device_registry as dr

_resolvers_cache: dict[str, type[BaseHostResolver]] | None = None


async def discover_resolvers() -> dict[str, type[BaseHostResolver]]:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _discover_resolvers)


def _discover_resolvers() -> dict[str, type[BaseHostResolver]]:
    global _resolvers_cache
    if _resolvers_cache is not None:
        return _resolvers_cache

    resolvers = {}
    package_path = __path__
    package_name = __name__

    for _, module_name, _ in pkgutil.iter_modules(package_path):
        module = importlib.import_module(f"{package_name}.{module_name}")
        for attr_name in dir(module):
            attr = getattr(module, attr_name)
            if (
                isinstance(attr, type)
                and issubclass(attr, BaseHostResolver)
                and attr is not BaseHostResolver
            ):
                resolvers[module_name] = attr

    _resolvers_cache = resolvers

    return resolvers


async def resolve(config_entry: ConfigEntry, device: dr.DeviceEntry) -> str | None:
    resolvers = await discover_resolvers()
    domain = config_entry.domain

    if not (resolver := resolvers.get(domain)):
        return None

    return resolver.resolve(config_entry, device)
