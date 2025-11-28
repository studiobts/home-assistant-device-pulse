# Device Pulse

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)

If you want to make donation as appreciation of my work, you can do so via buy me a coffee. Thank you!

<a href="https://buymeacoffee.com/studiobts" target="_blank"><img src="https://www.buymeacoffee.com/assets/img/custom_images/orange_img.png"></a>

## Introduction

Device Pulse is a custom Home Assistant integration that provides flexible monitoring of IP-based devices. It offers two configuration modes to track network device availability through ping checks and automatically generates summary sensors for quick visibility of connection states.

---

## Installation

#### Method 1: HACS (Recommended)

1. Install via HACS (Home Assistant Community Store)
2. Restart Home Assistant
3. Add the integration through the UI

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=studiobts&repository=home-assistant-device-pulse)

#### Method 2: Manual Installation

1. Download this repository
2. Copy the `device_pulse` folder to your Home Assistant's `custom_components` directory:
   ```
   /config/custom_components/device_pulse/
   ```
3. Restart Home Assistant
4. Add the integration through the UI

---

## Basic Functionality

### Configuration Modes

1. **Integration-based Monitoring**\
   Device Pulse can automatically detect existing Home Assistant integrations that expose device connection parameters such as `ip_address`, `ipaddress`, `host`, `hostname`, or `address`.\
   You can then select one of these integrations to monitor its devices.

<p float="left">
  <img src="https://github.com/studiobts/home-assistant-device-pulse/blob/main/images/config_flow_mode.png?raw=true" height="350" />
  <img src="https://github.com/studiobts/home-assistant-device-pulse/blob/main/images/config_flow_integration.png?raw=true" height="350" />
</p>

   During setup, you can specify which devices to monitor:   

   - **All valid devices** – all devices with a valid host parameter.
   - **All except listed devices** – exclude specific devices listed during configuration.
   - **Only listed devices** – include only the specified devices.

<p float="left">
  <img src="https://github.com/studiobts/home-assistant-device-pulse/blob/main/images/config_flow_device_selection.png?raw=true" height="350" />
</p>

2. **Custom Group Monitoring**\
   You can manually create a custom group and add devices by specifying their **name** and **host (hostname or IP)**. Each group can be configured independently.


### Monitoring Parameters

For both configuration modes, you can define:

- The **number of failed ping attempts** required before a device is considered disconnected.
- The **interval time** between each ping request.

<p float="left">
  <img src="https://github.com/studiobts/home-assistant-device-pulse/blob/main/images/config_flow_ping_parameters.png?raw=true" height="350" />
</p>

---

## Advanced Features

### Optional Supplementary Sensors

You can choose to create additional sensors for each monitored device to track:

- The number of failed pings.
- The timestamp of the last offline event.
- The round-trip time of the most recent ping.

<p float="left">
  <img src="https://github.com/studiobts/home-assistant-device-pulse/blob/main/images/config_flow_optional_sensors.png?raw=true" height="450" />
</p>

### Summary Sensors per Integration or Group

Each integration or custom group can have two summary sensors:

- The **total number of monitored devices**.
- The **number of offline devices**.

### Global Summary Sensors

Device Pulse automatically creates three global summary sensors:

1. A sensor for the **total number of devices** under monitoring.
2. A **binary sensor** indicating whether all devices are online.
3. A sensor showing the **total number of offline devices**.

### Attributes for Offline Summary Sensors

Sensors that track the number of offline devices (both per group and globally) expose three attributes:

- `offline_device_ids`: list of device IDs currently offline.
- `went_offline_device_ids`: list of device IDs that went offline in the most recent update.
- `came_online_device_ids`: list of device IDs that came back online in the most recent update.

These attributes allow for easy automation and dynamic UI cards showing current offline devices.

### Custom Events

Device Pulse emits three custom events that can be used for advanced automations and tracking device state changes:

- `device_pulse_ping_status_updated`: Triggered whenever the ping status of any monitored device sensor changes (from online to offline or vice versa).
- `device_pulse_device_went_offline`: Triggered when a device transitions from online to offline. The event data includes the device ID.
- `device_pulse_device_came_online`: Triggered when a device transitions from offline back to online. The event data includes the device ID.

These events can be used in automations to trigger notifications, log changes, or synchronize external systems with real-time network status.

---

## Configuration Parsing

Not all integrations have a straightforward configuration structure where the host can be easily identified. 

For integrations with complex or "non-standard" configuration formats, you can create a dedicated resolver class to handle proper configuration parsing.

### Creating a Custom Resolver

To implement a custom resolver:
- Create a new file in the `host_resolvers` directory named with the integration's domain
- **Extend BaseHostResolver**: Your class must inherit from the base resolver class
- **Implement the `resolve` method**: Return the host for the specific device

### Current Custom Resolvers

At the moment, the following custom resolvers are implemented:

- Midea Dehumidifier LAN
- Tasmota

## Device Pulse Timeline Card

<p float="left">
  <img src="https://github.com/studiobts/home-assistant-device-pulse/blob/main/images/timeline_card_horizontal.png?raw=true" width="100%" />
</p>

A companion custom Lovelace card named `device-pulse-timeline-card` is available in the repository [https://github.com/studiobts/device-pulse-timeline-card](https://github.com/studiobts/device-pulse-timeline-card).
This card displays a visual timeline of connection and disconnection events for each monitored device, providing an intuitive historical view of network stability and device uptime.

The card can be added to your dashboard as a standard custom card once installed and configured through HACS or manual setup.

---

## Device Pulse Table Card

<p float="left">
  <img src="https://github.com/studiobts/home-assistant-device-pulse/blob/main/images/table_card.png?raw=true" width="100%" />
</p>

A companion custom Lovelace card named `device-pulse-table-card` is available in the repository [https://github.com/studiobts/device-pulse-table-card](https://github.com/studiobts/device-pulse-table-card).

This card displays a table view of devices monitored through the integration, designed to visualize network health data collected. It transforms raw connectivity metrics into an interactive, real-time table, allowing users to monitor device status, latency, and stability at a glance.
Key capabilities include:
- **Real-Time Updates**: Leverages Home Assistant WebSockets to display live changes in connectivity and response times without page reloads.
- **Advanced Organization**: offers flexible grouping by integration and status-based filtering (Online/Offline) to easily manage large numbers of devices.
- **Customizable Layout**: Fully configurable via the visual editor, allowing you to toggle specific columns—such as Host, Last Response Time, or Pings Failed—to suit your monitoring needs.
- **Interactive Interface**: Supports dynamic sorting and text filtering, with direct access to standard "more-info" dialogs for detailed device history.

The card can be added to your dashboard as a standard custom card once installed and configured through HACS or manual setup.

---

## Example Automation

Sends a notification to the mobile app when one or more devices go offline, keeps that notification updated with the current list of offline devices or clears it when all devices are back online, and sends an additional notification each time a device reconnects.

```yaml
alias: Devices Disconnection/Re-Connection Notification
triggers:
  - trigger: event
    event_type: device_pulse_device_came_online
    event_data: {}
    id: came-online
  - trigger: state
    entity_id:
      - sensor.devices_offline
    id: went-offline
    attribute: went_offline_device_ids
conditions: []
actions:
  - choose:
      - conditions:
          - condition: trigger
            id:
              - went-offline
        sequence:
          - if:
              - condition: template
                value_template: >-
                  {{ state_attr('sensor.devices_offline', 'offline_device_ids')
                  | length > 0 }}
                alias: There are devices offline
            then:
              - action: notify.<MY_MOBILE_APP>
                metadata: {}
                data:
                  message: >-
                    {%- set offline_ids = state_attr('sensor.devices_offline', 'offline_device_ids') -%} 
                    {%- set device_names = offline_ids | map('device_attr', 'name') | list -%}
                    Following devices are OFFLINE:  

                    {{ device_names | join(', ') }}
                  data:
                    tag: device-pulse-offline
                alias: Send or Update Notification
            else:
              - alias: Clear Notification
                action: notify.<MY_MOBILE_APP>
                metadata: {}
                data:
                  message: clear_notification
                  data:
                    tag: device-pulse-offline
                    clear_notification: true
      - conditions:
          - condition: trigger
            id:
              - came-online
        sequence:
          - action: notify.<MY_MOBILE_APP>
            data:
              message: >-
                {%- set came_online_id = trigger.event.data.device_id -%} 
                {%- set device_name = device_attr(came_online_id, 'name_by_user') or device_attr(came_online_id, 'name') -%}
                This device came back ONLINE: {{ device_name }} 
mode: parallel
max: 5
```

---

## Example With Button Card

<p float="left">
  <img src="https://github.com/studiobts/home-assistant-device-pulse/blob/main/images/custom_button_card_example.png?raw=true" />
</p>

```yaml
type: custom:button-card
entity: sensor.devices_offline
show_state: false
show_icon: false
show_name: false
styles:
  card:
    - padding: 8px
    - border-radius: 10px
    - background-color: "#fde9ee"
    - border-color: "#fbd3dc"
    - color: "#c0123c"
  grid:
    - display: grid
    - grid-template-columns: auto auto auto 1fr
    - grid-template-rows: auto auto
    - grid-template-areas: |
        "icon entity"
        "icon list"
  custom_fields:
    icon:
      - grid-area: icon
      - justify-self: start
      - width: 60px
      - align-self: center
      - margin-right: 10px
    entity:
      - grid-area: entity
      - justify-self: start
      - align-self: end
      - text-align: left
      - font-size: 20px
      - font-weight: bold
      - line-height: 35px
      - text-transform: uppercase
    list:
      - grid-area: liste
      - justify-self: start
      - align-self: start
      - text-align: left
      - font-size: 16px
      - font-weight: bold
      - color: var(--secondary-text-color)
custom_fields:
  icon: |
    [[[
      return '<ha-icon icon="mdi:alert-circle-outline">';
    ]]]
  entity: |
    [[[ return `DEVICES OFFLINE` ]]]
  list: |
    [[[
      var ids = entity.attributes.offline_device_ids || [];
      var names = ids.map(id => {
        var device = Object.values(hass.devices).find(d => d.id === id);
        return device ? device.name : id;
      });
      return names.join('<br>');
    ]]]
```
To show the card only if there are devices disconnected, add a visibility condition

```yaml
condition: numeric_state
entity: sensor.devices_offline
above: 0
```

## Support

For issues and feature requests, please visit the [GitHub repository](https://github.com/studiobts/home-assistant-device-pulse).
