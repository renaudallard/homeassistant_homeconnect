// A Lovelace card that lays a dishwasher out the way the Home Connect app
// does when a programme is picked: the programme and what it will cost, the
// options along the bottom, and a start and a stop, with the door warning
// across the top when the door is open.
//
// It reads and drives the entities the integration already makes, so there is
// nothing to wire up: the programme select, the energy and water forecasts,
// the remaining time, each option switch and the two programme buttons are
// found on the appliance by the names they carry.
//
// Bundled with the homeconnect integration, which serves this file and adds
// it as a dashboard resource, so there is no resource to add by hand.

const CARD = "homeconnect-dishwasher-card";

// The options the app shows as pills, in the order it shows them, each paired
// with the tail of the entity that stands for it.
const OPTIONS = [
  { slug: "vario_speed_plus", label: "SpeedPerfect+" },
  { slug: "extra_dry", label: "Extra dry" },
  { slug: "hygiene_plus", label: "Hygiene+" },
  { slug: "half_load", label: "Half load" },
  { slug: "intensiv_zone", label: "Intensive zone" },
  { slug: "silence_on_demand", label: "Silent" },
];

// Half load and the intensive zone are a dishwasher's own, so a device with a
// switch for either is a dishwasher and no washer or dryer is taken for one.
const SIGNATURE = /^switch\..*_(half_load|intensiv_zone)$/;

// The one-of-a-kind readings and controls, each pinned to the kind of entity
// it is as well as the tail of its name, so a sensor about the selected
// programme is not mistaken for the programme select that drives it.
// Programme time is spelled both ways depending on where the words came from.
const FIELDS = {
  programme: /^select\..*_programme$/,
  energy: /^sensor\..*_energy_forecast$/,
  water: /^sensor\..*_water_forecast$/,
  remaining: /^sensor\..*_remaining_program(?:me)?_time$/,
  door: /^binary_sensor\..*_door_state$/,
  start: /^button\..*_start_program(?:me)?$/,
  stop: /^button\..*_stop_program(?:me)?$/,
};

const OFF = new Set(["off", "inactive", "", undefined, null, "unavailable", "unknown"]);

// The last part of a value, so a key reads as its own tail: Eco50 from
// Dishcare.Dishwasher.Program.Eco50, Run from OperationState.Run.
const leaf = (value) =>
  typeof value === "string" && value.includes(".")
    ? value.split(".").pop()
    : value;

// Every device that carries a dishwasher's own option, which is every
// dishwasher and nothing else.
function dishDevices(hass) {
  const entities = (hass && hass.entities) || {};
  const devices = new Set();
  for (const entity_id of Object.keys(entities)) {
    if (SIGNATURE.test(entity_id) && entities[entity_id].device_id) {
      devices.add(entities[entity_id].device_id);
    }
  }
  return [...devices];
}

class HomeConnectDishwasherCard extends HTMLElement {
  setConfig(config) {
    // The device is not required: with one dishwasher on the system it is
    // found on its own, and only more than one has to be told apart.
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
    const devices = dishDevices(hass);
    return devices.length === 1 ? { device: devices[0] } : { device: "" };
  }

  // The chosen dishwasher, or the only one there is when none was chosen.
  _device() {
    if (this._config.device) return this._config.device;
    const devices = dishDevices(this._hass);
    return devices.length === 1 ? devices[0] : undefined;
  }

  // The entities on that dishwasher, gathered by what each one is for.
  _entities(device) {
    const found = { options: {} };
    const entities = (this._hass && this._hass.entities) || {};
    if (!device) return found;
    for (const entity_id of Object.keys(entities)) {
      if (entities[entity_id].device_id !== device) continue;
      for (const [name, pattern] of Object.entries(FIELDS)) {
        if (pattern.test(entity_id)) found[name] = entity_id;
      }
      for (const option of OPTIONS) {
        if (entity_id.startsWith("switch.") && entity_id.endsWith(`_${option.slug}`)) {
          found.options[option.slug] = entity_id;
        }
      }
    }
    return found;
  }

  _value(entity_id) {
    if (!entity_id || !this._hass) return undefined;
    const state = this._hass.states[entity_id];
    return state ? state.state : undefined;
  }

  _call(entity_id, domain, service) {
    if (!entity_id || !this._hass) return;
    this._hass.callService(domain, service, { entity_id });
  }

  _render() {
    if (!this._hass) return;
    const device = this._device();
    const found = this._entities(device);
    const present = OPTIONS.filter((o) => found.options[o.slug]);
    const signature = `${device || ""}|${present.map((o) => o.slug).join(",")}`;

    // Rebuild the frame only when the dishwasher or its set of options changes,
    // so the click handlers are wired once and a value moving does not throw
    // the card away and build it again.
    if (signature !== this._signature) {
      this._signature = signature;
      this._build(device, present);
    }
    this._found = found;
    this._paint(found, present);
  }

  _build(device, present) {
    const title = this._config.name || "Dishwasher";
    const note = !device
      ? dishDevices(this._hass).length
        ? "More than one dishwasher here. Set 'device' to the one you mean."
        : "No dishwasher found on this system."
      : "";

    const pills = present
      .map(
        (o) =>
          `<button class="pill" data-slug="${o.slug}" type="button">${o.label}</button>`
      )
      .join("");

    this.shadowRoot.innerHTML = `
      <style>
        ha-card { padding: 16px; }
        .title { font-size: 1.2em; font-weight: 600; margin: 0 0 12px;
                 color: var(--primary-text-color); }
        .door { display: flex; gap: 10px; align-items: center; padding: 10px 12px;
                border-radius: 12px; margin-bottom: 12px; font-weight: 500;
                color: #7a3d00; background: #ffedd5;
                border: 1px solid rgba(234,120,20,.5); }
        .door .dot { width: 18px; height: 18px; border-radius: 50%; flex: 0 0 18px;
                     background: #ea7814; color: #fff; font-weight: 700;
                     display: flex; align-items: center; justify-content: center;
                     font-size: 13px; }
        .prog { display: flex; justify-content: space-between; align-items: baseline;
                padding: 12px 14px; border-radius: 12px; margin-bottom: 14px;
                background: var(--secondary-background-color); }
        .prog .lab { color: var(--secondary-text-color); }
        .prog .val { font-size: 1.15em; font-weight: 600;
                     color: var(--primary-color); }
        .stats { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px;
                 margin-bottom: 16px; }
        .stat .cap { font-size: .72em; letter-spacing: .04em; text-transform: uppercase;
                     color: var(--secondary-text-color); }
        .stat .num { font-size: 1.15em; font-weight: 600; margin-top: 2px;
                     color: var(--primary-text-color); }
        .bar { height: 4px; border-radius: 2px; margin-top: 6px;
               background: var(--divider-color); overflow: hidden; }
        .bar > span { display: block; height: 100%; width: 0;
                      background: var(--primary-color); }
        .opts { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 16px; }
        .opts:empty { display: none; }
        .pill { font: inherit; cursor: pointer; padding: 8px 14px; border-radius: 999px;
                border: 1px solid var(--divider-color); background: transparent;
                color: var(--primary-text-color); transition: all .2s ease; }
        .pill.on { border-color: var(--primary-color); color: var(--primary-color);
                   background: color-mix(in srgb, var(--primary-color) 12%, transparent);
                   font-weight: 600; }
        .pill:disabled { opacity: .5; cursor: default; }
        .actions { display: flex; gap: 10px; }
        .actions button { flex: 1; font: inherit; font-weight: 600; cursor: pointer;
                          padding: 12px; border-radius: 12px; border: none; }
        .go { background: var(--primary-color); color: var(--text-primary-color, #fff); }
        .stop { background: var(--secondary-background-color);
                color: var(--primary-text-color); }
        .actions button:disabled { opacity: .5; cursor: default; }
        .note { color: var(--secondary-text-color); text-align: center; padding: 24px 8px; }
      </style>
      <ha-card>
        <div class="title">${title}</div>
        ${note ? `<div class="note">${note}</div>` : ""}
        <div class="door" hidden><span class="dot">!</span><span>Please close the door.</span></div>
        <div class="prog">
          <span class="lab">Programme</span><span class="val">—</span>
        </div>
        <div class="stats">
          <div class="stat"><div class="cap">Energy</div><div class="num" data-k="energy">—</div><div class="bar"><span data-b="energy"></span></div></div>
          <div class="stat"><div class="cap">Water</div><div class="num" data-k="water">—</div><div class="bar"><span data-b="water"></span></div></div>
          <div class="stat"><div class="cap">Duration</div><div class="num" data-k="remaining">—</div></div>
        </div>
        <div class="opts">${pills}</div>
        <div class="actions">
          <button class="go" type="button">Start</button>
          <button class="stop" type="button">Stop</button>
        </div>
      </ha-card>`;

    if (note) {
      // Nothing to drive, so leave the body but wire nothing.
      this.shadowRoot.querySelectorAll(".prog, .stats, .opts, .actions").forEach(
        (el) => (el.hidden = true)
      );
      return;
    }

    for (const pill of this.shadowRoot.querySelectorAll(".pill")) {
      pill.addEventListener("click", () => {
        const entity_id = this._found.options[pill.dataset.slug];
        this._call(entity_id, "switch", "toggle");
      });
    }
    this.shadowRoot
      .querySelector(".go")
      .addEventListener("click", () => this._call(this._found.start, "button", "press"));
    this.shadowRoot
      .querySelector(".stop")
      .addEventListener("click", () => this._call(this._found.stop, "button", "press"));
  }

  _paint(found, present) {
    const root = this.shadowRoot;
    if (!root || !found || root.querySelector(".note")) return;

    // The door reads as a binary sensor: on is open, which is when the app
    // shows the warning and greys the start.
    const door = root.querySelector(".door");
    if (door) door.hidden = this._value(found.door) !== "on";

    const prog = root.querySelector(".prog .val");
    if (prog) {
      const name = leaf(this._value(found.programme));
      prog.textContent = OFF.has(String(name).toLowerCase()) ? "—" : String(name);
    }

    this._stat("energy", found.energy);
    this._stat("water", found.water);

    const num = root.querySelector('[data-k="remaining"]');
    if (num) {
      const left = Number(this._value(found.remaining));
      num.textContent = left > 0 ? clock(left) : "—";
    }

    for (const option of present) {
      const pill = root.querySelector(`.pill[data-slug="${option.slug}"]`);
      if (!pill) continue;
      const on = this._value(found.options[option.slug]) === "on";
      pill.classList.toggle("on", on);
    }

    const go = root.querySelector(".go");
    if (go) go.disabled = !found.start || !door.hidden;
    const stop = root.querySelector(".stop");
    if (stop) stop.disabled = !found.stop;
  }

  // One percentage stat: the number, and a bar filled to it.
  _stat(key, entity_id) {
    const root = this.shadowRoot;
    const num = root.querySelector(`[data-k="${key}"]`);
    const bar = root.querySelector(`[data-b="${key}"]`);
    const raw = this._value(entity_id);
    const value = Number(raw);
    if (num) num.textContent = raw === undefined || Number.isNaN(value) ? "—" : `${Math.round(value)}%`;
    if (bar) bar.style.width = Number.isNaN(value) ? "0" : `${Math.max(0, Math.min(100, value))}%`;
  }
}

// Seconds as an appliance counts them, shown the way a timer reads.
function clock(seconds) {
  const m = Math.floor(seconds / 60);
  if (m >= 60) return `${Math.floor(m / 60)} h ${String(m % 60).padStart(2, "0")}`;
  return `${m} min`;
}

// The little form shown when the card is edited: pick the dishwasher, name it.
class HomeConnectDishwasherCardEditor extends HTMLElement {
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
        ({ device: "Dishwasher", name: "Name (optional)" })[schema.name] || schema.name;
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
  customElements.define(CARD, HomeConnectDishwasherCard);
  customElements.define(`${CARD}-editor`, HomeConnectDishwasherCardEditor);
}

window.customCards = window.customCards || [];
if (!window.customCards.some((c) => c.type === CARD)) {
  window.customCards.push({
    type: CARD,
    name: "Home Connect Dishwasher",
    description: "A dishwasher's programme, what it will use, its options and start.",
    preview: true,
  });
}
