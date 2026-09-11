// A Lovelace card that draws a hob the way the Home Connect app does: the dark
// glass surface, with each cooking zone painted on it showing its power level,
// whether it is heating, its temperature and any countdown.
//
// The zones are laid out where the hob itself says they sit. A hob writes the
// position, size and shape of every zone into its description, and the
// integration hands those to the card over the websocket, so a four-ring hob
// with a flex strip down one side is drawn as that and not as a tidy grid.
// Reached over the cloud there is no such geometry, and the zones fall back to
// a grid, which is the most an appliance that will not say can be drawn.
//
// Bundled with the homeconnect integration, which serves this file and adds it
// as a dashboard resource, so there is no resource to add by hand.

const CARD = "homeconnect-hob-card";

const SUFFIXES = [
  "power_level",
  "current_temperature",
  "state",
  "operation_state",
  "remaining_program_time",
  "remaining_programme_time",
  "program_name",
  "programme_name",
];

// One matcher for every zone reading, whichever way the name was spelled.
const ZONE = new RegExp(`_zone_(\\d+)_(${SUFFIXES.join("|")})$`);

// What the last part of a value reads as: PowerLevel.Boost -> Boost, .9 -> 9.
const leaf = (value) =>
  typeof value === "string" && value.includes(".")
    ? value.split(".").pop()
    : value;

const OFF = new Set(["off", "inactive", "0", "", undefined, null, "unavailable"]);

// Every device that has zone readings on it, which is every hob.
function hobDevices(hass) {
  const entities = (hass && hass.entities) || {};
  const devices = new Set();
  for (const entity_id of Object.keys(entities)) {
    if (ZONE.test(entity_id) && entities[entity_id].device_id) {
      devices.add(entities[entity_id].device_id);
    }
  }
  return [...devices];
}

class HomeConnectHobCard extends HTMLElement {
  setConfig(config) {
    // The device is not required: with one hob on the system it is found on
    // its own, and only more than one has to be told apart.
    this._config = config || {};
    this._signature = null;
    this._layout = null;
    this._layoutFor = null;
    if (!this.shadowRoot) this.attachShadow({ mode: "open" });
  }

  set hass(hass) {
    this._hass = hass;
    this._askLayout();
    this._render();
  }

  getCardSize() {
    return 5;
  }

  static getConfigElement() {
    return document.createElement(`${CARD}-editor`);
  }

  static getStubConfig(hass) {
    const devices = hobDevices(hass);
    return devices.length === 1 ? { device: devices[0] } : { device: "" };
  }

  // The chosen hob, or the only one there is when none was chosen.
  _device() {
    if (this._config.device) return this._config.device;
    const devices = hobDevices(this._hass);
    return devices.length === 1 ? devices[0] : undefined;
  }

  // Ask the integration where this hob's zones sit, once per hob. The answer
  // is empty over the cloud, which is the sign to fall back to a grid.
  _askLayout() {
    const device = this._device();
    if (!device || this._layoutFor === device) return;
    if (!this._hass || !this._hass.callWS) return;
    this._layoutFor = device;
    this._layout = null;
    this._hass
      .callWS({ type: "homeconnect/hob_layout", device_id: device })
      .then((answer) => {
        this._layout = (answer && answer.zones) || [];
        this._signature = null;
        this._render();
      })
      .catch(() => {
        this._layout = [];
      });
  }

  // The zone readings on that hob, gathered by the number of their zone.
  _zones(device) {
    const entities = (this._hass && this._hass.entities) || {};
    const found = {};
    if (!device) return found;
    for (const entity_id of Object.keys(entities)) {
      if (entities[entity_id].device_id !== device) continue;
      const match = entity_id.match(ZONE);
      if (!match) continue;
      const field = match[2].replace("programme", "program");
      (found[match[1]] ||= {})[field] = entity_id;
    }
    return found;
  }

  // Whether the hob is offering this zone at all. One it calls NotSelectable is
  // a joinable zone standing idle, there to be shown only once it is in use.
  _selectable(fields) {
    const state = String(leaf(this._value(fields.state)) || "").toLowerCase();
    return state !== "notselectable";
  }

  _value(entity_id) {
    if (!entity_id) return undefined;
    const state = this._hass.states[entity_id];
    return state ? state.state : undefined;
  }

  // Where to draw each zone. The hob's own geometry when it gave any and it
  // covers every zone on show, else a grid worked out from how many there are.
  _placed(numbers) {
    const geometry = {};
    for (const zone of this._layout || []) geometry[zone.zone] = zone;
    if (numbers.length && numbers.every((n) => geometry[n])) {
      return numbers.map((n) => ({ n, ...geometry[n] }));
    }
    const columns = Math.max(1, Math.ceil(Math.sqrt(numbers.length || 1)));
    return numbers.map((n, i) => ({
      n,
      x: (i % columns) * 110 + 50,
      y: Math.floor(i / columns) * 110 + 50,
      w: 100,
      h: 100,
      round: true,
    }));
  }

  _render() {
    if (!this._hass) return;
    const device = this._device();
    const zones = this._zones(device);
    // A hob that can join two zones into one describes the joined zone as well
    // as the two, and marks whichever are idle NotSelectable, so a zone the hob
    // will not let you pick is left off. That drops the phantom flex tile until
    // the two are joined, and swaps to the one big tile once they are.
    const numbers = Object.keys(zones)
      .filter((n) => this._selectable(zones[n]))
      .sort((a, b) => Number(a) - Number(b));
    const placed = this._placed(numbers);
    const shape = placed
      .map((p) => `${p.n}:${p.x},${p.y},${p.w},${p.h},${p.round ? 1 : 0}`)
      .join(";");
    const signature = `${device || ""}|${shape}`;

    // Rebuild the frame only when the hob or where its live zones sit changes,
    // so a value moving does not throw the whole card away and build it again.
    if (signature !== this._signature) {
      this._signature = signature;
      this._build(placed, device);
    }
    for (const p of placed) this._paint(p.n, zones[p.n]);
  }

  _build(placed, device) {
    const title = this._config.name || "Hob";

    if (!placed.length) {
      const note = !device
        ? hobDevices(this._hass).length
          ? "More than one hob here. Set 'device' to the one you mean."
          : "No hob found on this system."
        : "No zones found for this device.";
      this.shadowRoot.innerHTML = `${this._style(1, 1)}
        <ha-card>
          <div class="title">${title}</div>
          <div class="glass empty"><div>${note}</div></div>
        </ha-card>`;
      return;
    }

    // The smallest box that holds every zone, with a little air around it so a
    // zone at the edge is not flush against the rim of the glass.
    let minX = Infinity;
    let minY = Infinity;
    let maxX = -Infinity;
    let maxY = -Infinity;
    for (const p of placed) {
      minX = Math.min(minX, p.x - p.w / 2);
      minY = Math.min(minY, p.y - p.h / 2);
      maxX = Math.max(maxX, p.x + p.w / 2);
      maxY = Math.max(maxY, p.y + p.h / 2);
    }
    const pad = Math.max(maxX - minX, maxY - minY) * 0.07;
    minX -= pad;
    minY -= pad;
    maxX += pad;
    maxY += pad;
    const wide = maxX - minX;
    const tall = maxY - minY;

    const tiles = placed
      .map((p) => {
        const left = ((p.x - p.w / 2 - minX) / wide) * 100;
        const top = ((p.y - p.h / 2 - minY) / tall) * 100;
        const w = (p.w / wide) * 100;
        const h = (p.h / tall) * 100;
        const radius = p.round ? "50%" : "16%";
        return `<div class="zone" id="zone-${p.n}"
          style="left:${left.toFixed(2)}%;top:${top.toFixed(2)}%;width:${w.toFixed(2)}%;height:${h.toFixed(2)}%;border-radius:${radius}">
          <span class="level"></span>
          <span class="under"><span class="temp"></span><span class="left"></span></span>
        </div>`;
      })
      .join("");

    this.shadowRoot.innerHTML = `${this._style(wide, tall)}
      <ha-card>
        <div class="title">${title}</div>
        <div class="glass">${tiles}</div>
      </ha-card>`;
  }

  _style(wide, tall) {
    return `
      <style>
        ha-card { padding: 16px; }
        .title { font-size: 1.1em; font-weight: 500; margin: 0 0 12px 4px;
                 color: var(--primary-text-color); }
        .glass {
          position: relative; border-radius: 18px; aspect-ratio: ${wide} / ${tall};
          background:
            radial-gradient(120% 90% at 30% 15%, #3a4351 0%, #2b323d 45%, #1c2027 100%);
          box-shadow: inset 0 1px 2px rgba(255,255,255,.06),
                      inset 0 -8px 24px rgba(0,0,0,.5);
        }
        .glass.empty { display: flex; align-items: center; justify-content: center;
                       aspect-ratio: 2 / 1; text-align: center; }
        .glass.empty div { color: rgba(230,235,245,.72); max-width: 22ch; padding: 12px; }
        .zone {
          position: absolute; box-sizing: border-box; overflow: hidden;
          display: flex; flex-direction: column; align-items: center;
          justify-content: center; gap: 4px;
          border: 2px solid rgba(255,255,255,.14);
          background: radial-gradient(circle at 50% 50%,
                      rgba(255,255,255,.05), rgba(0,0,0,.25));
          transition: box-shadow .3s ease, border-color .3s ease;
        }
        .zone.on {
          border-color: rgba(255,150,60,.85);
          box-shadow: 0 0 18px rgba(255,120,30,.55),
                      inset 0 0 22px rgba(255,90,20,.45);
        }
        .zone.boost {
          border-color: rgba(255,80,60,.95);
          box-shadow: 0 0 26px rgba(255,50,30,.8),
                      inset 0 0 26px rgba(255,40,20,.6);
        }
        .level { font-size: 1.5em; font-weight: 600; color: #f5f7fa;
                 text-shadow: 0 1px 3px rgba(0,0,0,.6); line-height: 1; }
        .zone:not(.on):not(.boost) .level { color: rgba(230,235,245,.45); }
        .under { display: flex; gap: 8px; font-size: .72em; min-height: 1em;
                 color: rgba(230,235,245,.75); }
        .under:empty { display: none; }
      </style>`;
  }

  _paint(number, fields) {
    const tile = this.shadowRoot.getElementById(`zone-${number}`);
    if (!tile) return;

    const power = leaf(this._value(fields.power_level));
    const zoneState = String(leaf(this._value(fields.state)) || "").toLowerCase();
    const op = String(leaf(this._value(fields.operation_state)) || "").toLowerCase();
    const powerText = String(power ?? "").toLowerCase();

    const off = OFF.has(powerText) && OFF.has(zoneState) && OFF.has(op);
    const boost = powerText === "boost";

    tile.classList.toggle("on", !off && !boost);
    tile.classList.toggle("boost", boost);

    const label = tile.querySelector(".level");
    if (off) label.textContent = "";
    else if (boost) label.textContent = "P";
    else if (power === undefined) label.textContent = "·";
    else label.textContent = String(power);

    const temp = this._value(fields.current_temperature);
    tile.querySelector(".temp").textContent =
      !off && temp && Number(temp) > 0 ? `${Math.round(Number(temp))}°` : "";

    const left = this._value(fields.remaining_program_time);
    tile.querySelector(".left").textContent =
      !off && left && Number(left) > 0 ? clock(Number(left)) : "";
  }
}

// Seconds as an appliance counts them, shown the way a timer reads.
function clock(seconds) {
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds % 60);
  if (m >= 60) {
    const h = Math.floor(m / 60);
    return `${h}:${String(m % 60).padStart(2, "0")}`;
  }
  return `${m}:${String(s).padStart(2, "0")}`;
}

// The little form shown when the card is edited: pick the hob, name it.
class HomeConnectHobCardEditor extends HTMLElement {
  setConfig(config) {
    this._config = config || {};
    this._render();
  }

  set hass(hass) {
    this._hass = hass;
    this._render();
  }

  _render() {
    if (!this._hass) return;
    if (!this._form) {
      this._form = document.createElement("ha-form");
      this._form.computeLabel = (schema) =>
        ({ device: "Hob", name: "Name (optional)" })[schema.name] || schema.name;
      this._form.addEventListener("value-changed", (event) => {
        event.stopPropagation();
        this.dispatchEvent(
          new CustomEvent("config-changed", {
            detail: { config: { type: `custom:${CARD}`, ...event.detail.value } },
          })
        );
      });
      this.appendChild(this._form);
    }
    this._form.hass = this._hass;
    this._form.data = this._config;
    this._form.schema = [
      {
        name: "device",
        required: true,
        selector: { device: { integration: "homeconnect" } },
      },
      { name: "name", selector: { text: {} } },
    ];
  }
}

if (!customElements.get(CARD)) {
  customElements.define(CARD, HomeConnectHobCard);
  customElements.define(`${CARD}-editor`, HomeConnectHobCardEditor);
}

window.customCards = window.customCards || [];
if (!window.customCards.some((c) => c.type === CARD)) {
  window.customCards.push({
    type: CARD,
    name: "Home Connect Hob",
    description: "A cooktop with its zones, their power, heat and timers.",
    preview: true,
  });
}
