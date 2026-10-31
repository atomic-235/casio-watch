# Agent notes

## Logs

**Never suppress command output.** Do not pipe commands through `tail`, `head`, `grep`, `2>/dev/null`, or any other filter when running, testing, or verifying something. Print the complete output. Truncation is the harness's job, never the agent's.

## Python environment

This project uses uv2nix. The environment is managed by Nix — do not use pip or create virtualenvs manually.
There is intentionally **no bubblewrap sandbox**: BLE needs direct access to the BlueZ D-Bus socket
(`/run/dbus/system_bus_socket`), which bwrap blocks.

**Run Python:**

```bash
python <script.py>
```

**Run the TUI:**

```bash
casio-watch-tui          # real watch
casio-watch-tui --mock   # fake watch
```

**Enter the environment:**

```bash
direnv allow .           # once, after editing .envrc
direnv reload            # after changing flake.nix
```

**Add a dependency:**

1. Add it to `[project.dependencies]` in `pyproject.toml`
2. Run `UV_PYTHON="" UV_PYTHON_DOWNLOADS=never uv lock`
3. Run `touch flake.nix && direnv reload` to rebuild the environment

**Run a command in the environment (from any directory):**

```bash
direnv exec /home/antonym/projects/personal/casio <command>
```

Do not run `uv sync`, `pip install`, or `python -m venv`. The venv is built by Nix and is read-only.

## Casio BLE gotchas

- Never call `BleakClient.pair()` on these watches: BlueZ gets
  `org.bluez.Error.AuthenticationFailed`, the watch displays `ERR`, and the link dies.
  Unbonded GATT writes work fine.
- The watch advertises only briefly after holding the lower-left `MODE` button
  (~3 s). Start the command, then press the button.
- Hourly chime is bit `0x80` on alarm slot 0, not a separate setting.
- `get_basic_settings()` carries library defaults for `time_adjustment`
  (`True`, 30 min); the real state comes from `get_time_adjustment()`.
- The library raises `RuntimeError("...result is not set")` when the watch sends
  an unsolicited notification before a read registers its result.
  `casio_watch.compat.install()` swallows those packets and is called by both
  entry points.
- GBX-100 / GBD watches need Casio's app-level init ("pairing") sequence before
  they will do anything but answer a few plain reads. `casio_watch.pairing`
  ports Gadgetbridge's `gbx100/InitOperation`: app info, BLE settings,
  advertising/connection parameters, module ID → condition → version → DST, then
  current time + `00 01` when the watch asks with `0x47 02`. It finishes with
  `0x3D`. Pairing runs on every connect and needs no button press on the watch.
- The init packet's write is never acknowledged; write it without waiting or the
  connect hangs (Gadgetbridge aborts the transaction for the same reason).
- Subscribe only to the ALL_FEATURES characteristic (`26eb002d…`). Subscribing
  to the step-counter/convoy characteristics as the library does makes the
  GBX-100 drop the link.
- gshock_api only resolves the watch model inside its own scanner; `ble.py`
  connects directly, so it calls `watch_info.set_name_and_model()` itself.
  Without that every capability check falls back to GENERIC.
- The GBX-100 advertises a new random address on most connections, so a saved
  address is only a hint — always scan.
- The GBX-100 has no thermometer; the condition packet's second byte is not a
  temperature, and its battery byte is not a 9..19 scale either.

## TUI testing

- `casio-watch-tui --mock` runs against `casio_watch.backend.FakeBackend`.
- `tests/tmux_scenarios.sh` drives the mock TUI through tmux and asserts on
  `capture-pane` output. Run it after any TUI change.
- Interaction model (lazygit/nvim): panels `1`/`2`/`3`, selection `j/k`, toggle
  `space`, edit `enter`, cancel `esc`, filter `/`, help `?`. Never reintroduce
  tab-through-fields or global printable-key editing.
- Reminders are day-level (Casio's protocol has no hour/minute), max 5 slots,
  each with title/date/repeat/enabled. The TUI sends all five slots back on
  write; `FakeBackend` mirrors them for tmux tests.
- Text editing happens only in the bottom `EditorInput`; `enter` submits,
  `esc` cancels.
- Textual inputs need width >= border(2) + padding(2) + text, or the content
  area is 0 columns and typed text is invisible.
