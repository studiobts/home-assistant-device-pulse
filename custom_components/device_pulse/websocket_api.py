import json
from typing import Any

import voluptuous as vol

from datetime import timedelta
from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.util import session_scope
from homeassistant.components.recorder.db_schema import EventData, Events, EventTypes
from homeassistant.components import websocket_api
from homeassistant.components.websocket_api import messages
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.json import json_bytes
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import device_registry as dr
from homeassistant.util import dt as dt_util

from sqlalchemy import select
from sqlalchemy.orm import Session

from .const import (
    DOMAIN,
    ENTITY_ATTR_TAG,
    ENTITY_ATTR_HOST,
    ENTITY_ATTR_DEVICE_ID,
    ENTITY_ATTR_INTEGRATION_DOMAIN,
    ENTITY_ATTR_INTEGRATION_NAME,
    ENTITY_ATTR_INTEGRATION_CUSTOM_GROUP,
    ENTITY_ATTR_STATE_SINCE,
    ENTITY_ATTR_PINGS_FAILED,
    ENTITY_TAG_PING_STATUS,
    ENTITY_TAG_PINGS_FAILED_COUNT,
    ENTITY_TAG_LAST_RESPONSE_TIME,
    EVENT_DEVICE_WENT_OFFLINE,
    EVENT_DEVICE_CAME_ONLINE,
)

@callback
def async_setup(hass: HomeAssistant) -> None:
    """Set up the logbook websocket API."""
    websocket_api.async_register_command(hass, ws_get_events)
    websocket_api.async_register_command(hass, ws_get_devices)

def _ws_formatted_events(msg_id: int, events: list) -> bytes:
    """Convert events to json."""
    return json_bytes(
        messages.result_message(
            msg_id, {'events': events}
        )
    )

def _query_events(session: Session, from_ts: int) -> list[tuple[str, str]]:
    query = (
        select(
            EventTypes.event_type,
            EventData.shared_data
        )
        .select_from(Events)
        .outerjoin(EventData, Events.data_id == EventData.data_id)
        .outerjoin(EventTypes, Events.event_type_id == EventTypes.event_type_id)
        .where(Events.time_fired_ts >= from_ts)
        .where(EventTypes.event_type.in_([EVENT_DEVICE_WENT_OFFLINE, EVENT_DEVICE_CAME_ONLINE]))
        .order_by(Events.time_fired_ts)
    )

    return session.connection().execute(query).all()

def _get_events(hass: HomeAssistant, from_ts: int):
    with session_scope(hass=hass, read_only=True) as session:
        combined = []
        for event_type, shared_data in _query_events(session, from_ts):
            combined.append({
                "event_type": "disconnected" if event_type == EVENT_DEVICE_WENT_OFFLINE else "connected",
                "event_type_original": event_type,
                **json.loads(shared_data)
            })

        return combined

@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/get_events",
        vol.Optional("hours_back"): str,
    }
)
@websocket_api.async_response
async def ws_get_events(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Handle get events websocket command."""
    recorder = get_instance(hass)

    msg_id: int = msg["id"]
    hours_back: int = int(msg.get("hours_back", 24))
    hours_back_ts = (dt_util.utcnow() - timedelta(hours=hours_back)).timestamp()

    events = await recorder.async_add_executor_job(_get_events, hass, hours_back_ts)

    connection.send_message(_ws_formatted_events(msg_id, events))

@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/get_devices",
    }
)
@websocket_api.async_response
async def ws_get_devices(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Handle get devices websocket command."""
    msg_id: int = msg["id"]

    entity_registry = er.async_get(hass)
    device_registry = dr.async_get(hass)

    result = {}

    for entity_id, entry in entity_registry.entities.items():
        if entry.platform != DOMAIN:
            continue

        entity_state = hass.states.get(entity_id)
        if entity_state is None:
            continue

        if entity_state.attributes.get(ENTITY_ATTR_TAG) != ENTITY_TAG_PING_STATUS:
            continue

        device_id = entity_state.attributes.get(ENTITY_ATTR_DEVICE_ID)
        device_entry = device_registry.devices.get(device_id)
        device_name = device_entry.name_by_user or device_entry.name or "Unknown Device"

        integration_domain = entity_state.attributes.get(ENTITY_ATTR_INTEGRATION_DOMAIN)
        integration_name = entity_state.attributes.get(ENTITY_ATTR_INTEGRATION_NAME)
        integration_custom_group = entity_state.attributes.get(ENTITY_ATTR_INTEGRATION_CUSTOM_GROUP)

        host = entity_state.attributes.get(ENTITY_ATTR_HOST)

        ping_status = {
            "entity_id": entity_id,
            "state": entity_state.state,
            "unit_of_measurement": None,
            "pings_failed": entity_state.attributes.get(ENTITY_ATTR_PINGS_FAILED)
        }
        ping_status_since_timestamp = entity_state.attributes.get(ENTITY_ATTR_STATE_SINCE)

        # TODO: add config entry check and determine if optional sensors are enabled or not
        last_response_time = None
        pings_failed_count = None

        for device_entity in er.async_entries_for_device(entity_registry, device_id):
            device_entity_state = hass.states.get(device_entity.entity_id)
            if device_entity_state is None:
                continue
            if device_entity_state.attributes.get(ENTITY_ATTR_TAG) == ENTITY_TAG_PINGS_FAILED_COUNT:
                pings_failed_count = {
                    "entity_id": device_entity.entity_id,
                    "state": device_entity_state.state if ping_status.get("state") == "off" else None,
                    "unit_of_measurement": None
                }
            elif device_entity_state.attributes.get(ENTITY_ATTR_TAG) == ENTITY_TAG_LAST_RESPONSE_TIME:
                last_response_time = {
                    "entity_id": device_entity.entity_id,
                    "state": device_entity_state.state if ping_status.get("state") == "on" else None,
                    "unit_of_measurement": device_entity.unit_of_measurement
                }

            if (
                last_response_time is not None
                and pings_failed_count is not None
            ):
                break

        result[device_id] = {
            "device_id": device_id,
            "device_name": device_name,
            "integration_domain": integration_domain,
            "integration_name": integration_name,
            "integration_custom_group": integration_custom_group,
            "host": host,
            "ping_status": ping_status,
            "ping_status_since_timestamp": ping_status_since_timestamp,
            "pings_failed_count": pings_failed_count,
            "last_response_time": last_response_time,
        }

    connection.send_message(websocket_api.result_message(msg_id, {
        'devices': result
    }))
