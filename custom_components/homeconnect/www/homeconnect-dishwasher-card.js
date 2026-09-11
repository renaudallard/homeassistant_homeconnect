// A Lovelace card that lays a dishwasher out the way the Home Connect app
// does, and drives it the same way: the programme across a card of its own,
// what the run will cost in energy and water on coloured bars, the options as
// pills with an icon each, the power and the child lock to hand, and a start
// and a stop, with the door warning across the top while the door is open.
//
// It reads and drives the entities the integration already makes, so there is
// nothing to wire up: the programme and power selects, the option switches,
// the child lock, the energy and water forecasts, the remaining time and the
// two programme buttons are found on the appliance by the names they carry.
//
// Bundled with the homeconnect integration, which serves this file and adds it
// as a dashboard resource, so there is no resource to add by hand.

const CARD = "homeconnect-dishwasher-card";

// The options the app shows as pills, in its order, each paired with the tail
// of the switch that stands for it and a line-art icon that stands for it.
const OPTIONS = [
  { slug: "vario_speed_plus", label: "SpeedPerfect+", icon: "mdi:fast-forward" },
  { slug: "extra_dry", label: "Extra dry", icon: "mdi:tumble-dryer" },
  { slug: "hygiene_plus", label: "Hygiene+", icon: "mdi:shield-plus-outline" },
  { slug: "half_load", label: "Half load", icon: "mdi:circle-half-full" },
  { slug: "intensiv_zone", label: "Intensive zone", icon: "mdi:target" },
  { slug: "silence_on_demand", label: "Silent", icon: "mdi:volume-off" },
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
  power: /^select\..*_power_state$/,
  childlock: /^switch\..*_child_lock$/,
  energy: /^sensor\..*_energy_forecast$/,
  water: /^sensor\..*_water_forecast$/,
  remaining: /^sensor\..*_remaining_program(?:me)?_time$/,
  door: /^binary_sensor\..*_door_state$/,
  start: /^button\..*_start_program(?:me)?$/,
  stop: /^button\..*_stop_program(?:me)?$/,
};

// How many bits a forecast bar is drawn in, the way the app draws it.
const SEGMENTS = 5;

const OFF = new Set(["off", "inactive", "", undefined, null, "unavailable", "unknown"]);

// The last part of a value, so a key reads as its own tail: Eco50 from
// Dishcare.Dishwasher.Program.Eco50, On from PowerState.On.
const leaf = (value) =>
  typeof value === "string" && value.includes(".")
    ? value.split(".").pop()
    : value;

const escape = (text) =>
  String(text).replace(
    /[&<>"']/g,
    (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[ch]
  );

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
    return 8;
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

  _call(entity_id, domain, service, extra) {
    if (!entity_id || !this._hass) return;
    this._hass.callService(domain, service, { entity_id, ...(extra || {}) });
  }

  _render() {
    if (!this._hass) return;
    const device = this._device();
    const found = this._entities(device);
    const present = OPTIONS.filter((o) => found.options[o.slug]);
    const has = ["programme", "power", "childlock", "start", "stop"]
      .map((k) => (found[k] ? "1" : "0"))
      .join("");
    const signature = `${device || ""}|${present.map((o) => o.slug).join(",")}|${has}`;

    if (signature !== this._signature) {
      this._signature = signature;
      this._build(device, found, present);
    }
    this._found = found;
    this._paint(found, present);
  }

  _build(device, found, present) {
    const title = this._config.name || "Dishwasher";
    const note = !device
      ? dishDevices(this._hass).length
        ? "More than one dishwasher here. Set 'device' to the one you mean."
        : "No dishwasher found on this system."
      : "";

    if (note) {
      this.shadowRoot.innerHTML = `${STYLE}
        <ha-card>
          <div class="title">${escape(title)}</div>
          <div class="note">${escape(note)}</div>
        </ha-card>`;
      return;
    }

    const programme = found.programme
      ? `<label class="programme"><span class="cap">Programme</span><select class="picker prog" data-role="programme"></select></label>`
      : `<div class="programme"><span class="cap">Programme</span><span class="prog-text" data-role="progtext">—</span></div>`;

    const bar = (key) =>
      `<div class="bar ${key}" data-bar="${key}">${'<span></span>'.repeat(SEGMENTS)}</div>`;

    const pills = present
      .map(
        (o) => `<button class="pill" data-slug="${o.slug}" type="button">
          <ha-icon icon="${o.icon}"></ha-icon><span>${o.label}</span>
        </button>`
      )
      .join("");

    const quick = [];
    if (found.power)
      quick.push(
        `<label class="field"><span class="cap">Power</span><select class="picker" data-role="power"></select></label>`
      );
    if (found.childlock)
      quick.push(
        `<button class="pill lock" data-role="childlock" type="button">
          <ha-icon icon="mdi:lock"></ha-icon><span>Child lock</span>
        </button>`
      );

    this.shadowRoot.innerHTML = `${STYLE}
      <ha-card>
        <div class="title">${escape(title)}</div>
        <div class="door" hidden>
          <span class="dot"><ha-icon icon="mdi:exclamation"></ha-icon></span>
          <span>Please close the door.</span>
        </div>
        ${programme}
        <div class="stats">
          <div class="stat"><span class="cap">Energy</span><span class="num" data-k="energy">—</span>${bar("energy")}</div>
          <div class="stat"><span class="cap">Water</span><span class="num" data-k="water">—</span>${bar("water")}</div>
          <div class="stat"><span class="cap">Duration</span><span class="num" data-k="remaining">—</span></div>
        </div>
        <div class="opts-head" ${present.length ? "" : "hidden"}>Options</div>
        <div class="opts">${pills}</div>
        <div class="quick">${quick.join("")}</div>
        <div class="actions">
          <button class="go" type="button"><ha-icon icon="mdi:play"></ha-icon><span>Start</span></button>
          <button class="stop" type="button"><ha-icon icon="mdi:stop"></ha-icon><span>Stop</span></button>
        </div>
      </ha-card>`;

    if (!this.shadowRoot.querySelector(".quick").children.length)
      this.shadowRoot.querySelector(".quick").hidden = true;

    this._wire("power", () =>
      this._call(this._found.power, "select", "select_option", {
        option: this._pick("power").value,
      })
    );
    this._wire("programme", () =>
      this._call(this._found.programme, "select", "select_option", {
        option: this._pick("programme").value,
      })
    );
    const lock = this.shadowRoot.querySelector('[data-role="childlock"]');
    if (lock)
      lock.addEventListener("click", () =>
        this._call(this._found.childlock, "switch", "toggle")
      );
    for (const pill of this.shadowRoot.querySelectorAll(".pill[data-slug]")) {
      pill.addEventListener("click", () =>
        this._call(this._found.options[pill.dataset.slug], "switch", "toggle")
      );
    }
    this.shadowRoot
      .querySelector(".go")
      .addEventListener("click", () => this._call(this._found.start, "button", "press"));
    this.shadowRoot
      .querySelector(".stop")
      .addEventListener("click", () => this._call(this._found.stop, "button", "press"));
  }

  _pick(role) {
    return this.shadowRoot.querySelector(`[data-role="${role}"]`);
  }

  _wire(role, handler) {
    const el = this._pick(role);
    if (el && el.tagName === "SELECT") el.addEventListener("change", handler);
  }

  _paint(found, present) {
    const root = this.shadowRoot;
    if (!root || !found || root.querySelector(".note")) return;

    // The door reads as a binary sensor: on is open, which is when the app
    // shows the warning and greys the start.
    const door = root.querySelector(".door");
    if (door) door.hidden = this._value(found.door) !== "on";

    this._fill(this._pick("power"), found.power);
    this._fill(this._pick("programme"), found.programme);

    const text = this._pick("progtext");
    if (text) {
      const name = leaf(this._value(found.programme));
      const shown = name == null ? "" : String(name);
      text.textContent = OFF.has(shown.toLowerCase()) ? "—" : shown;
    }

    const lock = root.querySelector('[data-role="childlock"]');
    if (lock) lock.classList.toggle("on", this._value(found.childlock) === "on");

    this._stat("energy", found.energy);
    this._stat("water", found.water);

    const num = root.querySelector('[data-k="remaining"]');
    if (num) {
      const left = Number(this._value(found.remaining));
      num.textContent = left > 0 ? clock(left) : "—";
    }

    for (const option of present) {
      const pill = root.querySelector(`.pill[data-slug="${option.slug}"]`);
      if (pill) pill.classList.toggle("on", this._value(found.options[option.slug]) === "on");
    }

    const go = root.querySelector(".go");
    if (go) go.disabled = !found.start || !door.hidden;
    const stop = root.querySelector(".stop");
    if (stop) stop.disabled = !found.stop;
  }

  // Fill a select from the entity's own list of choices, once per change of
  // that list so an open menu is not rebuilt under the finger, and point it at
  // what is chosen now. A value read as its own tail, so a key reads plainly.
  _fill(el, entity_id) {
    if (!el) return;
    const state = entity_id && this._hass.states[entity_id];
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
    // Not while the menu is open under the finger: an unrelated state change
    // repaints, and resetting the value then would drop the user's choice.
    if (!el.matches(":focus")) el.value = state.state;
  }

  // One forecast: its percentage as a number, and a bar lit in bits to it, the
  // way the app fills a segmented gauge.
  _stat(key, entity_id) {
    const root = this.shadowRoot;
    const num = root.querySelector(`[data-k="${key}"]`);
    const raw = this._value(entity_id);
    const value = Number(raw);
    const known = raw !== undefined && !Number.isNaN(value);
    if (num) num.textContent = known ? `${Math.round(value)}%` : "—";
    const bar = root.querySelector(`[data-bar="${key}"]`);
    if (bar) {
      const lit = known ? Math.round((Math.max(0, Math.min(100, value)) / 100) * SEGMENTS) : 0;
      [...bar.children].forEach((seg, i) => seg.classList.toggle("lit", i < lit));
    }
  }
}

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
    .programme .prog-text { font-size: 1.15em; font-weight: 700; color: var(--primary-color); }
    .picker { font: inherit; padding: 9px 12px; border-radius: 12px;
              color: var(--primary-text-color); background: var(--secondary-background-color);
              border: 1px solid var(--divider-color); }
    .picker.prog { font-weight: 700; color: var(--primary-color); text-align: right;
                   border: none; background: transparent; max-width: 60%; }
    .field { display: flex; flex-direction: column; gap: 5px; flex: 1 1 auto; min-width: 130px; }
    .field .picker { width: 100%; }
    .stats { display: grid; grid-template-columns: repeat(3, 1fr); gap: 0;
             margin-bottom: 18px; }
    .stat { display: flex; flex-direction: column; gap: 4px; padding: 0 14px;
            border-left: 1px solid var(--divider-color); }
    .stat:first-child { border-left: none; padding-left: 0; }
    .stat .num { font-size: 1.25em; font-weight: 700; color: var(--primary-text-color); }
    .bar { display: flex; gap: 3px; margin-top: 4px; }
    .bar span { flex: 1; height: 5px; border-radius: 3px; background: var(--divider-color); }
    .bar.energy span.lit { background: #e8896b; }
    .bar.water span.lit { background: #4f9fe0; }
    .opts-head { font-weight: 700; margin: 0 0 10px; color: var(--primary-text-color); }
    .opts { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 16px; }
    .opts:empty { display: none; }
    .quick { display: flex; flex-wrap: wrap; gap: 10px; align-items: flex-end;
             margin-bottom: 16px; }
    .quick:empty { display: none; }
    .pill { display: inline-flex; align-items: center; gap: 8px; font: inherit;
            cursor: pointer; padding: 9px 15px 9px 12px; border-radius: 999px;
            border: 1px solid var(--divider-color); background: transparent;
            color: var(--primary-text-color); transition: all .2s ease;
            --mdc-icon-size: 20px; }
    .pill ha-icon { color: var(--secondary-text-color); }
    .pill.on { border-color: var(--primary-color); color: var(--primary-color);
               background: color-mix(in srgb, var(--primary-color) 12%, transparent);
               font-weight: 600; }
    .pill.on ha-icon { color: var(--primary-color); }
    .pill:disabled { opacity: .5; cursor: default; }
    .actions { display: flex; gap: 10px; }
    .actions button { flex: 1; display: inline-flex; align-items: center;
                      justify-content: center; gap: 8px; font: inherit; font-weight: 700;
                      cursor: pointer; padding: 14px; border-radius: 14px; border: none;
                      --mdc-icon-size: 20px; }
    .go { background: var(--primary-color); color: var(--text-primary-color, #fff); }
    .stop { background: var(--secondary-background-color); color: var(--primary-text-color); }
    .actions button:disabled { opacity: .5; cursor: default; }
  </style>`;

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
    description: "A dishwasher's programme, options, power and start, driven like the app.",
    preview: true,
  });
}
