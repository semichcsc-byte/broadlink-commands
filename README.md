<img src="logo.png" alt="Broadlink Commands" width="360">

[![Validate](https://github.com/semichcsc-byte/broadlink-commands/actions/workflows/validate.yml/badge.svg)](https://github.com/semichcsc-byte/broadlink-commands/actions/workflows/validate.yml)
[![HACS custom](https://img.shields.io/badge/HACS-custom-41BDF5.svg)](https://hacs.xyz)

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

## What you need

- Home Assistant 2025.3 or newer
- A Broadlink RM mini, RM pro, RM4 mini or RM4 pro
- The device already on your Wi-Fi, set up once with the Broadlink app

Devices that cannot learn codes are filtered out, so if yours is not on the list
above it will not appear.

## Install

### With HACS

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=semichcsc-byte&repository=broadlink-commands&category=integration)

That button opens this repository straight in your HACS. Press **Download**, then
restart Home Assistant.

To add it by hand instead:

1. Open **HACS**
2. Top right **⋮** → **Custom repositories**
3. Repository: `https://github.com/semichcsc-byte/broadlink-commands`
4. Type: **Integration** → **Add**
5. Search HACS for *Broadlink Commands*, open it, press **Download**
6. Restart Home Assistant

### Without HACS

Copy the `custom_components/broadlink_commands` folder into your Home Assistant
`config/custom_components/` folder, so you end up with
`config/custom_components/broadlink_commands/manifest.json`. Restart Home
Assistant.

## Set up your remote

[![Open your Home Assistant instance and start setting up a new integration.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=broadlink_commands)

Or go to **Settings → Devices & services → Add integration** and search for
**Broadlink Commands**.

You get a list of the Broadlink devices found on the network. Pick yours, and that
is the whole setup.

**If the list is empty**, choose **Enter an address manually** and type the
device's IP. Discovery uses a network broadcast, and broadcasts do not cross VLANs
or subnets, so a device on a separate IoT network will never show up in the list
even though it is perfectly reachable. Everything after discovery is ordinary
traffic and routes fine.

## Learn a command

On the integration's page, press **Learn a command**.

**Infrared** — press the button on your remote once, when asked.

**Radio frequency** — the first RF command takes two steps, because the device
has to find the frequency first. Hold the button down until the step finishes,
then release it and press it once. Later RF commands on the same device reuse that
frequency, so they are a single press.

Then name the command and choose an area. Tick **Test before saving** to fire the
code and check it does the right thing; nothing is saved until you leave that box
unticked, so try as often as you like.

Each command you save becomes a button entity, grouped under the remote.

## Edit a command

Open the command from the integration's page.

Renaming it or moving it to another area keeps the same entity, so dashboards,
automations and scripts carry on working. Tick **Learn the code again** to
recapture the code and keep everything else.

## If something does not work

**The button does nothing, or only half works.** Learn the command again. RF
captures fail silently more often than you would think — the code gets saved, it
just is not quite right. Relearning fixes almost every case of a command that
behaves oddly.

**Nothing gets captured.** Hold the remote closer to the Broadlink, within a metre
or so, and make sure its batteries are good.

**It worked and then stopped.** Check the device still has the same IP. If your
router hands out a new one, set the address again by reconfiguring the
integration, or give the device a static lease.

**The Broadlink app locked it.** The app can lock a device, which blocks anything
else from controlling it. This integration clears that lock by itself whenever it
connects, so there is nothing for you to do.

**The frequency looks wrong.** Editing an RF command shows the frequency that was
found. Remotes usually print theirs on the back or inside the battery compartment.
If they disagree, correct it and tick **Learn the code again**. Clearing the field
scans from scratch. This is rarely the problem — try relearning first.

## How it works

- Codes live in the config entry, so they survive restarts and are included in
  Home Assistant backups. There is no database and nothing to back up separately.
- Removing a command removes its button.
- The device is contacted only when you press a button, and authenticated afresh
  each time, so one that reboots or changes address recovers on its own.
- Nothing leaves your network. The Broadlink cloud is not used.

## Licence

Apache-2.0.
