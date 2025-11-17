"""Config flow for Device Pulse integration."""

import abc
import copy
from typing import Any, Protocol, runtime_checkable

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import selector
import homeassistant.helpers.device_registry as dr
from homeassistant.util import uuid

from .const import (
    CONF_DEVICE_SELECTION_MODE,
    CONF_ENTRY_TYPE,
    CONF_INTEGRATION,
    CONF_PING_ATTEMPTS_BEFORE_FAILURE,
    CONF_PING_INTERVAL,
    CONF_SELECTED_DEVICES,
    CONF_SENSORS_INTEGRATION_SUMMARY_ENABLED,
    CONF_SENSORS_DISCONNECTED_SINCE_ENABLED,
    CONF_SENSORS_FAILED_PINGS_ENABLED,
    CONF_SENSORS_LAST_RESPONSE_TIME_ENABLED,
    CONF_GROUP_ID,
    CONF_GROUP_NAME,
    CONF_GROUP_DEVICES_LIST,
    CONF_GROUP_DEVICE_ID,
    CONF_GROUP_DEVICE_NAME,
    CONF_GROUP_DEVICE_HOST,
    DEFAULT_PING_ATTEMPTS_BEFORE_FAILURE,
    DEFAULT_PING_INTERVAL,
    DEFAULT_SENSORS_INTEGRATION_SUMMARY_ENABLED,
    DEFAULT_SENSORS_DISCONNECTED_SINCE_ENABLED,
    DEFAULT_SENSORS_FAILED_PINGS_ENABLED,
    DEFAULT_SENSORS_LAST_RESPONSE_TIME_ENABLED,
    DEVICE_SELECTION_ALL,
    DEVICE_SELECTION_EXCLUDE,
    DEVICE_SELECTION_INCLUDE,
    DOMAIN,
    ENTRY_TYPE_CUSTOM_GROUP,
    ENTRY_TYPE_INTEGRATION,
    ENTRY_TYPE_NETWORK_SUMMARY,
    NETWORK_SUMMARY_ENTRY_ID,
)
from .utils import (
    IntegrationData,
    format_duration,
    get_integration_devices_valid,
    get_valid_integrations_for_monitoring,
    is_valid_hostname_or_ip,
)

GROUP_EDIT_ADD_DEVICE = "group_edit_add_device"
GROUP_EDIT_REMOVE_DEVICES = "group_edit_remove_devices"
GROUP_EDIT_UPDATE_DEVICE = "group_edit_update_device"
GROUP_EDIT_CHANGE_SETTING = "group_edit_change_settings"

@runtime_checkable
class _FlowProtocol(Protocol):
    hass: HomeAssistant

    def async_show_form(
        self,
        *,
        step_id: str | None = None,
        data_schema: vol.Schema | None = None,
        errors: dict[str, str] | None = None,
        description_placeholders: dict[str, str] | None = None,
        last_step: bool | None = None,
        preview: str | None = None,
    ): ...


class DevicePingMonitorBaseFlow(abc.ABC, _FlowProtocol):
    """Base class for shared ConfigFlow and OptionsFlow logic."""
    entry_type: str | None = None
    available_integrations: dict[str, IntegrationData] | None = None

    integration_selected: IntegrationData | None = None
    integration_device_selection_mode = DEVICE_SELECTION_ALL
    integration_available_devices = []
    integration_selected_devices = []

    custom_group_name: str | None = None
    custom_group_devices: list[dict[str, str]] = []
    custom_group_edit_action = None
    custom_group_edit_update_device_id = None

    ping_attempts_before_failure: int = DEFAULT_PING_ATTEMPTS_BEFORE_FAILURE
    ping_interval: int = DEFAULT_PING_INTERVAL
    sensors_integration_summary_enabled = DEFAULT_SENSORS_INTEGRATION_SUMMARY_ENABLED
    sensors_failed_pings_enabled = DEFAULT_SENSORS_FAILED_PINGS_ENABLED
    sensors_disconnected_since_enabled = DEFAULT_SENSORS_DISCONNECTED_SINCE_ENABLED
    sensors_last_response_time_enabled = DEFAULT_SENSORS_LAST_RESPONSE_TIME_ENABLED

    async def async_step_monitor_parameters(self, user_input: dict[str, Any] | None = None):
        """Handle the parameters configuration step."""
        errors = {}

        if user_input is not None:
            self.ping_attempts_before_failure = int(user_input[CONF_PING_ATTEMPTS_BEFORE_FAILURE])
            self.ping_interval = int(user_input[CONF_PING_INTERVAL])

            return await self.async_step_monitor_sensors()

        data_schema = vol.Schema(
            {
                vol.Required(
                    CONF_PING_ATTEMPTS_BEFORE_FAILURE,
                    default=self.ping_attempts_before_failure,
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=1,
                        max=10,
                        step=1,
                        mode=selector.NumberSelectorMode.BOX,
                    )
                ),
                vol.Required(
                    CONF_PING_INTERVAL, default=self.ping_interval
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=10,
                        max=600,
                        step=10,
                        mode=selector.NumberSelectorMode.BOX,
                        unit_of_measurement="seconds",
                    )
                ),
            }
        )

        return self.async_show_form(
            step_id="monitor_parameters",
            data_schema=data_schema,
            errors=errors,
            last_step=False,
        )

    async def async_step_monitor_sensors(self, user_input: dict[str, Any] | None = None):
        """Handle the sensors options step."""
        if user_input is not None:
            self.sensors_integration_summary_enabled = bool(user_input[CONF_SENSORS_INTEGRATION_SUMMARY_ENABLED])
            self.sensors_failed_pings_enabled = bool(user_input[CONF_SENSORS_FAILED_PINGS_ENABLED])
            self.sensors_disconnected_since_enabled = bool(user_input[CONF_SENSORS_DISCONNECTED_SINCE_ENABLED])
            self.sensors_last_response_time_enabled = bool(user_input[CONF_SENSORS_LAST_RESPONSE_TIME_ENABLED])

            if self.entry_type == ENTRY_TYPE_INTEGRATION:
                return await self.async_step_integration_summary()
            elif self.entry_type == ENTRY_TYPE_CUSTOM_GROUP:
                return await self.async_step_custom_group_summary()
            else:
                return self.async_abort(reason="unknown_config_entry_type")

        data_schema = vol.Schema(
            {
                vol.Optional(
                    CONF_SENSORS_INTEGRATION_SUMMARY_ENABLED,
                    default=self.sensors_integration_summary_enabled,
                ): bool,
                vol.Optional(
                    CONF_SENSORS_FAILED_PINGS_ENABLED,
                    default=self.sensors_failed_pings_enabled,
                ): bool,
                vol.Optional(
                    CONF_SENSORS_DISCONNECTED_SINCE_ENABLED,
                    default=self.sensors_disconnected_since_enabled,
                ): bool,
                vol.Optional(
                    CONF_SENSORS_LAST_RESPONSE_TIME_ENABLED,
                    default=self.sensors_last_response_time_enabled,
                ): bool,
            }
        )

        return self.async_show_form(
            step_id="monitor_sensors",
            data_schema=data_schema,
            last_step=False,
            description_placeholders={
                "subject":
                    self.integration_selected.friendly_name
                    if self.entry_type == ENTRY_TYPE_INTEGRATION
                    else self.custom_group_name,
            },
        )

    def _get_sensors_summary(self) -> str:
        sensors_enabled = []
        if self.sensors_integration_summary_enabled:
            sensors_enabled.append("Group Summary")
        if self.sensors_failed_pings_enabled:
            sensors_enabled.append("Failed Pings")
        if self.sensors_disconnected_since_enabled:
            sensors_enabled.append("Disconnected Since")
        if self.sensors_last_response_time_enabled:
            sensors_enabled.append("Last Response Time")

        sensors_summary = (
            f"{', '.join(sensors_enabled)}"
            if sensors_enabled
            else "No Extra Sensors Enabled"
        )

        return sensors_summary

    async def async_step_integration_device_selection_mode(self, user_input: dict[str, Any] | None = None):
        """Handle device selection mode step."""
        errors = {}

        if user_input is not None:
            self.integration_device_selection_mode = user_input[CONF_DEVICE_SELECTION_MODE]

            if self.integration_device_selection_mode == DEVICE_SELECTION_EXCLUDE:
                return await self.async_step_integration_select_excluded_devices()
            elif self.integration_device_selection_mode == DEVICE_SELECTION_INCLUDE:
                return await self.async_step_integration_select_included_devices()

            return await self.async_step_monitor_parameters()

        self.integration_available_devices = await get_integration_devices_valid(self.hass, self.integration_selected)

        device_count = len(self.integration_available_devices)
        data_schema = vol.Schema(
            {
                vol.Required(
                    CONF_DEVICE_SELECTION_MODE, default=self.integration_device_selection_mode
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[DEVICE_SELECTION_ALL, DEVICE_SELECTION_EXCLUDE, DEVICE_SELECTION_INCLUDE],
                        translation_key=CONF_DEVICE_SELECTION_MODE,
                        mode=selector.SelectSelectorMode.LIST,
                        sort=True,
                    )
                )
            }
        )

        return self.async_show_form(
            step_id="integration_device_selection_mode",
            data_schema=data_schema,
            errors=errors,
            last_step=False,
            description_placeholders={
                "integration_name": self.integration_selected.friendly_name,
                "device_count": str(device_count),
            },
        )

    async def async_step_integration_select_excluded_devices(self, user_input: dict[str, Any] | None = None):
        """Handle device selection step."""
        return await self._async_step_integration_select_devices(user_input)

    async def async_step_integration_select_included_devices(self, user_input: dict[str, Any] | None = None):
        """Handle device selection step."""
        return await self._async_step_integration_select_devices(user_input)

    async def _async_step_integration_select_devices(self, user_input: dict[str, Any] | None = None):
        """Handle device selection step."""
        errors = {}

        if user_input is not None:
            selected = user_input.get("devices", [])

            if not selected:
                errors["base"] = "select_at_least_one_device"
            else:
                self.integration_selected_devices = selected
                return await self.async_step_monitor_parameters()

        device_options = [
            selector.SelectOptionDict(value=device.id, label=f"{device.name_by_user or device.name}")
            for device in self.integration_available_devices
        ]

        mode = (
            "excluded"
            if self.integration_device_selection_mode == DEVICE_SELECTION_EXCLUDE
            else "included"
        )

        data_schema = vol.Schema(
            {
                vol.Required(
                    "devices", default=self.integration_selected_devices
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=device_options,
                        mode=selector.SelectSelectorMode.DROPDOWN,
                        multiple=True,
                    )
                )
            }
        )

        return self.async_show_form(
            step_id=f"integration_select_{mode}_devices",
            data_schema=data_schema,
            errors=errors,
            last_step=False,
            description_placeholders={
                "integration_name": self.integration_selected.friendly_name,
            },
        )

    async def async_step_integration_summary(self, user_input: dict[str, Any] | None = None):
        """Show summary and confirm."""
        if user_input is not None:
            return await self._async_shared_integration_create_entry()

        if self.integration_device_selection_mode == DEVICE_SELECTION_ALL:
            device_summary = f"All devices (currently {len(self.integration_available_devices)})"
        elif self.integration_device_selection_mode == DEVICE_SELECTION_EXCLUDE:
            excluded_count = len(self.integration_selected_devices)
            monitored_count = len(self.integration_available_devices) - excluded_count
            device_summary = f"{monitored_count} devices (excluding {excluded_count})"

            if self.integration_selected_devices:
                device_registry = dr.async_get(self.hass)
                excluded_names = []
                for device_id in self.integration_selected_devices:
                    device = device_registry.async_get(device_id)
                    if device:
                        excluded_names.append(device.name_by_user or device.name)
                if excluded_names:
                    device_summary += f"\n  **Excluded**: {', '.join(excluded_names)}"
        else:
            monitored_count = len(self.integration_selected_devices)
            device_summary = f"{monitored_count} selected devices"

            if self.integration_selected_devices:
                device_registry = dr.async_get(self.hass)
                included_names = []
                for device_id in self.integration_selected_devices:
                    device = device_registry.async_get(device_id)
                    if device:
                        included_names.append(device.name_by_user or device.name)
                if included_names:
                    device_summary += f"\n  **Only**: {', '.join(included_names)}"

        sensors_summary = self._get_sensors_summary()

        detection_time = self._calculate_detection_time(
            self.ping_attempts_before_failure, self.ping_interval
        )

        data_schema = vol.Schema({})

        return self.async_show_form(
            step_id="integration_summary",
            data_schema=data_schema,
            last_step=True,
            description_placeholders={
                "integration_name": self.integration_selected.friendly_name,
                "device_summary": device_summary,
                "ping_attempts_before_failure": str(self.ping_attempts_before_failure),
                "ping_interval": str(self.ping_interval),
                "sensors": sensors_summary,
                "detection_time": detection_time,
            },
        )

    @abc.abstractmethod
    async def _async_shared_integration_create_entry(self):
        pass

    @staticmethod
    def _calculate_detection_time(
        ping_attempts_before_failure: int, ping_interval: int
    ) -> str:
        """Calculate the offline detection time."""
        total_seconds = ping_attempts_before_failure * ping_interval

        return format_duration(total_seconds)

    async def async_step_custom_group_info(self, user_input: dict[str, Any] | None = None):
        """Handle the custom group info step."""

        if user_input is not None:
            self.custom_group_name = str(user_input[CONF_GROUP_NAME])

            if self.custom_group_edit_action:
                return await self.async_step_custom_group_summary()

            # Go to the first device creation step.
            return await self.async_step_custom_group_add_device()

        data_schema = vol.Schema(
            {
                vol.Required(CONF_GROUP_NAME, default=self.custom_group_name): str
            }
        )

        return self.async_show_form(
            step_id="custom_group_info",
            data_schema=data_schema,
            last_step=False,
        )

    async def async_step_custom_group_add_device(self, user_input: dict[str, Any] | None = None):
        """Handle the custom group device step."""
        errors = {}

        if user_input is not None:
            if not is_valid_hostname_or_ip(user_input[CONF_GROUP_DEVICE_HOST]):
                errors["base"] = "invalid_hostname_or_ip"
            else:
                self.custom_group_devices.append({
                    CONF_GROUP_DEVICE_ID: uuid.random_uuid_hex(),
                    CONF_GROUP_DEVICE_NAME: user_input[CONF_GROUP_DEVICE_NAME],
                    CONF_GROUP_DEVICE_HOST: user_input[CONF_GROUP_DEVICE_HOST],
                })

                if self.custom_group_edit_action:
                    return await self.async_step_custom_group_summary()

                return await self.async_step_custom_group_add_device_or_continue()

        data_schema = vol.Schema({
            vol.Required(CONF_GROUP_DEVICE_NAME): str,
            vol.Required(CONF_GROUP_DEVICE_HOST): str,
        })

        return self.async_show_form(
            step_id="custom_group_add_device",
            data_schema=data_schema,
            last_step=False,
            errors=errors,
        )

    async def async_step_custom_group_add_device_or_continue(self, user_input: dict[str, Any] | None = None):
        if user_input is not None:
            action = user_input["group_add_device_or_continue"]

            if action == "add_device":
                return await self.async_step_custom_group_add_device()

            return await self.async_step_monitor_parameters()

        data_schema = vol.Schema(
            {
                vol.Required("group_add_device_or_continue", default=None): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=["continue", "add_device"],
                        translation_key="group_add_device_or_continue",
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                )
            }
        )

        return self.async_show_form(
            step_id="custom_group_add_device_or_continue",
            data_schema=data_schema,
            last_step=False,
        )

    async def async_step_custom_group_summary(self, user_input: dict[str, Any] | None = None):
        """Handle the custom group device step."""
        if user_input is not None:
            return await self._async_shared_custom_group_create_entry()

        group_devices = [
            f"\n- **{device.get(CONF_GROUP_DEVICE_NAME)}**: {device.get(CONF_GROUP_DEVICE_HOST)}"
            for device in self.custom_group_devices
        ]
        group_devices_list = f"{''.join(group_devices)}"

        sensors_summary = self._get_sensors_summary()

        detection_time = self._calculate_detection_time(
            self.ping_attempts_before_failure, self.ping_interval
        )

        data_schema = vol.Schema({})

        return self.async_show_form(
            step_id="custom_group_summary",
            data_schema=data_schema,
            last_step=True,
            description_placeholders={
                "group_name": self.custom_group_name,
                "group_devices_list": group_devices_list,
                "ping_attempts_before_failure": str(self.ping_attempts_before_failure),
                "ping_interval": str(self.ping_interval),
                "sensors": sensors_summary,
                "detection_time": detection_time,
            },
        )

    @abc.abstractmethod
    async def _async_shared_custom_group_create_entry(self):
        pass


class DevicePingMonitorConfigFlow(
    config_entries.ConfigFlow, DevicePingMonitorBaseFlow, domain=DOMAIN
):
    """Handle a config flow for Device Pulse."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        """Handle the initial step, the config entry type selection."""
        if user_input is not None:
            self.entry_type = user_input[CONF_ENTRY_TYPE]

            if self.entry_type == ENTRY_TYPE_INTEGRATION:
                return await self.async_step_integration_choice()
            elif self.entry_type == ENTRY_TYPE_CUSTOM_GROUP:
                return await self.async_step_custom_group_info()
            elif self.entry_type == ENTRY_TYPE_NETWORK_SUMMARY:
                return self.async_abort(reason="no_config_flow_available")
            else:
                return self.async_abort(reason="unknown_config_entry_type")

        # Reset custom group devices
        self.custom_group_devices = []

        data_schema = vol.Schema(
            {
                vol.Required(CONF_ENTRY_TYPE, default=None): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[ENTRY_TYPE_INTEGRATION, ENTRY_TYPE_CUSTOM_GROUP],
                        translation_key=CONF_ENTRY_TYPE,
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                )
            }
        )

        return self.async_show_form(
            step_id="user",
            data_schema=data_schema,
            last_step=False,
        )

    async def async_step_integration_choice(self, user_input: dict[str, Any] | None = None):
        errors = {}

        self.available_integrations = await get_valid_integrations_for_monitoring(self.hass)

        if not self.available_integrations:
            return self.async_abort(reason="no_supported_integrations")

        if user_input is not None:
            if not (selected := self.available_integrations.get(user_input["integration"])):
                return self.async_abort(reason="selected_integration_not_found")

            self.integration_selected = selected

            return await self.async_step_integration_device_selection_mode()

        configured_integrations = {
            entry.data[CONF_INTEGRATION]
            for entry in self.hass.config_entries.async_entries(DOMAIN)
            if entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_INTEGRATION
        }

        configurable_integrations = {
            domain: data
            for domain, data in self.available_integrations.items()
            if domain not in configured_integrations
        }

        if not configurable_integrations:
            return self.async_abort(reason="all_integrations_configured")

        integration_options = [
            selector.SelectOptionDict(
                value=domain,
                label=f"{info.friendly_name} ({info.device_count} devices)",
            )
            for domain, info in sorted(
                configurable_integrations.items(), key=lambda x: x[1].friendly_name
            )
        ]

        data_schema = vol.Schema(
            {
                vol.Required(CONF_INTEGRATION, default=None): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=integration_options,
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                )
            }
        )

        return self.async_show_form(
            step_id="integration_choice",
            data_schema=data_schema,
            errors=errors,
            last_step=False,
            description_placeholders={
                "integration_count": str(len(configurable_integrations))
            },
        )

    async def async_step_network_summary(self, user_input: dict[str, Any] | None = None):
        """Handle the network summary (called internally)."""
        await self.async_set_unique_id(NETWORK_SUMMARY_ENTRY_ID)
        self._abort_if_unique_id_configured()

        return self.async_create_entry(
            title="Network Summary",
            data={
                CONF_ENTRY_TYPE: ENTRY_TYPE_NETWORK_SUMMARY,
            },
        )

    async def _async_shared_integration_create_entry(self):
        return self.async_create_entry(
            title=f"{self.integration_selected.friendly_name} Devices",
            data={
                CONF_ENTRY_TYPE: ENTRY_TYPE_INTEGRATION,
                CONF_INTEGRATION: self.integration_selected.domain,
            },
            options={
                CONF_SELECTED_DEVICES: self.integration_selected_devices
                if self.integration_device_selection_mode != DEVICE_SELECTION_ALL
                else [],
                CONF_PING_ATTEMPTS_BEFORE_FAILURE: self.ping_attempts_before_failure,
                CONF_PING_INTERVAL: self.ping_interval,
                CONF_DEVICE_SELECTION_MODE: self.integration_device_selection_mode,
                CONF_SENSORS_INTEGRATION_SUMMARY_ENABLED: self.sensors_integration_summary_enabled,
                CONF_SENSORS_FAILED_PINGS_ENABLED: self.sensors_failed_pings_enabled,
                CONF_SENSORS_DISCONNECTED_SINCE_ENABLED: self.sensors_disconnected_since_enabled,
                CONF_SENSORS_LAST_RESPONSE_TIME_ENABLED: self.sensors_last_response_time_enabled,
            },
        )

    async def _async_shared_custom_group_create_entry(self):
        return self.async_create_entry(
            title=f"Custom Group: {self.custom_group_name} Devices",
            data={
                CONF_ENTRY_TYPE: ENTRY_TYPE_CUSTOM_GROUP,
                CONF_GROUP_ID: uuid.random_uuid_hex(),
            },
            options={
                CONF_GROUP_NAME: self.custom_group_name,
                CONF_GROUP_DEVICES_LIST: self.custom_group_devices,
                CONF_PING_ATTEMPTS_BEFORE_FAILURE: self.ping_attempts_before_failure,
                CONF_PING_INTERVAL: self.ping_interval,
                CONF_SENSORS_INTEGRATION_SUMMARY_ENABLED: self.sensors_integration_summary_enabled,
                CONF_SENSORS_FAILED_PINGS_ENABLED: self.sensors_failed_pings_enabled,
                CONF_SENSORS_DISCONNECTED_SINCE_ENABLED: self.sensors_disconnected_since_enabled,
                CONF_SENSORS_LAST_RESPONSE_TIME_ENABLED: self.sensors_last_response_time_enabled,
            },
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: config_entries.ConfigEntry):
        """Get the options flow for this handler."""
        return DevicePingMonitorOptionsFlow()


class DevicePingMonitorOptionsFlow(
    config_entries.OptionsFlowWithReload, DevicePingMonitorBaseFlow
):
    """Handle an options flow for Device Pulse."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None):
        """Handle the initial step of the options flow."""
        self.entry_type = self.config_entry.data.get(CONF_ENTRY_TYPE)

        self.ping_attempts_before_failure = self.config_entry.options.get(CONF_PING_ATTEMPTS_BEFORE_FAILURE, DEFAULT_PING_ATTEMPTS_BEFORE_FAILURE)
        self.ping_interval = self.config_entry.options.get(CONF_PING_INTERVAL, DEFAULT_PING_INTERVAL)
        self.sensors_integration_summary_enabled = self.config_entry.options.get(CONF_SENSORS_INTEGRATION_SUMMARY_ENABLED, DEFAULT_SENSORS_INTEGRATION_SUMMARY_ENABLED)
        self.sensors_failed_pings_enabled = self.config_entry.options.get(CONF_SENSORS_FAILED_PINGS_ENABLED, DEFAULT_SENSORS_FAILED_PINGS_ENABLED)
        self.sensors_disconnected_since_enabled = self.config_entry.options.get(CONF_SENSORS_DISCONNECTED_SINCE_ENABLED, DEFAULT_SENSORS_DISCONNECTED_SINCE_ENABLED)
        self.sensors_last_response_time_enabled = self.config_entry.options.get(CONF_SENSORS_LAST_RESPONSE_TIME_ENABLED, DEFAULT_SENSORS_LAST_RESPONSE_TIME_ENABLED)

        if self.entry_type == ENTRY_TYPE_INTEGRATION:
            self.available_integrations = await get_valid_integrations_for_monitoring(self.hass)
            self.integration_selected = self.available_integrations.get(self.config_entry.data.get(CONF_INTEGRATION))
            self.integration_device_selection_mode = self.config_entry.options.get(CONF_DEVICE_SELECTION_MODE, DEVICE_SELECTION_ALL)
            self.integration_selected_devices = copy.deepcopy(self.config_entry.options.get(CONF_SELECTED_DEVICES, []))

            return await self.async_step_integration_device_selection_mode(user_input)

        elif self.entry_type == ENTRY_TYPE_CUSTOM_GROUP:
            self.custom_group_name = self.config_entry.options.get(CONF_GROUP_NAME)
            self.custom_group_devices = copy.deepcopy(self.config_entry.options.get(CONF_GROUP_DEVICES_LIST))

            return await self.async_step_custom_group_edit_action(user_input)

        elif self.entry_type == ENTRY_TYPE_NETWORK_SUMMARY:
            return self.async_abort(reason="no_options_flow_available")
        else:
            return self.async_abort(reason="unknown_config_entry_type")

    async def async_step_custom_group_edit_action(self, user_input: dict[str, Any] | None = None):
        """Handle custom group edit action."""
        if user_input is not None:
            self.custom_group_edit_action = user_input["group_edit_action"]

            if self.custom_group_edit_action == GROUP_EDIT_ADD_DEVICE:
                return await self.async_step_custom_group_add_device()
            elif self.custom_group_edit_action == GROUP_EDIT_REMOVE_DEVICES:
                return await self.async_step_custom_group_remove_devices()
            elif self.custom_group_edit_action == GROUP_EDIT_UPDATE_DEVICE:
                return await self.async_step_custom_group_update_device_selection()
            elif self.custom_group_edit_action == GROUP_EDIT_CHANGE_SETTING:
                return await self.async_step_monitor_parameters()
            else:
                return self.async_abort(reason="unknown_custom_group_edit_action")

        data_schema = vol.Schema(
            {
                vol.Required("group_edit_action", default=None): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[
                            GROUP_EDIT_ADD_DEVICE,
                            GROUP_EDIT_REMOVE_DEVICES,
                            GROUP_EDIT_UPDATE_DEVICE,
                            GROUP_EDIT_CHANGE_SETTING,
                        ],
                        translation_key="group_edit_action",
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                )
            }
        )

        return self.async_show_form(
            step_id="custom_group_edit_action",
            data_schema=data_schema,
            last_step=False,
        )

    async def async_step_custom_group_remove_devices(self, user_input: dict[str, Any] | None = None):
        errors = {}

        if user_input is not None:
            removed_devices = user_input.get("devices", [])

            if not removed_devices:
                errors["base"] = "select_at_least_one_device"
            else:
                self.custom_group_devices = [
                    device
                    for device in self.custom_group_devices
                    if device.get(CONF_GROUP_DEVICE_ID) not in removed_devices
                ]

                return await self.async_step_custom_group_summary()

        device_registry = dr.async_get(self.hass)
        device_options = [
            selector.SelectOptionDict(
                value=group_device.get(CONF_GROUP_DEVICE_ID),
                label=device_entry.name_by_user or device_entry.name,
            )
            for group_device in self.custom_group_devices
            if (device_entry := device_registry.async_get_device(
                identifiers={(DOMAIN, group_device.get(CONF_GROUP_DEVICE_ID))}))
        ]

        data_schema = vol.Schema(
            {
                vol.Required("devices", default=[]): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=device_options,
                        mode=selector.SelectSelectorMode.DROPDOWN,
                        multiple=True,
                    )
                )
            }
        )

        return self.async_show_form(
            step_id="custom_group_remove_devices",
            data_schema=data_schema,
            errors=errors,
            last_step=False,
        )

    async def async_step_custom_group_update_device_selection(self, user_input: dict[str, Any] | None = None):
        if user_input is not None:
            self.custom_group_edit_update_device_id = user_input.get("device")

            return await self.async_step_custom_group_update_device_data()

        device_registry = dr.async_get(self.hass)
        device_options = [
            selector.SelectOptionDict(
                value=group_device.get(CONF_GROUP_DEVICE_ID),
                label=device_entry.name_by_user or device_entry.name,
            )
            for group_device in self.custom_group_devices
            if (device_entry := device_registry.async_get_device(
                identifiers={(DOMAIN, group_device.get(CONF_GROUP_DEVICE_ID))}))
        ]

        data_schema = vol.Schema(
            {
                vol.Required("device", default=None): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=device_options,
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                )
            }
        )

        return self.async_show_form(
            step_id="custom_group_update_device_selection",
            data_schema=data_schema,
            last_step=False,
        )

    async def async_step_custom_group_update_device_data(self, user_input: dict[str, Any] | None = None):
        errors = {}

        if user_input is not None:
            if not is_valid_hostname_or_ip(user_input[CONF_GROUP_DEVICE_HOST]):
                errors["base"] = "invalid_hostname_or_ip"
            else:
                for device in self.custom_group_devices:
                    if device.get(CONF_GROUP_DEVICE_ID) == self.custom_group_edit_update_device_id:
                        device.update({
                            CONF_GROUP_DEVICE_HOST: str(user_input[CONF_GROUP_DEVICE_HOST]),
                        })

                return await self.async_step_custom_group_summary()

        device_selected = next((
            device
            for device in self.custom_group_devices
            if device.get(CONF_GROUP_DEVICE_ID) == self.custom_group_edit_update_device_id), None)
        device_registry = dr.async_get(self.hass)
        device = device_registry.async_get_device(identifiers={(DOMAIN, device_selected.get(CONF_GROUP_DEVICE_ID))})

        data_schema = vol.Schema({
            vol.Required(CONF_GROUP_DEVICE_HOST, default=device_selected.get(CONF_GROUP_DEVICE_HOST)): str,
        })

        return self.async_show_form(
            step_id="custom_group_update_device_data",
            data_schema=data_schema,
            errors=errors,
            last_step=False,
            description_placeholders={
                "device_name": device.name_by_user or device.name,
            }
        )

    async def _async_shared_integration_create_entry(self):
        return self.async_create_entry(
            data={
                # Integration specific data
                CONF_DEVICE_SELECTION_MODE: self.integration_device_selection_mode,
                CONF_SELECTED_DEVICES: self.integration_selected_devices
                if self.integration_device_selection_mode != DEVICE_SELECTION_ALL
                else [],
                # Common entry data
                CONF_PING_ATTEMPTS_BEFORE_FAILURE: self.ping_attempts_before_failure,
                CONF_PING_INTERVAL: self.ping_interval,
                CONF_SENSORS_INTEGRATION_SUMMARY_ENABLED: self.sensors_integration_summary_enabled,
                CONF_SENSORS_FAILED_PINGS_ENABLED: self.sensors_failed_pings_enabled,
                CONF_SENSORS_DISCONNECTED_SINCE_ENABLED: self.sensors_disconnected_since_enabled,
                CONF_SENSORS_LAST_RESPONSE_TIME_ENABLED: self.sensors_last_response_time_enabled,
            },
        )

    async def _async_shared_custom_group_create_entry(self):
        return self.async_create_entry(
            data={
                # Custom group specific data
                CONF_GROUP_NAME: self.custom_group_name,
                CONF_GROUP_DEVICES_LIST: self.custom_group_devices,
                # Common entry data
                CONF_PING_ATTEMPTS_BEFORE_FAILURE: self.ping_attempts_before_failure,
                CONF_PING_INTERVAL: self.ping_interval,
                CONF_SENSORS_INTEGRATION_SUMMARY_ENABLED: self.sensors_integration_summary_enabled,
                CONF_SENSORS_FAILED_PINGS_ENABLED: self.sensors_failed_pings_enabled,
                CONF_SENSORS_DISCONNECTED_SINCE_ENABLED: self.sensors_disconnected_since_enabled,
                CONF_SENSORS_LAST_RESPONSE_TIME_ENABLED: self.sensors_last_response_time_enabled,
            },
        )
