// A Lovelace card for the machines that hold a temperature rather than run a
// programme: a fridge, a freezer, a fridge-freezer. They have no programme and
// no start, so the programme card does not fit them; what they have is a
// temperature to set for each compartment and a handful of modes, super and
// eco and holiday and the child lock, which is what this lays out.
//
// It reads whatever the appliance keeps, the way the app does: every
// temperature it will let you set as a stepper, and every mode it offers as a
// switch, with the door warning across the top while a door is open.
//
// Bundled with the homeconnect integration, which serves this file and adds it
// as a dashboard resource, so there is no resource to add by hand.

const CARD = "homeconnect-cooling-card";

const escape = (text) =>
  String(text).replace(
    /[&<>"']/g,
    (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[ch]
  );

const leaf = (value) =>
  typeof value === "string" && value.includes(".")
    ? value.split(".").pop()
    : value;

// A cooling machine is a Home Connect one with settings to hold but no
// programme to run and no plates to draw. A washer has a programme, a hob has
// its zones, so both are left to their own cards; a fridge has neither, which
// is what marks it out.
function coolingDevices(hass) {
  const entities = (hass && hass.entities) || {};
  const seen = {};
  for (const id of Object.keys(entities)) {
    const entity = entities[id];
    if (entity.platform !== "homeconnect" || !entity.device_id) continue;
    const mark = (seen[entity.device_id] ||= { prog: false, zone: false, control: false });
    if (/^select\..*_programme$/.test(id)) mark.prog = true;
    if (/_zone_\d+_/.test(id)) mark.zone = true;
    const controllable = id.startsWith("number.") || id.startsWith("switch.");
    if (controllable && entity.entity_category !== "diagnostic") mark.control = true;
  }
  return Object.keys(seen).filter((d) => seen[d].control && !seen[d].prog && !seen[d].zone);
}

class HomeConnectCoolingCard extends HTMLElement {
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
    return 6;
  }

  static getConfigElement() {
    return document.createElement(`${CARD}-editor`);
  }

  static getStubConfig(hass) {
    const devices = coolingDevices(hass);
    return devices.length === 1 ? { device: devices[0] } : { device: "" };
  }

  _device() {
    if (this._config.device) return this._config.device;
    const devices = coolingDevices(this._hass);
    return devices.length === 1 ? devices[0] : undefined;
  }

  // What the machine keeps to be set: the temperatures, the mode switches, and
  // any other choice. Housekeeping that only reports, marked diagnostic, is
  // stepped over; the rest is what a fridge is actually set by.
  _controls(device) {
    const found = { temps: [], modes: [], selects: [], doors: [] };
    const entities = (this._hass && this._hass.entities) || {};
    if (!device) return found;
    for (const id of Object.keys(entities)) {
      const entity = entities[id];
      if (entity.device_id !== device || entity.platform !== "homeconnect") continue;
      if (id.startsWith("binary_sensor.") && /_door(_state)?$/.test(id)) {
        found.doors.push(id);
        continue;
      }
      if (entity.entity_category === "diagnostic") continue;
      if (id.startsWith("number.")) found.temps.push(id);
      else if (id.startsWith("switch.")) found.modes.push(id);
      else if (id.startsWith("select.")) found.selects.push(id);
    }
    for (const key of ["temps", "modes", "selects"]) found[key].sort();
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
    const signature = `${device || ""}|${found.temps.join(",")}|${found.modes.join(",")}|${found.selects.join(",")}`;
    if (signature !== this._signature) {
      this._signature = signature;
      this._build(device, found);
    }
    this._paint(found);
  }

  _build(device, found) {
    const title = this._config.name || "Fridge";
    const note = !device
      ? coolingDevices(this._hass).length
        ? "More than one here. Set 'device' to the one you mean."
        : "No fridge or freezer found on this system."
      : "";
    if (note) {
      this.shadowRoot.innerHTML = `${STYLE}
        <ha-card><div class="title">${escape(title)}</div>
        <div class="note">${escape(note)}</div></ha-card>`;
      return;
    }

    const temps = found.temps
      .map(
        (id) => `<div class="temp" data-number="${escape(id)}">
          <span class="cap">${escape(this._label(id))}</span>
          <div class="step">
            <button data-step="-1" type="button">−</button>
            <b data-out="${escape(id)}">—</b>
            <button data-step="1" type="button">+</button>
          </div>
        </div>`
      )
      .join("");
    const modes = found.modes
      .map(
        (id) => `<button class="pill" data-switch="${escape(id)}" type="button">
          <ha-icon icon="${iconFor(this._label(id))}"></ha-icon><span>${escape(this._label(id))}</span>
        </button>`
      )
      .join("");
    const selects = found.selects
      .map(
        (id) => `<label class="field"><span class="cap">${escape(this._label(id))}</span>
          <select class="picker" data-select="${escape(id)}"></select></label>`
      )
      .join("");

    this.shadowRoot.innerHTML = `${STYLE}
      <ha-card>
        <div class="title">${escape(title)}</div>
        <div class="door" hidden>
          <span class="dot"><ha-icon icon="mdi:exclamation"></ha-icon></span>
          <span>Please close the door.</span>
        </div>
        ${temps ? `<div class="temps">${temps}</div>` : ""}
        ${modes ? `<div class="opts-head">Modes</div><div class="opts">${modes}</div>` : ""}
        ${selects ? `<div class="fields">${selects}</div>` : ""}
      </ha-card>`;

    this._wire(found);
  }

  _wire(found) {
    const root = this.shadowRoot;
    for (const box of root.querySelectorAll("[data-number]")) {
      const id = box.dataset.number;
      for (const button of box.querySelectorAll("[data-step]")) {
        button.addEventListener("click", () => this._nudge(id, Number(button.dataset.step)));
      }
    }
    for (const pill of root.querySelectorAll("[data-switch]")) {
      pill.addEventListener("click", () => this._call(pill.dataset.switch, "switch", "toggle"));
    }
    for (const el of root.querySelectorAll("[data-select]")) {
      el.addEventListener("change", () =>
        this._call(el.dataset.select, "select", "select_option", { option: el.value })
      );
    }
  }

  // Move a temperature one step, kept inside the range the appliance allows.
  _nudge(id, direction) {
    const state = this._hass.states[id];
    if (!state) return;
    const step = Number(state.attributes.step) || 1;
    const min = Number(state.attributes.min);
    const max = Number(state.attributes.max);
    let next = Number(state.state) + direction * step;
    if (!Number.isNaN(min)) next = Math.max(min, next);
    if (!Number.isNaN(max)) next = Math.min(max, next);
    this._call(id, "number", "set_value", { value: next });
  }

  _paint(found) {
    const root = this.shadowRoot;
    if (!root || root.querySelector(".note")) return;

    const open = found.doors.some((id) => this._value(id) === "on");
    const door = root.querySelector(".door");
    if (door) door.hidden = !open;

    for (const id of found.temps) {
      const out = root.querySelector(`[data-out="${cssEscape(id)}"]`);
      const state = this._hass.states[id];
      if (out && state) {
        const unit = state.attributes.unit_of_measurement || "";
        out.textContent = `${Math.round(Number(state.state))}${unit ? ` ${unit}` : ""}`;
      }
    }
    for (const id of found.modes) {
      const pill = root.querySelector(`[data-switch="${cssEscape(id)}"]`);
      if (pill) pill.classList.toggle("on", this._value(id) === "on");
    }
    for (const id of found.selects) {
      const el = root.querySelector(`[data-select="${cssEscape(id)}"]`);
      const state = id && this._hass.states[id];
      if (!el || !state) continue;
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
  }
}

const ICONS = [
  [/super|boost|fast/, "mdi:snowflake-alert"],
  [/freez/, "mdi:snowflake"],
  [/eco|energy|holiday|vacation/, "mdi:leaf"],
  [/fresh|vita|humid/, "mdi:sprout-outline"],
  [/child|lock/, "mdi:lock"],
  [/ice/, "mdi:cube-outline"],
  [/light|display/, "mdi:lightbulb-outline"],
];

function iconFor(label) {
  const text = String(label).toLowerCase();
  for (const [pattern, icon] of ICONS) if (pattern.test(text)) return icon;
  return "mdi:tune-variant";
}

const cssEscape = (id) =>
  window.CSS && CSS.escape ? CSS.escape(id) : id.replace(/[^a-zA-Z0-9_-]/g, "\\$&");

const STYLE = `
  <style>
    ha-card { padding: 16px; }
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
    .temps { display: flex; flex-direction: column; gap: 10px; margin-bottom: 16px; }
    .temp { display: flex; align-items: center; justify-content: space-between; gap: 12px;
            padding: 12px 16px; border-radius: 16px;
            background: var(--card-background-color, #fff); box-shadow: 0 1px 3px rgba(0,0,0,.10); }
    .step { display: flex; align-items: center; gap: 14px; }
    .step b { font-size: 1.3em; font-weight: 700; min-width: 3.5ch; text-align: center;
              color: var(--primary-color); }
    .step button { width: 38px; height: 38px; border-radius: 50%; border: 1px solid var(--divider-color);
                   background: var(--secondary-background-color); color: var(--primary-text-color);
                   font-size: 1.3em; line-height: 1; cursor: pointer; }
    .opts-head { font-weight: 700; margin: 4px 0 10px; color: var(--primary-text-color); }
    .opts { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 14px; }
    .fields { display: flex; flex-wrap: wrap; gap: 12px; }
    .field { display: flex; flex-direction: column; gap: 5px; flex: 1 1 160px; min-width: 140px; }
    .field .picker { width: 100%; }
    .picker { font: inherit; padding: 9px 12px; border-radius: 12px;
              color: var(--primary-text-color); background: var(--secondary-background-color);
              border: 1px solid var(--divider-color); }
    .pill { display: inline-flex; align-items: center; gap: 8px; font: inherit;
            cursor: pointer; padding: 9px 15px 9px 12px; border-radius: 999px;
            border: 1px solid var(--divider-color); background: transparent;
            color: var(--primary-text-color); transition: all .2s ease; --mdc-icon-size: 20px; }
    .pill ha-icon { color: var(--secondary-text-color); }
    .pill.on { border-color: var(--primary-color); color: var(--primary-color);
               background: color-mix(in srgb, var(--primary-color) 12%, transparent); font-weight: 600; }
    .pill.on ha-icon { color: var(--primary-color); }
  </style>`;

class HomeConnectCoolingCardEditor extends HTMLElement {
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
        ({ device: "Fridge or freezer", name: "Name (optional)" })[schema.name] || schema.name;
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
  customElements.define(CARD, HomeConnectCoolingCard);
  customElements.define(`${CARD}-editor`, HomeConnectCoolingCardEditor);
}

window.customCards = window.customCards || [];
if (!window.customCards.some((c) => c.type === CARD)) {
  window.customCards.push({
    type: CARD,
    name: "Home Connect Cooling",
    description: "A fridge or freezer: its compartment temperatures and its modes.",
    preview: true,
  });
}
