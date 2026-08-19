# Broadlink Commands

Learn IR and RF codes from a Broadlink remote and get a Home Assistant button for
each one. No add-on, no Docker, no external database — the codes live in the
config entry and the buttons are ordinary entities.

## Why this exists

Home Assistant's built-in Broadlink integration can learn codes, but only through
`remote.learn_command` in Developer Tools, and what you get back is a command name
you have to wire up yourself. The Broadlink Manager add-on has a nicer learning UI
but stores codes in its own database, so nothing it captures becomes an entity.

This integration does the learning in Home Assistant's own config flow and creates
a `button` entity per command, grouped under a real device.

## Install

Add this repository to HACS as a custom repository (category: Integration), install
it, and restart Home Assistant. Then go to **Settings → Devices & Services → Add
integration → Broadlink Commands**.

## Setting up the device

The config flow scans the network and lists the Broadlink devices it finds.

Broadcast discovery does not cross VLANs or subnets. If your device is on a
separate network — an IoT VLAN, for example — pick **Enter an address manually**
and give it the IP. Control itself is plain UDP and routes fine; only the discovery
broadcast is limited.

Supported: RM mini, RM pro, RM4 mini and RM4 pro. Devices that cannot learn are
filtered out of the list.

## Learning a command

On the device page, choose **Learn a command**.

**Infrared** — press the button on your remote once when asked.

**Radio frequency** — two steps, because the device has to find the frequency
first. Hold the button down until the step completes, then let go and press it
once.

Either way you then get a screen to name the command, put it in an area, and
optionally send the code to check it does what you expect before saving. Testing
does not save anything, so you can try as many times as you need.

Each saved command becomes a button entity under the device.

## Notes

- Codes are stored in the config entry, so they survive restarts and are included
  in Home Assistant backups.
- Removing a command removes its button.
- The device is contacted only when a button is pressed, and authentication is
  redone each time, so a device that reboots or changes address recovers on its
  own once the address is updated.

## Licence

Apache-2.0.
