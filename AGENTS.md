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

**Run the CLI:**

```bash
casio-watch --help
```

**Add a dependency:**

1. Add it to `[project.dependencies]` in `pyproject.toml`
2. Run `UV_PYTHON="" UV_PYTHON_DOWNLOADS=never uv lock`
3. Run `touch flake.nix && direnv reload` to rebuild the environment

**Run a command in the environment:**

```bash
direnv exec . <command>
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

## TUI testing

- `casio-watch-tui --mock` runs against `casio_watch.backend.FakeBackend`.
- `tests/tmux_scenarios.sh` drives the mock TUI through tmux and asserts on
  `capture-pane` output. Run it after any TUI change.
- Interaction model (lazygit/nvim): panels `1`/`2`, selection `j/k`, toggle
  `space`, edit `enter`, cancel `esc`, filter `/`, help `?`. Never reintroduce
  tab-through-fields or global printable-key editing.
- Text editing happens only in the bottom `EditorInput`; `enter` submits,
  `esc` cancels.
- Textual inputs need width >= border(2) + padding(2) + text, or the content
  area is 0 columns and typed text is invisible.
