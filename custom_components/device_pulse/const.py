"""Constants for Device Pulse integration."""

DOMAIN = "device_pulse"
PLATFORMS = ["binary_sensor", "sensor"]

HOST_PARAM_NAMES = ["ip", "address", "ip_address", "ipaddress", "host", "hostname"]

ENTRY_TYPE_NETWORK_SUMMARY = "network_summary"
ENTRY_TYPE_INTEGRATION = "integration"
ENTRY_TYPE_CUSTOM_GROUP = "custom_group"

CONF_ENTRY_TYPE = "entry_type"
# Entry Type Integration specific fields and defaults
CONF_INTEGRATION = "integration"
CONF_DEVICE_SELECTION_MODE = "device_selection_mode"
CONF_SELECTED_DEVICES = "selected_devices"
CONF_PING_ATTEMPTS_BEFORE_FAILURE = "ping_attempts_before_failure"
CONF_PING_INTERVAL = "ping_interval"
CONF_SENSORS_INTEGRATION_SUMMARY_ENABLED = "sensors_integration_summary_enabled"
CONF_SENSORS_FAILED_PINGS_ENABLED = "sensors_failed_pings_enabled"
CONF_SENSORS_DISCONNECTED_SINCE_ENABLED = "sensors_disconnected_since_enabled"
CONF_SENSORS_LAST_RESPONSE_TIME_ENABLED = "sensors_last_response_time_enabled"

DEFAULT_PING_ATTEMPTS_BEFORE_FAILURE = 3
DEFAULT_PING_INTERVAL = 60
DEFAULT_SENSORS_INTEGRATION_SUMMARY_ENABLED = False
DEFAULT_SENSORS_FAILED_PINGS_ENABLED = False
DEFAULT_SENSORS_DISCONNECTED_SINCE_ENABLED = False
DEFAULT_SENSORS_LAST_RESPONSE_TIME_ENABLED = False

DEVICE_SELECTION_ALL = "all"
DEVICE_SELECTION_EXCLUDE = "exclude"
DEVICE_SELECTION_INCLUDE = "include"

# Entry Type Custom Group specific fields and default
CONF_GROUP_ID = "group_id"
CONF_GROUP_NAME = "group_name"
CONF_GROUP_DEVICES_LIST = "group_devices_list"
CONF_GROUP_DEVICE_ID = "group_device_id"
CONF_GROUP_DEVICE_NAME = "group_device_name"
CONF_GROUP_DEVICE_HOST = "group_device_host"

NETWORK_SUMMARY_ENTRY_ID = "network_summary"

NETWORK_SUMMARY_ALL_DEVICES_ONLINE_STATUS_ID = f"{DOMAIN}_network_summary_all_devices_online_status"
NETWORK_SUMMARY_TOTAL_DEVICES_COUNT = f"{DOMAIN}_network_summary_total_devices_count"
NETWORK_SUMMARY_TOTAL_DEVICES_OFFLINE_COUNT = f"{DOMAIN}_network_summary_total_devices_offline_count"
INTEGRATION_SUMMARY_TOTAL_DEVICES_COUNT = f"{DOMAIN}_{{platform}}_platform_total_devices_count"
INTEGRATION_SUMMARY_TOTAL_DEVICES_OFFLINE_COUNT = f"{DOMAIN}_{{platform}}_platform_total_devices_offline_count"

ENTITY_ATTR_INTEGRATION_DOMAIN = "integration_domain"
ENTITY_ATTR_INTEGRATION_NAME = "integration_name"
ENTITY_ATTR_INTEGRATION_CUSTOM_GROUP = "integration_custom_group"
ENTITY_ATTR_DEVICE_ID = "device_id"
ENTITY_ATTR_HOST = "host"
ENTITY_ATTR_TAG = "tag"
ENTITY_ATTR_STATE_SINCE = "state_since"
ENTITY_ATTR_PINGS_FAILED = "pings_failed"

ENTITY_TAG_PING_STATUS = "ping_status"
ENTITY_TAG_PINGS_FAILED_COUNT = "pings_failed_count"
ENTITY_TAG_DISCONNECTED_SINCE = "disconnected_since"
ENTITY_TAG_LAST_RESPONSE_TIME = "last_response_time"

EVENT_PING_STATUS_UPDATED = f"{DOMAIN}_ping_status_updated"
EVENT_DEVICE_WENT_OFFLINE = f"{DOMAIN}_device_went_offline"
EVENT_DEVICE_CAME_ONLINE = f"{DOMAIN}_device_came_online"