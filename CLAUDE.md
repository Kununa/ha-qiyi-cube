# QiYi Smart Cube – Home Assistant integration

Custom HA integration (`custom_components/qiyi_cube`) that connects an
**X-Man Tornado V4 AI** smart cube (QiYi protocol) to Home Assistant over
Bluetooth LE. The user's HA uses **ESPHome Bluetooth proxies**. Modelled on
csTimer's `qiyicube.js` / smartcube-web-bluetooth.

## Status (2026-10-11)

- Protocol verified live (`tools/live_test.py`); quaternion order calibrated.
- **Installed in the user's HA** (v0.3.0, HA 2026.10.1 on HA OS / RPi 5) and
  working through the ESPHome proxies: discovery, entities, solver (tables
  pre-built on the Mac and copied to `/config/.cache/qiyi_cube/twophase`),
  Lovelace card served at `/qiyi_cube/qiyi-cube-card.js`. Deploy = tar over
  SSH + restart (see memory `ha-ssh-access`); ha-mcp gives 502 for ~1–2 min
  after a restart while Core is still starting.
- Untested on real use yet: real-solve thresholds, smoothness of the live 3D
  view over the proxy.
- Public repo https://github.com/Kununa/ha-qiyi-cube (MIT), pushed with `gh`
  (user logged in as Kununa). README states the project is vibe coded – keep that.

## The user's cube

- Name `XMD-TornadoV4LE-04E4`, MAC `CC:A9:00:00:04:E4`.
- Advertises manufacturer ID `0x0504` (1284, QiYi); first 6 bytes of that
  manufacturer data are the MAC reversed (`e4 04 00 00 a9 cc`). On macOS bleak
  gives UUID addresses, so the MAC **must** come from manufacturer data there.
- The cube sleeps when idle and only advertises after a face is turned. When
  testing live, ask the user to turn the cube and close the phone app (only
  one connection at a time).
  Since the integration is installed in HA, HA grabs the cube too: disable the
  config entry (ha-mcp `ha_set_integration enabled=false`, with the user's OK)
  before running the tools/ scripts, re-enable afterwards.

## Protocol (see `protocol.py`)

- Service `FFF0`, characteristic `FFF6` (notify + write-without-response).
- Every frame is AES-128-ECB with key `57b1f9abcd5ae8a79cb98ce7578c5108`,
  16-byte blocks. Decrypted: `header, length, payload…, CRC16-MODBUS (LE)`,
  zero padded. Valid frame ⇔ CRC over `msg[:length]` == 0.
- App → cube hello: `FE 15 00 6B 01 00 00 22 06 00 02 08 00 <mac reversed> crc`.
- `FE` opcode `0x02` hello/state and `0x03` state change: bytes 3–6 cube
  timestamp ms (BE), 7–33 facelets (54 nibbles, low nibble first, values index
  `"LRDUFB"`, faces in URFDLB order), 34 move (1..12 = L' L R' R D' D U' U F' F
  B' B), 35 battery %. **Both must be ACKed** by sending back `msg[2:7]` as a frame.
  If the ACK is late (seen through the ESPHome proxy) the cube **resends the
  same 0x03 frame**; `cube.py` drops a turn whose cube timestamp equals the
  previous turn's (still ACKs it).
  Opcode 0x03 frames are 94 bytes: after the battery byte comes the move
  history – `ff` padding, then up to 10 entries of `timestamp(4, BE) move(1)`
  (oldest first, newest = previous move), then 1 byte that is `01` when the
  cube is solved, then CRC (decoded from `tools/capture.py` output
  2026-10-11). Not used yet; we trust the facelets instead.
- `CC` frames (length 16, ~13/s, Tornado V4 AI only): seq, uint16 timer,
  battery, 4× int16 BE quaternion ×1000 in wire order **x, y, w, z**, CRC.
  Verified 2026-10-11 by holding each colour up (`tools/gyro_capture.py`,
  data in `tests/test_protocol.py::CALIBRATION`): the orientation is
  gravity-referenced (no drift, absolute "up"), and `protocol.up_vector`
  gives up in cube coordinates (+x=U, −x=D, +y=L, −y=R, +z=F, −z=B). Yaw
  reference is unknown, so only the top face is derived, not the front face.
  The stream stopped after ~80 s of lying still in that capture.
  The battery byte reads **101 while the cube sits in its charging box** (seen
  with a full battery and an *unpowered* box, so it means "in box", not
  "charging"); FE frames still say 100. Behaviour with a powered box and a
  non-full battery is unknown. We only clamp battery to 100; an "on charger"
  sensor was built and dropped (value goes stale once the cube sleeps). The advertisement's bytes after the MAC
  (`01 24 0a 00 01 21 1e 01 01 17`) are still unexplained.
- There is a second vendor service `5833ff01-9b8b-5191-6142-22a4536ef123`
  (write `…ff02`, notify `…ff03`) – unexplored.

## Code layout

- `protocol.py`, `cube.py`, `solver.py` – pure Python (no HA imports), so they
  run standalone in `tools/live_test.py`. Keep it that way.
- `solver.py` wraps RubikTwoPhase (pure Python, GPLv3; `kociemba` on PyPI has
  no wheels for HA's aarch64/Alpine). Its tables (~80 MB, 30+ min to build)
  live in `<config>/.cache/qiyi_cube/twophase`; built in a `nice`d subprocess
  so HA keeps the GIL. Searching also runs in a long-lived worker process
  (`SolverProcess`, line protocol over stdin/stdout): in-process the 6 search
  threads held the GIL and stalled HA's event loop (115 ms on the Mac, worse on
  the Pi) – the card's live 3D view stuttered after every turn.
  Search settings (`const.py`): start 0.3 s after the last turn, stop at the
  first solution ≤ 20 moves (~10–40 ms on the Mac); a full 1 s search only
  saved ~1 move. The card shows "calculating…" while the sensor's solution
  doesn't solve the current (live) state – checked by simulation. Tests patch the solver out. Facelet strings are passed
  through unchanged – QiYi's URFDLB order matches Kociemba's.
- `coordinator.py` – HA glue: registers a Bluetooth advertisement callback and
  connects whenever the cube advertises while disconnected; throttles gyro
  updates; fans out to entity listeners.
- `brand/` – icon.png/@2x + dark_ variants (HA ≥ 2026.x serves brand images
  from custom integrations itself). Generated by `tools/make_icon.py`; don't
  use QiYi's real logo (trademark).
- Entities: `event.py` (move event per turn), `binary_sensor.py` (solved,
  connectivity), `sensor.py` (battery, last move, moves since solved, last
  solve moves/duration, solved faces with facelets as attributes, top face,
  moves to solve with the solution as attribute, raw orientation). Sensors use
  `RestoreSensor` because the cube is asleep most of the time.
- `websocket.py` – `qiyi_cube/subscribe_live` (entity_id → stream of
  `{"q": [w,x,y,z]}` per gyro sample, `{"q": null}` on disconnect,
  `{"move", "facelets"}` per quarter turn) for the card's live 3D view and
  turn animation; bypasses states/recorder.
- Entity ids are forced English via `entity.with_english_ids` (sets
  `entity.entity_id` from the description key before adding; user wants
  English ids although HA runs in German). Only affects new registry entries.
- `frontend/qiyi-cube-card.js` – vanilla custom element (no build step, no
  lit). 3D view = 54 individually placed sticker divs (CSS 3D transforms) so
  a layer can rotate for the turn animation; DOM is built once and only
  patched (a rebuild would kill a running animation); exactly one live
  subscription per card (Lovelace detaches/re-attaches cards while
  `subscribeMessage` is pending – that leaked a second subscription and every
  turn animated twice); turns that don't change the facelets (vs. the last
  queued/running turn) are skipped. Headless Chrome doesn't run
  requestAnimationFrame reliably under --virtual-time-budget – stub it with
  setTimeout in test pages. The card simulates the cube itself (sticker
  permutations derived from the 3D geometry, checked against twophase) for the
  solve guide; the visual editor uses `ha-form` (stub it in test pages). frame conventions are documented at the
  top of the file and checked against the calibration quaternions. For visual
  checks render static HTML with headless Chrome
  (`"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --headless=new
  --user-data-dir=<scratch> --screenshot=… file://…`; it writes the PNG but
  doesn't exit – stop it). Quick Look can't do preserve-3d. `async_setup` serves it at `/qiyi_cube/qiyi-cube-card.js` and adds it
  via `frontend.add_extra_js_url` (`?v=<manifest version>` busts the cache, so
  bump the version when the card changes). Finds sibling entities through the
  device + `translation_key`. No node here: smoke-test it with macOS
  JavaScriptCore (`/System/Library/Frameworks/JavaScriptCore.framework/Versions/Current/Helpers/jsc`)
  and a stubbed `HTMLElement`/`customElements`.
- "Last solve" = real solves only (the user wants fidgeting ignored): first
  pause ≥ 3 s after leaving solved while well mixed (≤ 5 solved pieces and,
  if the solver has a result for that state, distance ≥ 12) starts the solve
  at the next turn. Constants at the top of `cube.py`, tests in
  `tests/test_cube.py` (simulated cube via twophase.cubie). User scrambles by
  random turning, inspects a few seconds, solves in 2+ min (beginner).
  Two-phase overestimates patterned states (`(R U R' U')×3` → 15), hence the
  piece count. Thresholds are untested on real solves yet.

## Commands

```sh
.venv/bin/python -m pytest              # all tests (protocol + HA)
.venv/bin/python tools/live_test.py 30  # talk to the real cube for 30 s
.venv/bin/python tools/capture.py 90    # dump raw decrypted frames (find unknown fields)
.venv/bin/python tools/gyro_capture.py 120  # print the quaternion stream
```

`.venv` is created from `requirements_test.txt` (HA test harness + the
Bluetooth packages HA's bluetooth component needs; versions match HA 2026.10).
Recreate with `python3 -m venv .venv && .venv/bin/pip install -r requirements_test.txt`.

## Ideas / open items

- Verify behaviour through ESPHome proxies (connection slots, reconnects).
- Use the 0x03 move history (format now known) to recover moves dropped over
  a flaky proxy link.
- Check what the battery byte does while really charging (powered box, battery < 100).
- Explore the `5833ff01` service; find a command to stop the gyro stream.
- Proper solve timer (detect scramble end / inspection) if the user wants it.
