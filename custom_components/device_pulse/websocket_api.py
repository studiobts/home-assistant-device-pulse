import json
from typing import Any

import voluptuous as vol

from datetime import timedelta
from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.util import session_scope
from homeassistant.components.recorder.db_schema import EventData, Events, EventTypes
from homeassistant.util import dt as dt_util
from homeassistant.components import websocket_api
from homeassistant.components.websocket_api import messages
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.json import json_bytes

from sqlalchemy import select
from sqlalchemy.engine.row import Row
from sqlalchemy.orm import Session

from .const import DOMAIN, EVENT_DEVICE_WENT_OFFLINE, EVENT_DEVICE_CAME_ONLINE

@callback
def async_setup(hass: HomeAssistant) -> None:
    """Set up the logbook websocket API."""
    websocket_api.async_register_command(hass, ws_get_events)

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
    """Handle logbook get events websocket command."""
    recorder = get_instance(hass)

    msg_id: int = msg["id"]
    hours_back: int = int(msg.get("hours_back", 24))
    hours_back_ts = (dt_util.utcnow() - timedelta(hours=hours_back)).timestamp()

    events = await recorder.async_add_executor_job(_get_events, hass, hours_back_ts)

    connection.send_message(_ws_formatted_events(msg_id, events))
