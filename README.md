# casio — Casio G-Shock BLE control

CLI to read and configure Casio G-Shock watches from Linux over Bluetooth LE
(BlueZ), using [`gshock-api`](https://github.com/izivkov/gshock_api).

Tested with a GA-B2100.

## Usage

Put the watch in connect mode (hold the lower-left `MODE` button for ~3 s),
then:

```bash
casio-watch scan                          # list nearby CASIO devices
casio-watch -a AA:BB:CC:DD:EE:FF status   # read state
casio-watch -a AA:BB:CC:DD:EE:FF time     # sync the clock
casio-watch -a AA:BB:CC:DD:EE:FF alarms get
casio-watch -a AA:BB:CC:DD:EE:FF alarms disable
casio-watch -a AA:BB:CC:DD:EE:FF alarms enable 0
casio-watch -a AA:BB:CC:DD:EE:FF alarms chime on
casio-watch -a AA:BB:CC:DD:EE:FF settings get
casio-watch -a AA:BB:CC:DD:EE:FF settings set time_format 24h
casio-watch -a AA:BB:CC:DD:EE:FF timer set 600
```

The address can be omitted, in which case the CLI scans for a `CASIO …` device.

## TUI

```bash
casio-watch-tui
```

Press **`s`** and hold the watch's lower-left `MODE` button for ~3 s. The watch
is saved to `~/.config/casio-watch/config.json`, so later sessions are just
`s`. The TUI shows battery/temperature and edits clock format, date format,
language, light duration, auto light, power saving, button tone, time
adjustment and all five alarms/chime.

It follows the lazygit/nvim model: lists, a normal mode, and one bottom-line
prompt for text.

| Key | Action |
|---|---|
| `1` / `2` / `3` | Settings / Alarms / Reminders panel |
| `tab` | next panel |
| `j` / `k` | move selection |
| `g` / `G` | first / last row |
| `space` | toggle value or alarm |
| `enter` | edit value / open menu |
| `c` | toggle hourly chime (alarms) |
| `/` | filter rows |
| `s` / `r` / `t` | scan / refresh / sync clock |
| `w` | write changes (confirmation panel) |
| `?` / `q` | help / quit |

Editing uses the bottom prompt: `enter` commits, `esc` cancels. Digits only
type while the prompt is open — there is no tab-through-fields. In the
Reminders panel, `enter` opens a menu (title, date, repeat period, toggle,
clear); dates are entered as `YYYY-MM-DD` and are day-level, matching Casio's
reminder protocol.

Mock mode (no watch needed):

```bash
casio-watch-tui --mock
```

### TUI tests

```bash
direnv exec . bash tests/tmux_scenarios.sh
```

Drives the mock TUI in tmux: connect, panel switching, enter-prompt editing of
alarm time, write confirmation, filtering, help.


## Credits

The BLE protocol implementation is [`gshock-api`](https://github.com/izivkov/gshock_api)
by Ivo Zivkov (MIT). This project is a Linux CLI/TUI on top of it.

## Notes

- Do **not** call `BleakClient.pair()` — Casio watches reject BLE pairing with
  `org.bluez.Error.AuthenticationFailed` and the watch shows `ERR`. GATT writes
  work without bonding.
- Casio watches only advertise for a short window after the connect button is
  pressed; start the command first, then press the button.
- The hourly chime is the `0x80` flag on alarm slot 0.
