// Lovelace card for the QiYi Smart Cube integration.
// Served and registered by the integration itself (see __init__.py).
//
//   type: custom:qiyi-cube-card
//   entity: sensor.xmd_tornadov4le_04e4_solved_faces   # optional
//   view: 3d        # or "net" for the flat unfolded cube
//   show_header / show_solution / show_solve_button / show_last_solve: true
// (all of it can be set in the visual editor)
//
// The other entities (solution, battery, ...) are found through the device of
// `entity`. The 3D view follows the cube live and animates every turn, using
// the integration's `qiyi_cube/subscribe_live` websocket command.

const FACES = "URFDLB";
const COLORS = {
  U: "#f4f4f4", R: "#d7263d", F: "#1fa64a", D: "#ffd500", L: "#ff7a00", B: "#1e62d0",
};
const COLOR_FACE = {
  white: "U", red: "R", green: "F", yellow: "D", orange: "L", blue: "B",
};
// Net position (column, row) of each face, in units of one face.
const NET = { U: [1, 0], L: [0, 1], F: [1, 1], R: [2, 1], B: [3, 1], D: [1, 2] };
const TURN_MS = 160; // duration of one animated quarter turn

const TEXT = {
  en: {
    solved: "Solved", faces: "faces solved", solution: "Solution", moves: "moves",
    waiting: "Searching…", asleep: "Asleep", connected: "Connected",
    solving: "Solving…", lastSolve: "Last solve", tps: "TPS", align: "Reset orientation (front towards you)",
    noEntity: "No QiYi cube found. Set `entity` to the cube's solved faces sensor.",
    toSolve: "To solve", calculating: "calculating…", solve: "Solve", stop: "Stop", close: "Close", guideDone: "Solved! 🎉",
    recalc: "Recalculating…", wait: "Waiting for a solution…", undoHint: "undo the last turn",
    step: (i, n) => `Step ${i} of ${n}`,
    hint: "Direction as seen when looking straight at that face.",
    turnText: (face, q) =>
      `Turn the ${{ U: "white", R: "red", F: "green", D: "yellow", L: "orange", B: "blue" }[face]} face ` +
      ["", "clockwise", "twice (half turn)", "counter-clockwise"][q],
  },
  de: {
    solved: "Gelöst", faces: "Seiten gelöst", solution: "Lösung", moves: "Züge",
    waiting: "Suche…", asleep: "Schläft", connected: "Verbunden",
    solving: "Löst…", lastSolve: "Letzte Lösung", tps: "Züge/s", align: "Ausrichtung zurücksetzen (Vorderseite zu dir)",
    noEntity: "Kein QiYi-Würfel gefunden. Setze `entity` auf den Sensor „Gelöste Seiten“.",
    toSolve: "Bis gelöst", calculating: "wird berechnet…", solve: "Lösen", stop: "Beenden", close: "Schließen", guideDone: "Gelöst! 🎉",
    recalc: "Neu berechnen…", wait: "Warte auf eine Lösung…", undoHint: "letzten Zug rückgängig machen",
    step: (i, n) => `Schritt ${i} von ${n}`,
    hint: "Richtung von vorne auf diese Seite gesehen.",
    turnText: (face, q) =>
      `Drehe die ${{ U: "weiße", R: "rote", F: "grüne", D: "gelbe", L: "orange", B: "blaue" }[face]} Seite ` +
      ["", "im Uhrzeigersinn", "zweimal (halbe Drehung)", "gegen den Uhrzeigersinn"][q],
  },
};

// --- 3D math ------------------------------------------------------------------
// 3×3 matrices as row arrays, acting on column vectors.
//
// Frames (all right-handed):
//   P  physical cube frame of the facelet string: X = R, Y = U, Z = F
//   C  the cube's gyro frame: x = U, y = L, z = F (see protocol.up_vector)
//   W  world: z = up (gravity), heading arbitrary
//   D  display: x = right, y = up, z = towards the viewer
// CSS uses x right, y DOWN, z towards the viewer, hence S = diag(1, -1, 1).

const mul = (a, b) =>
  a.map((row) => [0, 1, 2].map((j) => row[0] * b[0][j] + row[1] * b[1][j] + row[2] * b[2][j]));
const tr = (a) => [0, 1, 2].map((i) => [a[0][i], a[1][i], a[2][i]]);
const col = (a, j) => [a[0][j], a[1][j], a[2][j]];
const apply = (m, v) => m.map((r) => r[0] * v[0] + r[1] * v[1] + r[2] * v[2]);
const dot = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
const cross = (a, b) => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
const flipY = (v) => [v[0], -v[1], v[2]]; // S
const S = [[1, 0, 0], [0, -1, 0], [0, 0, 1]];
const IDENTITY = [[1, 0, 0], [0, 1, 0], [0, 0, 1]];
const P_TO_C = [[0, 1, 0], [-1, 0, 0], [0, 0, 1]];
const W_TO_D = [[1, 0, 0], [0, 0, 1], [0, -1, 0]]; // world -y faces the viewer
const rotX = (a) => [[1, 0, 0], [0, Math.cos(a), -Math.sin(a)], [0, Math.sin(a), Math.cos(a)]];
const rotY = (a) => [[Math.cos(a), 0, Math.sin(a)], [0, 1, 0], [-Math.sin(a), 0, Math.cos(a)]];
const rotZ = (a) => [[Math.cos(a), -Math.sin(a), 0], [Math.sin(a), Math.cos(a), 0], [0, 0, 1]];
// Rotation by `a` (right-handed) about a cardinal axis given as a unit vector.
function rotAbout(n, a) {
  if (n[0]) return rotX(n[0] * a);
  if (n[1]) return rotY(n[1] * a);
  return rotZ(n[2] * a);
}
// Look from slightly above and to the right, so U, F and R are visible.
const CAMERA = mul(rotX((25 * Math.PI) / 180), rotY((-30 * Math.PI) / 180));
// Cube at rest when there is no gyro data: white up, green towards the viewer.
const C_REST = [[0, -1, 0], [0, 0, -1], [1, 0, 0]];

// Quaternion (w, x, y, z) from the cube -> rotation W -> C.
function quatMatrix([w, x, y, z]) {
  const n = Math.hypot(w, x, y, z) || 1;
  [w, x, y, z] = [w / n, x / n, y / n, z / n];
  return [
    [1 - 2 * (y * y + z * z), 2 * (x * y - w * z), 2 * (x * z + w * y)],
    [2 * (x * y + w * z), 1 - 2 * (x * x + z * z), 2 * (y * z - w * x)],
    [2 * (x * z - w * y), 2 * (y * z + w * x), 1 - 2 * (x * x + y * y)],
  ];
}

// Heading that turns the cube's front (or right) face towards the viewer.
function alignHeading(cToW) {
  const f = col(cToW, 2);
  if (Math.hypot(f[0], f[1]) > 0.5) return -Math.PI / 2 - Math.atan2(f[1], f[0]);
  const r = col(cToW, 1).map((v) => -v);
  return -Math.atan2(r[1], r[0]);
}

function matrix3d(m, t = [0, 0, 0]) {
  const v = [m[0][0], m[1][0], m[2][0], 0, m[0][1], m[1][1], m[2][1], 0,
             m[0][2], m[1][2], m[2][2], 0, t[0], t[1], t[2], 1];
  return `matrix3d(${v.map((x) => +x.toFixed(5)).join(",")})`;
}

// Per face: [column direction, row direction, outward normal] in frame P,
// matching the facelet order of the cube state string.
const FACE_AXES = {
  U: [[1, 0, 0], [0, 0, 1], [0, 1, 0]],
  R: [[0, 0, -1], [0, -1, 0], [1, 0, 0]],
  F: [[1, 0, 0], [0, -1, 0], [0, 0, 1]],
  D: [[1, 0, 0], [0, 0, -1], [0, -1, 0]],
  L: [[0, 0, 1], [0, -1, 0], [-1, 0, 0]],
  B: [[-1, 0, 0], [0, -1, 0], [0, 0, -1]],
};

// The 54 stickers: local axes and centre (in sticker units) in frame P.
const STICKERS = [...FACES].flatMap((face) => {
  const [c, r, n] = FACE_AXES[face];
  return [...Array(9)].map((_, i) => {
    const dc = (i % 3) - 1;
    const dr = Math.floor(i / 3) - 1;
    return { c, r, n, pos: [0, 1, 2].map((k) => 1.5 * n[k] + dc * c[k] + dr * r[k]) };
  });
});

// --- cube simulation (derived from the sticker geometry) ---------------------

const stickerKey = (pos, n) => [...pos, ...n].map((v) => Math.round(v * 2)).join(",");
const STICKER_AT = new Map(STICKERS.map((st, i) => [stickerKey(st.pos, st.n), i]));
// Per face: index each sticker moves to on a clockwise quarter turn.
const TURN_PERM = Object.fromEntries(
  [...FACES].map((face) => {
    const n = FACE_AXES[face][2];
    const rot = rotAbout(n, -Math.PI / 2);
    const perm = STICKERS.map((st, i) =>
      apply([n], st.pos)[0] > 0.5 ? STICKER_AT.get(stickerKey(apply(rot, st.pos), apply(rot, st.n))) : i,
    );
    return [face, perm];
  }),
);

function turnFacelets(facelets, face, quarters) {
  let cur = facelets;
  for (let q = 0; q < quarters % 4; q++) {
    const next = new Array(54);
    TURN_PERM[face].forEach((j, i) => {
      next[j] = cur[i];
    });
    cur = next.join("");
  }
  return cur;
}

const isSolvedState = (f) =>
  typeof f === "string" && [...FACES].every((face, k) => f.slice(k * 9, k * 9 + 9) === face.repeat(9));
// "R U2 F'" -> [{face, quarters}] with clockwise quarter turns 1..3
const parseMoves = (text) =>
  (text || "").trim().split(/\s+/).filter((m) => FACES.includes(m[0])).map((m) => ({
    face: m[0],
    quarters: m.endsWith("'") ? 3 : m.endsWith("2") ? 2 : 1,
  }));
const moveName = (step) => step.face + ["", "", "2", "'"][step.quarters];
const applySteps = (f, steps) => steps.reduce((acc, st) => turnFacelets(acc, st.face, st.quarters), f);

// Curved arrow for a face, drawn clockwise as seen looking at the face.
function arrowSvg(quarters) {
  const r = 30;
  const pt = (deg) => [50 + r * Math.cos((deg * Math.PI) / 180), 50 + r * Math.sin((deg * Math.PI) / 180)];
  const [a0, a1] = [-150, 115];
  const [x0, y0] = pt(a0);
  const [x1, y1] = pt(a1);
  const t = (a1 * Math.PI) / 180;
  const [tx, ty, nx, ny] = [-Math.sin(t), Math.cos(t), Math.cos(t), Math.sin(t)];
  const f = (v) => v.toFixed(1);
  const head = [[x1 + tx * 17, y1 + ty * 17], [x1 - tx * 3 + nx * 12, y1 - ty * 3 + ny * 12],
    [x1 - tx * 3 - nx * 12, y1 - ty * 3 - ny * 12]]
    .map(([x, y]) => `${f(x)},${f(y)}`).join(" ");
  const arc = `M${f(x0)} ${f(y0)} A${r} ${r} 0 1 1 ${f(x1)} ${f(y1)}`;
  const flip = quarters === 3 ? ` transform="translate(100 0) scale(-1 1)"` : "";
  const two = quarters === 2
    ? `<text x="50" y="62" text-anchor="middle" font-size="34" font-weight="700" fill="#fff" stroke="#000" stroke-width="1.5">2</text>`
    : "";
  return `<svg viewBox="0 0 100 100"><g${flip} stroke-linecap="round" fill="none">
    <path d="${arc}" stroke="#000" stroke-opacity="0.55" stroke-width="12"/>
    <path d="${arc}" stroke="#fff" stroke-width="7"/>
    <polygon points="${head}" fill="#fff" stroke="#000" stroke-width="1.5"/></g>${two}</svg>`;
}

// Straight arrow pointing along +x, for a 3×1 strip of stickers.
function straightArrowSvg(quarters) {
  const two = quarters === 2
    ? `<text x="150" y="64" text-anchor="middle" font-size="40" font-weight="700" fill="#fff" stroke="#000" stroke-width="2">2</text>`
    : "";
  return `<svg viewBox="0 0 300 100" preserveAspectRatio="none"><g stroke-linejoin="round">
    <path d="M30 50 H230" stroke="#000" stroke-opacity="0.55" stroke-width="22" stroke-linecap="round"/>
    <path d="M30 50 H230" stroke="#fff" stroke-width="14" stroke-linecap="round"/>
    <polygon points="285,50 225,18 225,82" fill="#fff" stroke="#000" stroke-opacity="0.7" stroke-width="3"/></g>${two}</svg>`;
}

// CSS transform of a square element whose local x/y/z become the P-frame
// vectors c/r/n (rotated by `rot`), centred at `pos` (sticker units).
function placeTransform(c, r, n, pos, rot, unit) {
  const [c2, r2, n2, p2] = [c, r, n, pos].map((v) => flipY(apply(rot, v)));
  return matrix3d(tr([c2, r2, n2]), p2.map((v) => v * unit));
}

// P (as CSS) -> screen (CSS) for a gyro matrix W -> C and a heading.
function cubeTransform(cToW, heading) {
  const a = mul(mul(mul(mul(CAMERA, W_TO_D), rotZ(heading)), cToW), P_TO_C);
  return matrix3d(mul(mul(S, a), S));
}

// --- helpers ----------------------------------------------------------------

function formatTime(secs) {
  const m = Math.floor(secs / 60);
  const s = (secs - m * 60).toFixed(2).padStart(5, "0");
  return m ? `${m}:${s}` : secs.toFixed(2) + " s";
}

function cubeEntities(hass, anchor) {
  const reg = hass.entities || {};
  const deviceId = reg[anchor]?.device_id;
  const found = {};
  for (const e of Object.values(reg)) {
    if (e.platform !== "qiyi_cube" || (deviceId && e.device_id !== deviceId)) continue;
    const st = hass.states[e.entity_id];
    if (!st) continue;
    const key =
      e.translation_key ||
      (st.attributes.device_class === "battery" ? "battery" : null) ||
      (st.attributes.device_class === "connectivity" ? "connected" : null);
    if (key) found[key] = st;
  }
  return found;
}

function findAnchor(hass) {
  return Object.values(hass.entities || {}).find(
    (e) => e.platform === "qiyi_cube" && e.translation_key === "solved_faces",
  )?.entity_id;
}

const STYLE = `
  ha-card { display: block; padding: 16px; }
  .head { display: flex; align-items: center; gap: 8px; margin-bottom: 4px; }
  .title { font-size: 1.1em; font-weight: 500; flex: 1; min-width: 0;
           overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .chip { font-size: 0.85em; padding: 2px 8px; border-radius: 12px; white-space: nowrap;
          background: var(--secondary-background-color); color: var(--secondary-text-color); }
  .chip.solving { background: var(--primary-color); color: var(--text-primary-color, #fff); }
  .chip.ok { background: rgba(var(--rgb-success-color, 67, 160, 71), 0.15);
             color: var(--success-color, #43a047); }
  .wrap { position: relative; }
  .reset { position: absolute; right: 0; bottom: 0; width: 40px; height: 40px; padding: 8px;
           border: none; border-radius: 50%; background: none; cursor: pointer;
           color: var(--secondary-text-color); --mdc-icon-size: 24px; }
  .reset:hover { background: var(--secondary-background-color); color: var(--primary-text-color); }
  .stage { display: flex; align-items: center; justify-content: center; overflow: hidden;
           cursor: pointer; -webkit-tap-highlight-color: transparent; }
  .cube { position: relative; width: 0; height: 0; transform-style: preserve-3d;
          transition: transform 90ms linear; }
  .cube > div { position: absolute; box-sizing: border-box; backface-visibility: hidden; }
  .st { background: #161616; }
  .st i { position: absolute; inset: 5%; border-radius: 12%;
          box-shadow: inset 0 0 0 1px rgba(0, 0, 0, 0.15); }
  .cube > .core { background: #161616; backface-visibility: visible; }
  svg { display: block; width: 100%; max-width: 420px; margin: 8px auto 0; }
  svg .top { fill: none; stroke: var(--primary-color); stroke-width: 1.2; }
  .solution { margin-top: 12px; color: var(--secondary-text-color); }
  .label { display: block; font-size: 0.85em; margin-bottom: 2px; }
  code { font-family: var(--code-font-family, monospace); font-size: 1.05em;
         color: var(--primary-text-color); word-spacing: 0.2em; }
  .msg { padding: 8px 0; color: var(--secondary-text-color); }
  .actions { display: flex; gap: 8px; margin-top: 12px; }
  .btn { font: inherit; font-weight: 500; padding: 6px 16px; border: none; border-radius: 18px;
         cursor: pointer; background: var(--primary-color); color: var(--text-primary-color, #fff); }
  .btn:disabled { opacity: 0.4; cursor: default; }
  .stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
           gap: 8px 16px; margin-top: 12px; }
  .stat .value { font-size: 1.7em; font-weight: 500; line-height: 1.25; color: var(--primary-text-color); }
  .stat .sub { font-size: 0.85em; color: var(--secondary-text-color); }
  .stat { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
  .stat .btn { flex: none; }
  .stat .value.pending { color: var(--secondary-text-color); animation: pulse 1.2s ease-in-out infinite; }
  @keyframes pulse { 50% { opacity: 0.3; } }
  .btn.secondary { background: var(--secondary-background-color); color: var(--primary-text-color); }
  .guide { margin-top: 12px; }
  .guide .now { font-size: 1.15em; font-weight: 500; color: var(--primary-text-color); margin: 2px 0 4px; }
  .guide .now b { font-family: var(--code-font-family, monospace); font-size: 1.35em; margin-right: 10px; }
  .hint { font-size: 0.85em; color: var(--secondary-text-color); }
  .steps { display: flex; flex-wrap: wrap; gap: 4px; margin-top: 8px; }
  .steps span { font-family: var(--code-font-family, monospace); padding: 1px 7px; border-radius: 6px;
                background: var(--secondary-background-color); color: var(--primary-text-color); }
  .steps .done { opacity: 0.35; }
  .steps .cur { background: var(--primary-color); color: var(--text-primary-color, #fff); }
  .steps .undo { box-shadow: inset 0 0 0 1px var(--error-color, #db4437); }
  .st.hl { background: var(--primary-color); }
  .cube > .arrow { pointer-events: none; }
  .cube > .arrow svg { display: block; width: 100%; height: 100%; max-width: none; margin: 0; }
`;

// --- card -------------------------------------------------------------------

class QiYiCubeCard extends HTMLElement {
  static getStubConfig(hass) {
    const entity = findAnchor(hass);
    return entity ? { entity } : {};
  }

  static getConfigElement() {
    return document.createElement("qiyi-cube-card-editor");
  }

  _opt(name) {
    return this._config?.[name] ?? true;
  }

  constructor() {
    super();
    this._queue = []; // pending {move, facelets} from the live stream
    this._anim = null; // running turn animation
    this._unit = 40; // px per sticker, set from the card width
  }

  setConfig(config) {
    this._config = config || {};
    this._built = undefined;
    if (this._hass) this._render();
  }

  set hass(hass) {
    this._hass = hass;
    this._render();
    this._subscribe();
  }

  connectedCallback() {
    if (this._hass) this._render();
    this._subscribe();
  }

  disconnectedCallback() {
    this._unsubscribe();
    this._resizeObserver?.disconnect();
    this._resizeObserver = undefined;
    this._built = undefined;
  }

  getCardSize() {
    return 8;
  }

  getGridOptions() {
    return { columns: "full", min_columns: 6, rows: "auto" };
  }

  get _is3d() {
    return this._config?.view !== "net";
  }

  // --- live stream ------------------------------------------------------------

  // Exactly one live subscription per attached card. Lovelace may detach and
  // re-attach a card while the subscription is still being set up, so the
  // pending promise is tracked and only the current one may deliver events.
  _subscribe() {
    if (!this.isConnected || !this._anchor || !this._hass?.connection) return;
    if (this._sub && this._subAnchor === this._anchor) return;
    this._unsubscribe();
    const sub = this._hass.connection.subscribeMessage(
      (ev) => {
        if (this._sub === sub) this._onLive(ev);
      },
      { type: "qiyi_cube/subscribe_live", entity_id: this._anchor },
    );
    this._sub = sub;
    this._subAnchor = this._anchor;
    sub.catch((err) => {
      console.warn("qiyi-cube-card: no live stream", err);
    });
  }

  _unsubscribe() {
    const sub = this._sub;
    this._sub = undefined;
    sub?.then((unsub) => unsub()).catch(() => {});
  }

  _onLive(ev) {
    if (ev.move) {
      this._lastLiveMove = Date.now();
      // A turn that doesn't change the cube (resent frame) is not animated.
      const last = this._queue.at(-1)?.facelets ?? this._anim?.ev.facelets ?? this._facelets;
      if (ev.facelets === last) return;
      this._liveFacelets = ev.facelets;
      this._queue.push(ev);
      if (!this._anim) this._nextTurn();
      this._guideMove(ev);
      this._render(); // "to solve" turns into "calculating…" right away
      return;
    }
    if (!ev.q) {
      this._cToW = null; // asleep: back to rest pose, re-align on next stream
      this._heading = 0;
    } else {
      const fresh = !this._cToW;
      this._cToW = tr(quatMatrix(ev.q));
      if (fresh) this._heading = alignHeading(this._cToW);
    }
    this._applyPose();
  }

  _applyPose() {
    if (this._cubeEl) {
      this._cubeEl.style.transform = cubeTransform(this._cToW || C_REST, this._heading || 0);
    }
  }

  // --- turn animation ---------------------------------------------------------

  _nextTurn() {
    const ev = this._queue.shift();
    if (!ev) {
      this._anim = null;
      this._syncColors();
      this._updateGuideVisual();
      return;
    }
    if (!this._cubeEl) {
      this._setColors(ev.facelets);
      this._nextTurn();
      return;
    }
    const n = FACE_AXES[ev.move[0]][2];
    const angle = (ev.move.endsWith("'") ? 1 : -1) * (Math.PI / 2); // clockwise = negative
    const layer = STICKERS.flatMap((s, i) => (apply([n], s.pos)[0] > 0.5 ? [i] : []));
    // Catch up when turns arrive faster than they animate.
    const duration = TURN_MS / (1 + this._queue.length);
    const start = performance.now();
    this._showCore(n);
    this._anim = { n, angle, layer, ev };
    this._updateGuideVisual();
    const step = (now) => {
      if (this._anim?.ev !== ev) return;
      const p = Math.min(1, (now - start) / duration);
      this._turnLayer(n, layer, angle * (1 - (1 - p) ** 2)); // ease-out
      if (p < 1) {
        requestAnimationFrame(step);
      } else {
        this._turnLayer(n, layer, 0);
        this._hideCore();
        this._setColors(ev.facelets);
        this._nextTurn();
      }
    };
    requestAnimationFrame(step);
  }

  _turnLayer(n, layer, angle) {
    const rot = rotAbout(n, angle);
    for (const i of layer) this._placeSticker(i, rot);
    if (this._coreEls) {
      // Two black planes close the gap between the turning layer and the rest.
      this._place(this._coreEls[0], n, rot, 0.51, 3);
      this._place(this._coreEls[1], n, IDENTITY, 0.49, 3);
    }
  }

  _showCore(n) {
    this._coreEls = [0, 1].map(() => {
      const el = document.createElement("div");
      el.className = "core";
      this._cubeEl.appendChild(el);
      return el;
    });
    this._turnLayer(n, [], 0);
  }

  _hideCore() {
    this._coreEls?.forEach((el) => el.remove());
    this._coreEls = null;
  }

  // Square of `size` stickers in the plane at `offset` along axis n.
  _place(el, n, rot, offset, size) {
    const face = Object.values(FACE_AXES).find((a) => a[2].every((v, k) => v === n[k]));
    const [c, r] = face;
    const px = size * this._unit;
    el.style.width = el.style.height = `${px}px`;
    el.style.left = el.style.top = `${-px / 2}px`;
    el.style.transform = placeTransform(c, r, n, n.map((v) => v * offset), rot, this._unit);
  }

  _placeSticker(i, rot = IDENTITY) {
    const s = STICKERS[i];
    const el = this._stickerEls[i];
    el.style.transform = placeTransform(s.c, s.r, s.n, s.pos, rot, this._unit);
  }

  // Colours follow the live stream while it delivers turns (animated); the
  // entity state may arrive before or after a turn's stream message, so it is
  // only applied once the stream has been quiet for a moment.
  _syncColors() {
    clearTimeout(this._syncTimer);
    const target = this._stateFacelets;
    if (!target || target === this._facelets) return;
    const quietFor = Date.now() - (this._lastLiveMove || 0);
    if (this._anim || this._queue.length || quietFor < 1000) {
      this._syncTimer = setTimeout(() => this._syncColors(), Math.max(100, 1000 - quietFor));
      return;
    }
    this._setColors(target);
  }

  _setColors(facelets) {
    if (!facelets || facelets.length !== 54 || !this._stickerEls) return;
    this._facelets = facelets;
    this._stickerEls.forEach((el, i) => {
      el.firstChild.style.background = COLORS[facelets[i]] || "var(--disabled-color, #888)";
    });
  }

  _layout() {
    const width = this._stageEl?.clientWidth;
    // Setting the stage height re-triggers the ResizeObserver; only width matters.
    if (!width || width === this._layoutWidth) return;
    this._layoutWidth = width;
    // The projected cube is about 4.6 stickers wide.
    this._unit = Math.max(30, Math.min(100, (width * 0.78) / 4.6));
    this._stageEl.style.height = `${Math.round(this._unit * 5.2)}px`;
    this._stageEl.style.perspective = `${Math.round(this._unit * 24)}px`;
    for (const el of this._stickerEls) {
      el.style.width = el.style.height = `${this._unit}px`;
      el.style.left = el.style.top = `${-this._unit / 2}px`;
    }
    this._stickerEls.forEach((_, i) => this._placeSticker(i));
    this._updateGuideVisual(true);
  }

  // --- rendering --------------------------------------------------------------

  _build() {
    if (!this.shadowRoot) this.attachShadow({ mode: "open" });
    this.shadowRoot.innerHTML = `<style>${STYLE}</style>
      <ha-card><div class="head"></div><div class="picture"></div><div class="info"></div></ha-card>`;
    this._headEl = this.shadowRoot.querySelector(".head");
    this._pictureEl = this.shadowRoot.querySelector(".picture");
    this._infoEl = this.shadowRoot.querySelector(".info");
    this._stickerEls = null;
    this._cubeEl = null;
    this._keys = {};
    this._arrowEls = [];
    this._arrowKey = undefined;
    this._layoutWidth = undefined;
    this._built = true;
    this._infoEl.addEventListener("click", (e) => {
      const action = e.target.closest?.("[data-action]")?.dataset.action;
      if (action === "solve") this._startGuide();
      if (action === "stop") this._stopGuide();
    });
    if (!this._is3d) return;

    this._pictureEl.innerHTML = `<div class="wrap"><div class="stage"><div class="cube"></div></div>
      <button class="reset" type="button"><ha-icon icon="mdi:rotate-3d-variant"></ha-icon></button></div>`;
    this._stageEl = this._pictureEl.querySelector(".stage");
    this._cubeEl = this._stageEl.firstChild;
    this._resetEl = this._pictureEl.querySelector(".reset");
    this._stickerEls = STICKERS.map(() => {
      const el = document.createElement("div");
      el.className = "st";
      el.appendChild(document.createElement("i"));
      this._cubeEl.appendChild(el);
      return el;
    });
    const realign = () => {
      if (!this._cToW) return;
      this._heading = alignHeading(this._cToW);
      this._applyPose();
    };
    this._stageEl.addEventListener("click", realign);
    this._resetEl.addEventListener("click", realign);
    if (typeof ResizeObserver !== "undefined") {
      this._resizeObserver?.disconnect();
      // Lay out in the next frame: changing sizes inside the callback loops.
      this._resizeObserver = new ResizeObserver(() => requestAnimationFrame(() => this._layout()));
      this._resizeObserver.observe(this._stageEl);
    }
    this._layout();
    this._applyPose();
    if (this._facelets) this._setColors(this._facelets);
  }

  // Sets innerHTML of `el` only when `html` changed (keeps the DOM stable).
  _update(name, el, html) {
    if (this._keys[name] === html) return;
    this._keys[name] = html;
    el.innerHTML = html;
  }

  _render() {
    const hass = this._hass;
    if (!hass || !this._config) return;
    const t = TEXT[(hass.locale?.language || hass.language || "en").slice(0, 2)] || TEXT.en;
    const configured = this._config.entity;
    const anchor = configured && hass.states[configured] ? configured : findAnchor(hass);
    this._anchor = anchor;
    const ents = anchor ? cubeEntities(hass, anchor) : {};
    const faces = ents.solved_faces || (anchor && hass.states[anchor]);

    if (!this._built) this._build();
    if (!faces) {
      this._update("head", this._headEl, "");
      this._update("info", this._infoEl, `<div class="msg">${t.noEntity}</div>`);
      return;
    }

    const deviceId = hass.entities?.[faces.entity_id]?.device_id;
    const device = deviceId && hass.devices?.[deviceId];
    const title = this._config.title ?? (device?.name_by_user || device?.name || "QiYi Cube");
    const facelets = faces.attributes.facelets || "";
    const solvedCount = Number(faces.state);
    const isSolved = solvedCount === 6;
    const connected = ents.connected?.state === "on";
    const solving = ents.solving?.state === "on";
    const battery = ents.battery?.state;

    this._solutionText = ents.moves_to_solve?.attributes.solution;
    this._stateFacelets = facelets;
    if (this._guide?.stale) this._adoptSolution();

    this._headEl.style.display = this._opt("show_header") ? "" : "none";
    this._update("head", this._headEl, `
      <div class="title">${title}</div>
      <span class="chip ${isSolved ? "ok" : ""}">
        ${isSolved ? `✓ ${t.solved}` : `${Number.isFinite(solvedCount) ? solvedCount : "–"}/6 ${t.faces}`}
      </span>
      ${solving ? `<span class="chip solving">${t.solving}</span>` : ""}
      ${battery && battery !== "unknown" ? `<span class="chip">${battery} %</span>` : ""}
      <span class="chip ${connected ? "ok" : ""}">${connected ? t.connected : t.asleep}</span>`);

    if (this._is3d) {
      this._resetEl.title = t.align;
      this._syncColors();
      this._updateGuideVisual();
    } else {
      this._update("picture", this._pictureEl, this._netSvg(facelets, ents, title));
    }

    if (this._guide) {
      this._update("info", this._infoEl, this._guideHtml(t));
      return;
    }
    // Two tiles side by side (they stack on narrow cards). The move sequence
    // itself only shows in the solve guide; the button is always there
    // (disabled when solved) so the card doesn't change height.
    const solution = ents.moves_to_solve;
    const moves = solution?.attributes.solution;
    const showSolution = solution && this._opt("show_solution");
    const showButton = solution && this._opt("show_solve_button");
    // While you turn (and until Home Assistant has the new solution) the last
    // one no longer fits: check it against the current state by simulation.
    const current = this._currentFacelets();
    const solvedNow = isSolvedState(current);
    const fresh = solvedNow || (!!moves && isSolvedState(applySteps(current, parseMoves(moves))));
    const disabled = solvedNow || !fresh ? " disabled" : "";
    const button = showButton
      ? `<button class="btn" type="button" data-action="solve"${disabled}>${t.solve}</button>`
      : "";
    const tiles = [];
    if (showSolution) {
      const value = solvedNow ? "✓" : fresh ? solution.state : "…";
      const sub = solvedNow ? t.solved : fresh ? t.moves : t.calculating;
      tiles.push(`<div class="stat"><div><span class="label">${t.toSolve}</span>
        <div class="value${fresh ? "" : " pending"}">${value}</div><div class="sub">${sub}</div></div>${button}</div>`);
    }
    if (ents.last_solve_duration && this._opt("show_last_solve")) {
      const secs = Number(ents.last_solve_duration.state);
      const known = Number.isFinite(secs) && ents.last_solve_duration.state !== "";
      const tps = ents.last_solve_duration.attributes.tps;
      const sub = known
        ? `${ents.last_solve_moves?.state ?? "–"} ${t.moves}${tps != null ? ` · ${tps} ${t.tps}` : ""}`
        : "&nbsp;";
      tiles.push(`<div class="stat"><div><span class="label">${t.lastSolve}</span>
        <div class="value">${known ? formatTime(secs) : "–"}</div><div class="sub">${sub}</div></div></div>`);
    }
    let info = tiles.length ? `<div class="stats">${tiles.join("")}</div>` : "";
    if (button && !showSolution) info += `<div class="actions">${button}</div>`;
    this._update("info", this._infoEl, info);
  }

  // --- solve guide ------------------------------------------------------------
  // Steps come from the solution sensor and are checked against the card's
  // own cube simulation. Every turn of the real cube advances the guide; a
  // wrong turn adds a step that undoes it, so the steps always solve the cube.
  // If they ever stop doing so (missed turn), the guide waits for the next
  // solution from Home Assistant.

  _currentFacelets() {
    const quiet = Date.now() - (this._lastLiveMove || 0) > 1000;
    return (quiet && this._stateFacelets) || this._liveFacelets || this._stateFacelets;
  }

  _startGuide() {
    this._guide = { steps: [], done: [], stale: true, finished: false };
    this._adoptSolution();
    this._render();
  }

  _stopGuide() {
    clearTimeout(this._guideTimer);
    this._guide = null;
    this._updateGuideVisual();
    this._render();
  }

  _adoptSolution() {
    const g = this._guide;
    const facelets = this._currentFacelets();
    if (isSolvedState(facelets)) {
      this._finishGuide(g);
      return;
    }
    const steps = parseMoves(this._solutionText).map((st) => ({ ...st, name: moveName(st) }));
    if (steps.length && isSolvedState(applySteps(facelets, steps))) {
      Object.assign(g, { steps, stale: false });
      this._updateGuideVisual();
    }
  }

  // Show "Solved!" for a few seconds, then go back to the normal view.
  _finishGuide(g) {
    Object.assign(g, { steps: [], stale: false, finished: true });
    clearTimeout(this._guideTimer);
    this._guideTimer = setTimeout(() => {
      if (this._guide === g) this._stopGuide();
    }, 4000);
  }

  _guideMove(ev) {
    const g = this._guide;
    if (!g || g.finished) return;
    if (isSolvedState(ev.facelets)) {
      this._finishGuide(g);
    } else if (!g.stale) {
      const face = ev.move[0];
      const quarters = ev.move.endsWith("'") ? 3 : 1;
      const first = g.steps[0];
      if (first?.face === face) {
        first.quarters = (first.quarters - quarters + 4) % 4;
        if (!first.quarters) {
          g.steps.shift();
          if (!first.undo) g.done.push(first.name);
        }
      } else {
        g.steps.unshift({ face, quarters: 4 - quarters, undo: true });
      }
      if (!isSolvedState(applySteps(ev.facelets, g.steps))) g.stale = true;
    }
    this._render();
  }

  _guideHtml(t) {
    const g = this._guide;
    if (g.finished) {
      return `<div class="guide"><div class="now">${t.guideDone}</div><div class="actions">
        <button class="btn" type="button" data-action="stop">${t.close}</button></div></div>`;
    }
    const stop = `<div class="actions"><button class="btn secondary" type="button" data-action="stop">${t.stop}</button></div>`;
    if (g.stale) {
      return `<div class="guide"><div class="now">${g.done.length ? t.recalc : t.wait}</div>${stop}</div>`;
    }
    const cur = g.steps[0];
    const total = g.done.length + g.steps.filter((st) => !st.undo).length;
    const chips = [
      ...g.done.map((m) => `<span class="done">${m}</span>`),
      ...g.steps.map((st, k) => `<span class="${k ? "" : "cur"} ${st.undo ? "undo" : ""}">${moveName(st)}</span>`),
    ].join("");
    return `<div class="guide">
      <span class="label">${t.step(Math.min(g.done.length + 1, total), total)}${cur.undo ? ` · ${t.undoHint}` : ""}</span>
      <div class="now"><b>${moveName(cur)}</b>${t.turnText(cur.face, cur.quarters)}</div>
      <div class="hint">${t.hint}</div><div class="steps">${chips}</div>${stop}</div>`;
  }

  // Highlight the face to turn and put an arrow on it (3D view).
  // The whole turning layer is highlighted; a curved arrow sits on the face
  // and straight arrows run along the layer on the four neighbouring faces, so
  // the direction is visible from any side (also for back faces).
  _updateGuideVisual(force = false) {
    if (!this._stickerEls) return;
    const g = this._guide;
    const step = g && !g.stale && !g.finished && !this._anim && !this._queue.length ? g.steps[0] : null;
    const key = step ? moveName(step) + this._unit : "";
    if (key === this._arrowKey && !force) return;
    this._arrowKey = key;
    this._arrowEls?.forEach((el) => el.remove());
    this._arrowEls = [];
    const n = step && FACE_AXES[step.face][2];
    this._stickerEls.forEach((el, i) => el.classList.toggle("hl", !!step && dot(STICKERS[i].pos, n) > 0.5));
    if (!step) return;

    const [c, r] = FACE_AXES[step.face];
    this._addArrow(arrowSvg(step.quarters), c, r, n, n.map((v) => v * 1.56), 3, 3);
    for (const [, , m] of Object.values(FACE_AXES)) {
      if (dot(m, n) !== 0) continue;
      // Stickers on face m move along -(n × m) for a clockwise turn.
      const d = cross(n, m).map((v) => (step.quarters === 3 ? v : -v));
      // Local y is chosen so that (d, y, m) is oriented like the sticker frames.
      const y = dot(d, cross(n, m)) < 0 ? n : n.map((v) => -v);
      const pos = [0, 1, 2].map((k) => 1.56 * m[k] + n[k]);
      this._addArrow(straightArrowSvg(step.quarters), d, y, m, pos, 3, 1);
    }
  }

  _addArrow(svg, x, y, z, pos, w, h) {
    const el = document.createElement("div");
    el.className = "arrow";
    el.innerHTML = svg;
    el.style.width = `${w * this._unit}px`;
    el.style.height = `${h * this._unit}px`;
    el.style.left = `${(-w * this._unit) / 2}px`;
    el.style.top = `${(-h * this._unit) / 2}px`;
    el.style.transform = placeTransform(x, y, z, pos, IDENTITY, this._unit);
    this._cubeEl.appendChild(el);
    this._arrowEls.push(el);
  }

  _netSvg(facelets, ents, title) {
    const top = COLOR_FACE[ents.top_face?.state];
    const color = (i) => COLORS[facelets[i]] || "var(--disabled-color, #888)";
    const rects = [];
    for (const [fi, face] of [...FACES].entries()) {
      const [fx, fy] = NET[face];
      for (let i = 0; i < 9; i++) {
        const x = fx * 3 + (i % 3);
        const y = fy * 3 + Math.floor(i / 3);
        rects.push(
          `<rect x="${x * 10 + 0.6}" y="${y * 10 + 0.6}" width="8.8" height="8.8" rx="1.6" fill="${color(fi * 9 + i)}"/>`,
        );
      }
      if (face === top) {
        rects.push(
          `<rect class="top" x="${fx * 30 - 0.6}" y="${fy * 30 - 0.6}" width="31.2" height="31.2" rx="2.5"/>`,
        );
      }
    }
    return `<svg viewBox="0 0 120 90" role="img" aria-label="${title}">${rects.join("")}</svg>`;
  }
}

// --- visual editor ------------------------------------------------------------

const EDITOR_TEXT = {
  en: {
    entity: "Cube", title: "Title", view: "View", view3d: "3D (live)", viewNet: "Net (flat)",
    show_header: "Status", show_solution: "Solution", show_solve_button: "Solve button",
    show_last_solve: "Last solve",
  },
  de: {
    entity: "Würfel", title: "Titel", view: "Ansicht", view3d: "3D (live)", viewNet: "Netz (flach)",
    show_header: "Status", show_solution: "Lösung", show_solve_button: "Lösen-Knopf",
    show_last_solve: "Letzte Lösung",
  },
};
const TOGGLES = ["show_header", "show_solution", "show_solve_button", "show_last_solve"];

class QiYiCubeCardEditor extends HTMLElement {
  setConfig(config) {
    this._config = { ...config };
    this._render();
  }

  set hass(hass) {
    this._hass = hass;
    this._render();
  }

  _render() {
    if (!this._hass || !this._config) return;
    const lang = (this._hass.locale?.language || this._hass.language || "en").slice(0, 2);
    const L = EDITOR_TEXT[lang] || EDITOR_TEXT.en;
    if (!this._form) {
      this._form = document.createElement("ha-form");
      this._form.addEventListener("value-changed", (ev) => {
        const config = { ...ev.detail.value };
        for (const [k, v] of Object.entries(config)) if (v === "" || v == null) delete config[k];
        this._config = config;
        this.dispatchEvent(new CustomEvent("config-changed", { detail: { config }, bubbles: true, composed: true }));
      });
      this.appendChild(this._form);
    }
    this._form.hass = this._hass;
    this._form.data = { view: "3d", ...Object.fromEntries(TOGGLES.map((k) => [k, true])), ...this._config };
    this._form.schema = [
      { name: "entity", selector: { entity: { filter: { integration: "qiyi_cube" } } } },
      { name: "title", selector: { text: {} } },
      {
        name: "view",
        selector: {
          select: { mode: "dropdown", options: [{ value: "3d", label: L.view3d }, { value: "net", label: L.viewNet }] },
        },
      },
      { type: "grid", name: "", schema: TOGGLES.map((name) => ({ name, selector: { boolean: {} } })) },
    ];
    this._form.computeLabel = (schema) => L[schema.name] ?? schema.name;
  }
}

if (!customElements.get("qiyi-cube-card-editor")) {
  customElements.define("qiyi-cube-card-editor", QiYiCubeCardEditor);
}

if (!customElements.get("qiyi-cube-card")) {
  customElements.define("qiyi-cube-card", QiYiCubeCard);
  window.customCards = window.customCards || [];
  window.customCards.push({
    type: "qiyi-cube-card",
    name: "QiYi Cube",
    description: "Live 3D smart cube with animated turns, a solution and the last solve.",
    preview: true,
  });
}
