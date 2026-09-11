// A Lovelace card that lays any programme machine out the way the Home Connect
// app does, and drives it the same way: the programme on a card of its own,
// what the run will cost on coloured bars beside the time it will take, the
// options the appliance offers, and a start and a stop, with the door warning
// across the top while the door is open.
//
// The app builds a washer, a dryer, an oven, a coffee maker and the rest from
// one set of parts: a programme, a forecast, and the appliance's own options,
// each drawn by what it is, a flag as a chip, a choice as a picker, a number
// as a slider. This does the same, reading whatever the appliance exposes
// rather than a list held per machine, so it fits every programme machine
// without being told which it is. The hob and the dishwasher have cards of
// their own, drawn to their own shapes, so they are left to those.
//
// Bundled with the homeconnect integration, which serves this file and adds it
// as a dashboard resource, so there is no resource to add by hand.

const CARD = "homeconnect-appliance-card";

// How many bits a forecast bar is drawn in, the way the app draws it.
const SEGMENTS = 5;

const OFF = new Set(["off", "inactive", "", undefined, null, "unavailable", "unknown"]);

// The one-off readings and controls, each pinned to the kind of entity it is
// and the tail of its name. Programme time is spelled both ways.
const NAMED = {
  programme: /^select\..*_programme$/,
  power: /^select\..*_power_state$/,
  childlock: /^switch\..*_child_lock$/,
  energy: /^sensor\..*_energy_forecast$/,
  water: /^sensor\..*_water_forecast$/,
  remaining: /^sensor\..*_remaining_program(?:me)?_time$/,
  door: /^binary_sensor\..*_door_state$/,
  start: /^button\..*_start_program(?:me)?$/,
  stop: /^button\..*_stop_program(?:me)?$/,
};

// An icon for an option, chosen by what its name is about, the way the app
// gives each option a glyph. A tune knob stands in for anything unnamed.
const ICONS = [
  [/speed|vario|perfect|fast/, "mdi:fast-forward"],
  [/temperature|temp\b|thermal/, "mdi:thermometer"],
  [/spin/, "mdi:sync"],
  [/dry|drying/, "mdi:tumble-dryer"],
  [/prewash|pre-wash|soak/, "mdi:water-outline"],
  [/rinse|water/, "mdi:water"],
  [/silent|silence|quiet/, "mdi:volume-off"],
  [/hygien|steam|disinfect|sanit/, "mdi:shield-plus-outline"],
  [/half|load/, "mdi:circle-half-full"],
  [/intensiv|intensive|zone/, "mdi:target"],
  [/eco|energy/, "mdi:leaf"],
  [/iron|wrinkle|crease/, "mdi:iron"],
  [/dos|detergent|dosing/, "mdi:cup-water"],
  [/light|brightness/, "mdi:lightbulb-outline"],
  [/fan|air|ventil/, "mdi:fan"],
  [/child|lock/, "mdi:lock"],
];

function iconFor(label) {
  const text = String(label).toLowerCase();
  for (const [pattern, icon] of ICONS) if (pattern.test(text)) return icon;
  return "mdi:tune-variant";
}

const leaf = (value) =>
  typeof value === "string" && value.includes(".")
    ? value.split(".").pop()
    : value;

const escape = (text) =>
  String(text).replace(
    /[&<>"']/g,
    (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[ch]
  );

// A programme machine is one with a programme to pick. The hob is drawn by its
// zones and the dishwasher by its own card, so a machine that looks like either
// is left to them and not taken up here.
function isAppliance(entities, device) {
  let programme = false;
  let special = false;
  for (const id of Object.keys(entities)) {
    const entity = entities[id];
    if (entity.device_id !== device || entity.platform !== "homeconnect") continue;
    if (NAMED.programme.test(id)) programme = true;
    if (/_zone_\d+_/.test(id) || /_(half_load|intensiv_zone)$/.test(id)) special = true;
  }
  return programme && !special;
}

function applianceDevices(hass) {
  const entities = (hass && hass.entities) || {};
  const devices = new Set();
  for (const id of Object.keys(entities)) {
    const entity = entities[id];
    if (entity.platform !== "homeconnect" || !entity.device_id) continue;
    if (!devices.has(entity.device_id) && NAMED.programme.test(id)) {
      devices.add(entity.device_id);
    }
  }
  return [...devices].filter((d) => isAppliance(entities, d));
}

class HomeConnectApplianceCard extends HTMLElement {
  setConfig(config) {
    this._config = config || {};
    this._signature = null;
    if (!this.shadowRoot) this.attachShadow({ mode: "open" });
  }

  set hass(hass) {
    this._hass = hass;
    this._render();
  }

  getCardSize() {
    return 9;
  }

  static getConfigElement() {
    return document.createElement(`${CARD}-editor`);
  }

  static getStubConfig(hass) {
    const devices = applianceDevices(hass);
    return devices.length === 1 ? { device: devices[0] } : { device: "" };
  }

  _device() {
    if (this._config.device) return this._config.device;
    const devices = applianceDevices(this._hass);
    return devices.length === 1 ? devices[0] : undefined;
  }

  // The controls of the chosen machine, sorted into what each is for: the
  // named few, and then the options by their kind. A setting the appliance
  // keeps as housekeeping carries a category, so those are stepped over and
  // only what a programme is adjusted by is shown.
  _controls(device) {
    const found = { switches: [], selects: [], numbers: [] };
    const entities = (this._hass && this._hass.entities) || {};
    if (!device) return found;
    for (const id of Object.keys(entities)) {
      const entity = entities[id];
      if (entity.device_id !== device || entity.platform !== "homeconnect") continue;
      let claimed = false;
      for (const [name, pattern] of Object.entries(NAMED)) {
        if (pattern.test(id)) {
          found[name] = id;
          claimed = true;
        }
      }
      if (claimed || entity.entity_category) continue;
      if (id.startsWith("switch.")) found.switches.push(id);
      else if (id.startsWith("select.")) found.selects.push(id);
      else if (id.startsWith("number.")) found.numbers.push(id);
    }
    for (const key of ["switches", "selects", "numbers"]) found[key].sort();
    return found;
  }

  _value(id) {
    if (!id || !this._hass) return undefined;
    const state = this._hass.states[id];
    return state ? state.state : undefined;
  }

  _attr(id, name) {
    const state = id && this._hass.states[id];
    return state ? state.attributes[name] : undefined;
  }

  _call(id, domain, service, extra) {
    if (!id || !this._hass) return;
    this._hass.callService(domain, service, { entity_id: id, ...(extra || {}) });
  }

  // What to call an option: its own name, with the appliance's name taken off
  // the front where Home Assistant put it there.
  _label(id) {
    const name = this._attr(id, "friendly_name");
    if (!name) return id;
    const device = this._hass.devices && this._hass.devices[this._device()];
    const machine = device && (device.name_by_user || device.name);
    return machine && name.startsWith(machine) ? name.slice(machine.length).trim() : name;
  }

  _render() {
    if (!this._hass) return;
    const device = this._device();
    const found = this._controls(device);
    this._found = found;
    const named = Object.keys(NAMED)
      .map((k) => (found[k] ? "1" : "0"))
      .join("");
    const options = [...found.switches, ...found.selects, ...found.numbers].join(",");
    const signature = `${device || ""}|${named}|${options}`;
    if (signature !== this._signature) {
      this._signature = signature;
      this._build(device, found);
    }
    this._paint(found);
  }

  _build(device, found) {
    const title = this._config.name || "Appliance";
    const note = !device
      ? applianceDevices(this._hass).length
        ? "More than one here. Set 'device' to the one you mean."
        : "No programme appliance found on this system."
      : "";
    if (note) {
      this.shadowRoot.innerHTML = `${STYLE}
        <ha-card><div class="title">${escape(title)}</div>
        <div class="note">${escape(note)}</div></ha-card>`;
      return;
    }

    const programme = found.programme
      ? `<label class="programme"><span class="cap">Programme</span><select class="picker prog" data-role="programme"></select></label>`
      : "";

    const forecasts = [];
    if (found.energy) forecasts.push(this._statCell("Energy", "energy"));
    if (found.water) forecasts.push(this._statCell("Water", "water"));
    forecasts.push(
      `<div class="stat"><span class="cap">Duration</span><span class="num" data-k="remaining">—</span></div>`
    );
    const cockpit = found.energy || found.water || found.remaining
      ? `<div class="stats">${forecasts.join("")}</div>`
      : "";

    const chips = found.switches
      .map(
        (id) => `<button class="pill" data-switch="${escape(id)}" type="button">
          <ha-icon icon="${iconFor(this._label(id))}"></ha-icon><span>${escape(this._label(id))}</span>
        </button>`
      )
      .join("");
    const chosers = found.selects
      .map(
        (id) => `<label class="field"><span class="cap">${escape(this._label(id))}</span>
          <select class="picker" data-select="${escape(id)}"></select></label>`
      )
      .join("");
    const sliders = found.numbers
      .map(
        (id) => `<label class="field slider"><span class="cap">${escape(this._label(id))}
          <b data-out="${escape(id)}"></b></span>
          <input type="range" data-number="${escape(id)}"></label>`
      )
      .join("");
    const options =
      chips || chosers || sliders
        ? `<div class="opts-head">Options</div>
           ${chips ? `<div class="opts">${chips}</div>` : ""}
           ${chosers ? `<div class="fields">${chosers}</div>` : ""}
           ${sliders ? `<div class="fields">${sliders}</div>` : ""}`
        : "";

    const quick = [];
    if (found.power)
      quick.push(
        `<label class="field"><span class="cap">Power</span><select class="picker" data-role="power"></select></label>`
      );
    if (found.childlock)
      quick.push(
        `<button class="pill lock" data-role="childlock" type="button"><ha-icon icon="mdi:lock"></ha-icon><span>Child lock</span></button>`
      );

    const actions =
      found.start || found.stop
        ? `<div class="actions">
             <button class="go" type="button"><ha-icon icon="mdi:play"></ha-icon><span>Start</span></button>
             <button class="stop" type="button"><ha-icon icon="mdi:stop"></ha-icon><span>Stop</span></button>
           </div>`
        : "";

    this.shadowRoot.innerHTML = `${STYLE}
      <ha-card>
        <div class="title">${escape(title)}</div>
        <div class="door" hidden>
          <span class="dot"><ha-icon icon="mdi:exclamation"></ha-icon></span>
          <span>Please close the door.</span>
        </div>
        ${programme}
        ${cockpit}
        ${options}
        <div class="quick">${quick.join("")}</div>
        ${actions}
      </ha-card>`;

    if (!this.shadowRoot.querySelector(".quick").children.length)
      this.shadowRoot.querySelector(".quick").hidden = true;
    this._wire(found);
  }

  _statCell(cap, key) {
    return `<div class="stat"><span class="cap">${cap}</span><span class="num" data-k="${key}">—</span>
      <div class="bar ${key}" data-bar="${key}">${"<span></span>".repeat(SEGMENTS)}</div></div>`;
  }

  _wire(found) {
    const root = this.shadowRoot;
    const prog = root.querySelector('[data-role="programme"]');
    if (prog)
      prog.addEventListener("change", () =>
        this._call(this._found.programme, "select", "select_option", { option: prog.value })
      );
    const power = root.querySelector('[data-role="power"]');
    if (power)
      power.addEventListener("change", () =>
        this._call(this._found.power, "select", "select_option", { option: power.value })
      );
    const lock = root.querySelector('[data-role="childlock"]');
    if (lock)
      lock.addEventListener("click", () => this._call(this._found.childlock, "switch", "toggle"));
    for (const pill of root.querySelectorAll("[data-switch]"))
      pill.addEventListener("click", () =>
        this._call(pill.dataset.switch, "switch", "toggle")
      );
    for (const el of root.querySelectorAll("[data-select]"))
      el.addEventListener("change", () =>
        this._call(el.dataset.select, "select", "select_option", { option: el.value })
      );
    for (const el of root.querySelectorAll("[data-number]"))
      el.addEventListener("change", () =>
        this._call(el.dataset.number, "number", "set_value", { value: Number(el.value) })
      );
    const go = root.querySelector(".go");
    if (go) go.addEventListener("click", () => this._call(this._found.start, "button", "press"));
    const stop = root.querySelector(".stop");
    if (stop) stop.addEventListener("click", () => this._call(this._found.stop, "button", "press"));
  }

  _paint(found) {
    const root = this.shadowRoot;
    if (!root || root.querySelector(".note")) return;

    const door = root.querySelector(".door");
    if (door) door.hidden = this._value(found.door) !== "on";

    this._fill(root.querySelector('[data-role="programme"]'), found.programme);
    this._fill(root.querySelector('[data-role="power"]'), found.power);
    const lock = root.querySelector('[data-role="childlock"]');
    if (lock) lock.classList.toggle("on", this._value(found.childlock) === "on");

    if (found.energy) this._stat("energy", found.energy);
    if (found.water) this._stat("water", found.water);
    const num = root.querySelector('[data-k="remaining"]');
    if (num) {
      const left = Number(this._value(found.remaining));
      num.textContent = left > 0 ? clock(left) : "—";
    }

    for (const id of found.switches) {
      const pill = root.querySelector(`[data-switch="${cssEscape(id)}"]`);
      if (pill) pill.classList.toggle("on", this._value(id) === "on");
    }
    for (const id of found.selects)
      this._fill(root.querySelector(`[data-select="${cssEscape(id)}"]`), id);
    for (const id of found.numbers) {
      const el = root.querySelector(`[data-number="${cssEscape(id)}"]`);
      const out = root.querySelector(`[data-out="${cssEscape(id)}"]`);
      const state = this._hass.states[id];
      if (el && state) {
        el.min = state.attributes.min ?? 0;
        el.max = state.attributes.max ?? 100;
        el.step = state.attributes.step ?? 1;
        if (!el.matches(":focus")) el.value = state.state;
      }
      if (out && state) {
        const unit = state.attributes.unit_of_measurement || "";
        out.textContent = `${state.state}${unit ? ` ${unit}` : ""}`;
      }
    }

    const go = root.querySelector(".go");
    if (go) go.disabled = !found.start || !door.hidden;
    const stop = root.querySelector(".stop");
    if (stop) stop.disabled = !found.stop;
  }

  _fill(el, id) {
    if (!el) return;
    const state = id && this._hass.states[id];
    if (!state) {
      el.disabled = true;
      return;
    }
    el.disabled = false;
    const options = state.attributes.options || [];
    const signature = options.join("");
    if (el._signature !== signature) {
      el._signature = signature;
      el.innerHTML = options
        .map((o) => `<option value="${escape(o)}">${escape(leaf(o))}</option>`)
        .join("");
    }
    if (!el.matches(":focus")) el.value = state.state;
  }

  _stat(key, id) {
    const root = this.shadowRoot;
    const raw = this._value(id);
    const value = Number(raw);
    const known = raw !== undefined && !Number.isNaN(value);
    const num = root.querySelector(`[data-k="${key}"]`);
    if (num) num.textContent = known ? `${Math.round(value)}%` : "—";
    const bar = root.querySelector(`[data-bar="${key}"]`);
    if (bar) {
      const lit = known ? Math.round((Math.max(0, Math.min(100, value)) / 100) * SEGMENTS) : 0;
      [...bar.children].forEach((seg, i) => seg.classList.toggle("lit", i < lit));
    }
  }
}

// A selector-safe entity id, so an id with a dot reads as one string.
const cssEscape = (id) =>
  window.CSS && CSS.escape ? CSS.escape(id) : id.replace(/[^a-zA-Z0-9_-]/g, "\\$&");

// Seconds as an appliance counts them, shown the way a timer reads.
function clock(seconds) {
  const m = Math.floor(seconds / 60);
  if (m >= 60) return `${Math.floor(m / 60)} h ${String(m % 60).padStart(2, "0")}`;
  return `${m} min`;
}

const STYLE = `
  <style>
    ha-card { padding: 16px; }
    [hidden] { display: none !important; }
    .title { font-size: 1.4em; font-weight: 700; letter-spacing: -.01em;
             margin: 0 0 14px; color: var(--primary-text-color); }
    .cap { font-size: .72em; letter-spacing: .05em; text-transform: uppercase;
           color: var(--secondary-text-color); }
    .note { color: var(--secondary-text-color); text-align: center; padding: 24px 8px; }
    .door { display: flex; gap: 10px; align-items: center; padding: 12px 14px;
            border-radius: 16px; margin-bottom: 14px; font-weight: 600;
            color: #7a3d00; background: #ffedd5; border: 1px solid rgba(234,120,20,.4); }
    .door .dot { width: 26px; height: 26px; border-radius: 50%; flex: 0 0 26px;
                 background: #ea7814; color: #fff; display: flex; align-items: center;
                 justify-content: center; --mdc-icon-size: 18px; }
    .programme { display: flex; align-items: center; justify-content: space-between;
                 gap: 12px; padding: 14px 16px; border-radius: 16px; margin-bottom: 16px;
                 background: var(--card-background-color, #fff);
                 box-shadow: 0 1px 3px rgba(0,0,0,.10); }
    .picker { font: inherit; padding: 9px 12px; border-radius: 12px;
              color: var(--primary-text-color); background: var(--secondary-background-color);
              border: 1px solid var(--divider-color); }
    .picker.prog { font-weight: 700; color: var(--primary-color); text-align: right;
                   border: none; background: transparent; max-width: 60%; }
    .stats { display: grid; grid-auto-flow: column; grid-auto-columns: 1fr;
             margin-bottom: 18px; }
    .stat { display: flex; flex-direction: column; gap: 4px; padding: 0 14px;
            border-left: 1px solid var(--divider-color); }
    .stat:first-child { border-left: none; padding-left: 0; }
    .stat .num { font-size: 1.25em; font-weight: 700; color: var(--primary-text-color); }
    .bar { display: flex; gap: 3px; margin-top: 4px; }
    .bar span { flex: 1; height: 5px; border-radius: 3px; background: var(--divider-color); }
    .bar.energy span.lit { background: #e8896b; }
    .bar.water span.lit { background: #4f9fe0; }
    .opts-head { font-weight: 700; margin: 4px 0 10px; color: var(--primary-text-color); }
    .opts { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 14px; }
    .fields { display: flex; flex-wrap: wrap; gap: 12px; margin-bottom: 14px; }
    .field { display: flex; flex-direction: column; gap: 5px; flex: 1 1 160px; min-width: 140px; }
    .field.slider b { font-weight: 700; color: var(--primary-text-color); }
    .field .picker, .field input[type=range] { width: 100%; }
    .quick { display: flex; flex-wrap: wrap; gap: 10px; align-items: flex-end;
             margin-bottom: 16px; }
    .quick:empty { display: none; }
    .pill { display: inline-flex; align-items: center; gap: 8px; font: inherit;
            cursor: pointer; padding: 9px 15px 9px 12px; border-radius: 999px;
            border: 1px solid var(--divider-color); background: transparent;
            color: var(--primary-text-color); transition: all .2s ease; --mdc-icon-size: 20px; }
    .pill ha-icon { color: var(--secondary-text-color); }
    .pill.on { border-color: var(--primary-color); color: var(--primary-color);
               background: color-mix(in srgb, var(--primary-color) 12%, transparent);
               font-weight: 600; }
    .pill.on ha-icon { color: var(--primary-color); }
    .actions { display: flex; gap: 10px; }
    .actions button { flex: 1; display: inline-flex; align-items: center; justify-content: center;
                      gap: 8px; font: inherit; font-weight: 700; cursor: pointer; padding: 14px;
                      border-radius: 14px; border: none; --mdc-icon-size: 20px; }
    .go { background: var(--primary-color); color: var(--text-primary-color, #fff); }
    .stop { background: var(--secondary-background-color); color: var(--primary-text-color); }
    .actions button:disabled { opacity: .5; cursor: default; }
  </style>`;

class HomeConnectApplianceCardEditor extends HTMLElement {
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
        ({ device: "Appliance", name: "Name (optional)" })[schema.name] || schema.name;
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
      { name: "device", required: true, selector: { device: { integration: "homeconnect" } } },
      { name: "name", selector: { text: {} } },
    ];
  }
}

if (!customElements.get(CARD)) {
  customElements.define(CARD, HomeConnectApplianceCard);
  customElements.define(`${CARD}-editor`, HomeConnectApplianceCardEditor);
}

window.customCards = window.customCards || [];
if (!window.customCards.some((c) => c.type === CARD)) {
  window.customCards.push({
    type: CARD,
    name: "Home Connect Appliance",
    description: "Any programme machine: washer, dryer, oven, coffee and the rest, driven like the app.",
    preview: true,
  });
}
