### Virtual Test Devices for Home Assistant

Virtual devices for testing automations — including **clones of your real
devices** that report the same abilities, so you can test against a stand-in
instead of the real thing.

Works on its own from Home Assistant's own Actions screen. Also the test bench
for [PistonCore](https://github.com/jercoates/pistoncore-v2).

**A fork of [twrecked/hass-virtual](https://github.com/twrecked/hass-virtual)
that uses the same `virtual` domain — install this or hass-virtual, not both.**

Adds `alarm_control_panel`, `camera`, `climate`, `media_player`, `notify`,
`siren`, `humidifier`, `vacuum`, `button` and `event`; lets every device state
its real `supported_features`, modes and limits; and fixes three silent
data-loss bugs.

The camera hands over a real picture, so a snapshot writes a real file. The
notifier records what was sent — message, title and a count — so you can see
what a notification said without owning a phone app or an SMS service.

See the [README](https://github.com/jercoates/ha-virtual-test-devices/blob/main/README.md)
for the full picture.
