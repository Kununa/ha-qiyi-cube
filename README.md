<p align="center">
  <img src="custom_components/qiyi_cube/brand/icon@2x.png" alt="QiYi Smart Cube icon" width="128">
</p>

# QiYi Smart Cube for Home Assistant

[![Tests](https://github.com/Kununa/ha-qiyi-cube/actions/workflows/tests.yml/badge.svg)](https://github.com/Kununa/ha-qiyi-cube/actions/workflows/tests.yml)
[![Validate](https://github.com/Kununa/ha-qiyi-cube/actions/workflows/validate.yml/badge.svg)](https://github.com/Kununa/ha-qiyi-cube/actions/workflows/validate.yml)

> **Vibe coded.** This integration was written almost entirely by an AI
> (Claude Code) in conversation with its owner. It was tested against one real
> cube (X-Man Tornado V4 AI) on Home Assistant 2026.10 through ESPHome
> Bluetooth proxies and has an automated test suite, but the code has not been
> reviewed line by line by a human. Use it at your own risk, and expect rough
> edges.

Local Bluetooth integration for QiYi / X-Man smart cubes. No cloud, no app.

- Every turn as an event, solved state, battery, moves, top face, orientation
- Detects **real solves** (scramble → inspection → solve) and ignores fidgeting
- Computes a short **solution** for the current state (Kociemba two-phase)
- Ships a **Lovelace card**: live 3D cube that follows the real one, animated
  turns, and a step-by-step **solve guide**

The cube protocol is the QiYi one implemented by csTimer and
smartcube-web-bluetooth (service `FFF0`, characteristic `FFF6`,
AES-128-ECB, CRC16-MODBUS).

## Requirements

- Home Assistant 2026.10 or newer (older versions are untested)
- A Bluetooth adapter or ESPHome Bluetooth proxies with
  `bluetooth_proxy: active: true` (the integration connects to the cube)
- Tested with the **X-Man Tornado V4 AI** (`XMD-TornadoV4LE-*`). Other QiYi
  smart cubes speaking the same protocol may work; orientation (gyro) data is
  specific to the Tornado V4 AI.

## Install

**HACS:** add `https://github.com/Kununa/ha-qiyi-cube` as a custom repository
(type *Integration*),
install *QiYi Smart Cube*, restart Home Assistant.

**Manually:** copy `custom_components/qiyi_cube` into your Home Assistant
`config/custom_components/` folder and restart.

Then turn a face of the cube: it is discovered automatically
(**Settings → Devices & services**). The cube only accepts one connection, so
close the phone app first.

The cube sleeps when idle and only connects while awake: pick it up and turn a
face. Values are kept while it sleeps.

## Entities

Entity ids are always English (`sensor.<cube>_solved_faces`, …) whatever the
Home Assistant language; names are translated (English, German).

| Entity | Description |
| --- | --- |
| `event.*_move` | Fires on every face turn; `event_type` is the move (`R`, `U'`, …), attribute `solved`. |
| `binary_sensor.*_solved` | Cube is solved. |
| `binary_sensor.*_solving` | A real solve is in progress (see below). |
| `binary_sensor.*_connectivity` | Connected right now (the cube sleeps when idle). |
| `sensor.*_last_move` | Last move. |
| `sensor.*_moves_since_solved` | Moves since the cube last left the solved state; 0 while solved. |
| `sensor.*_last_solve_moves` / `_last_solve_duration` | Moves and time of the last **real** solve, from the first turn after inspection until solved. The duration has attributes `tps`, `scramble_moves`, `scramble_distance`, `inspection_seconds`. |
| `sensor.*_solved_faces` | Number of solved faces (0–6). Attributes: `facelets` (54-character string, URFDLB order) and `face_u` … `face_b` (9 facelets per face). |
| `sensor.*_moves_to_solve` | Length of a short solution from the current state; attribute `solution`, e.g. `R U2 F' …`. Updated ~0.3 s after the last turn. |
| `sensor.*_top_face` | Colour of the face pointing up (`white`, `yellow`, `green`, `blue`, `red`, `orange`; standard colour scheme). Changes only when another face ends up on top. |
| `sensor.*_battery` | Battery %. |
| `sensor.*_orientation` | Raw gyro quaternion (diagnostic), attributes `w`/`x`/`y`/`z`; updated at most once a second while connected. |

### Real solves vs. fidgeting

A solve only counts when the cube was **well mixed** and then **not turned for
at least 3 seconds** (inspection) before solving it. The first turn after that
pause starts the timer; later thinking pauses don't matter. "Well mixed" means
at most 5 of the 20 pieces are in place and, once the solver is ready, the
solution is at least 12 moves long – fidget patterns like `R U R' U'` or
turning a face back and forth never get there. Disconnecting mid-solve
abandons it.

### Example automations

```yaml
# Notify after a real solve
triggers:
  - trigger: state
    entity_id: binary_sensor.xmd_tornadov4le_04e4_solving
    from: "on"
    to: "off"
conditions:
  - condition: state
    entity_id: binary_sensor.xmd_tornadov4le_04e4_solved
    state: "on"
actions:
  - action: notify.notify
    data:
      message: >
        Solved in {{ states('sensor.xmd_tornadov4le_04e4_last_solve_duration') }} s
        ({{ states('sensor.xmd_tornadov4le_04e4_last_solve_moves') }} moves)!
```

```yaml
# Red desk light while solving
triggers:
  - trigger: state
    entity_id: binary_sensor.xmd_tornadov4le_04e4_solving
    to: "on"
actions:
  - action: light.turn_on
    target:
      entity_id: light.desk
    data:
      color_name: red
```

## Lovelace card

The integration ships a card and loads it into the frontend automatically (no
resource to add; reload the browser once after installing or updating). Add
*QiYi Cube* from the card picker and configure it in the visual editor, or in
YAML:

```yaml
type: custom:qiyi-cube-card
entity: sensor.xmd_tornadov4le_04e4_solved_faces  # optional, any entity of the cube
title: My cube          # optional
view: 3d                # default; "net" shows the flat unfolded cube instead
show_header: true       # status chips
show_solution: true     # "to solve" move count
show_solve_button: true
show_last_solve: true
```

**3D view:** the cube with its real colours **follows the real cube live**
while it is connected and **animates every turn** (gyro data and moves are
streamed over a websocket, not recorded). It scales with the card width. The
cube knows which way is up but not which way it faces, so the view turns its
front towards you when the stream starts – **tap the cube or the rotate button
to reset the orientation**. While the cube sleeps it rests white up, green
front.

Below the cube the card shows how many moves are left to solve (with
"calculating…" while you turn) and the last real solve.

**Solve guide:** the *Solve* button walks you through the current solution
move by move. The layer to turn is highlighted on the 3D cube, with a curved
arrow on the face and straight arrows on its four neighbouring faces, so the
direction is visible from any side (also for the back face). Every turn of the
real cube advances the guide. A wrong turn adds a step that undoes it; if the
guide loses track it waits for the next solution from Home Assistant. After
"Solved!" the card returns to its normal view after a few seconds.

## Solver

Solutions come from [RubikTwoPhase](https://github.com/hkociemba/RubiksCube-TwophaseSolver)
(GPLv3), a pure-Python implementation of Kociemba's two-phase algorithm. It
stops at the first solution of at most 20 moves (usually a few milliseconds)
and runs in a separate low-priority process, so Home Assistant itself never
waits for it.

On first start it builds about 80 MB of lookup tables in
`<config>/.cache/qiyi_cube/twophase` (not included in backups). This runs once
in the background and takes 30–60 minutes on a Raspberry Pi; until then the
solution sensor stays empty. Tables built on another 64-bit little-endian
machine can be copied there instead (include the `.complete` marker file).

## Development

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements_test.txt
.venv/bin/python -m pytest                      # protocol, cube logic, HA integration
.venv/bin/python tools/live_test.py 30          # talk to a real cube from this machine
.venv/bin/python tools/capture.py 90            # dump raw decrypted frames
.venv/bin/python tools/gyro_capture.py 120      # print the quaternion stream
```

GitHub Actions runs the tests (`tests.yml`) and Home Assistant's hassfest plus
the HACS validation (`validate.yml`, also weekly) on every push and pull
request.

**Releasing:** GitHub → *Actions* → *Release* → *Run workflow*, enter the
new version (e.g. `0.6.0`). The workflow runs the tests, sets the version in
`manifest.json`, tags `v0.6.0`, and publishes a release with generated notes
and `qiyi_cube.zip`, which HACS installs. Tick *dry run* to try it without
publishing anything.

`protocol.py`, `cube.py` and `solver.py` have no Home Assistant imports, so the
tools can use them directly. The tools need the cube to themselves: disable
the integration while they run. `CLAUDE.md` holds the protocol notes and
design decisions collected while building this.

## Credits

- [csTimer](https://github.com/cs0x7f/cstimer) and
  [smartcube-web-bluetooth](https://github.com/poliva/smartcube-web-bluetooth)
  for the QiYi protocol
- Herbert Kociemba for the two-phase algorithm and
  [RubikTwoPhase](https://github.com/hkociemba/RubiksCube-TwophaseSolver)

## License

MIT – see [LICENSE](LICENSE). The solver dependency RubikTwoPhase is GPLv3
and installed separately by Home Assistant.
