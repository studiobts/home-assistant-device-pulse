# Requesting a Custom Host Resolver

If you want to make donation as appreciation of my work, you can do so via buy me a coffee. Thank you!

<a href="https://buymeacoffee.com/studiobts" target="_blank"><img src="https://www.buymeacoffee.com/assets/img/custom_images/orange_img.png"></a>

## Introduction

If you're using an integration that doesn't currently appear in the supported list, you can request the addition of a custom host resolver. However, please note the following important points before proceeding:

## Important Considerations

- **No Guarantee**: There is no guarantee that a resolver will be created for your integration.
- **Testing Limitations**: Without access to a real device, it may not be possible to create a working resolver, even with complete information.
- **Best Effort**: The implementation will be attempted on a best-effort basis using the data you provide.

## Required Information

To request support for a new integration, you must provide the following files from your Home Assistant configuration:

### 1. Config Entry Data

**File Location**: `/config/.storage/core.config_entries`

This file contains the configuration data for all your integrations. You need to:
- Locate the entry for the specific integration you want supported
- Copy only the relevant config entry section (not the entire file)
- The entry will contain fields like `domain`, `data`, `options`, and `unique_id`

### 2. Device Registry Data

**File Location**: `/config/.storage/core.device_registry`

This file contains information about all devices registered in Home Assistant. You need to:
- Find the device entries linked to the config entry from step 1
- Copy the relevant device entries that belong to your integration
- These entries will show how the integration exposes device parameters like `identifiers`, `connections`, and configuration data

### 3. Devices with `via_device_id` Attribute

**Important**: If any device entry contains a `via_device_id` attribute, you must also include:

- The complete device registry entry of the device referenced by `via_device_id`
- The config entry data (from `/config/.storage/core.config_entries`) associated with that referenced device

**Example**: If device A has `"via_device_id": "device_b_id"`, you need to provide:
- Device A's registry entry
- Device B's registry entry (the one referenced by `via_device_id`)
- Device B's config entry data

This information is crucial for understanding the device hierarchy and relationships within the integration.

## Security Precautions

⚠️ **Before copying any data, carefully review and remove all sensitive information**, including:

- Email addresses
- Passwords
- API tokens or keys
- Authentication credentials
- Personal identifiers
- Location data (coordinates, addresses)
- Any other private information

## File Handling Guidelines

**Critical**: Do NOT modify these files directly in your Home Assistant installation.

- ❌ Never edit `/config/.storage/core.config_entries` or `/config/.storage/core.device_registry`
- ❌ Do not change formatting, add comments, or remove fields
- ✅ Only read and copy data from these files
- ⚠️ Modifying these files incorrectly can prevent Home Assistant from starting

## How to Submit Your Request

Once you have gathered the required information:

1. Create a new GitHub issue in the repository using the template provided
2. Include the sanitized config entry and device registry data
3. Provide any additional context about the integration's behavior

## What Happens Next

After you submit your request:

1. The data will be reviewed to understand the integration's structure
2. An attempt will be made to create a custom resolver based on the provided information
3. If successful, the resolver will be added to the `host_resolvers` directory

**Remember: Even with all the correct information, implementation may not be possible without physical access to test the integration with real devices.**