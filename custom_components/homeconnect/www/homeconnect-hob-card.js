// A Lovelace card that draws a hob the way the Home Connect app does: the dark
// glass surface, with each cooking zone painted on it showing its power level,
// whether it is heating, its temperature and any countdown.
//
// The picture is drawn rather than photographed, because that is what the app
// does too: there is no cooktop image anywhere, and no appliance reports where
// its zones physically sit, so they are laid out in a tidy grid rather than in
// the exact arrangement of one particular model.
//
// Bundled with the homeconnect integration, which serves this file and loads
// it, so there is no resource to add by hand.

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

class HomeConnectHobCard extends HTMLElement {
  setConfig(config) {
    if (!config || !config.device) {
      throw new Error("Set 'device' to the hob's device id.");
    }
    this._config = config;
    this._signature = null;
    if (!this.shadowRoot) this.attachShadow({ mode: "open" });
  }

  set hass(hass) {
    this._hass = hass;
    this._render();
  }

  getCardSize() {
    return 5;
  }

  static getStubConfig() {
    return { device: "" };
  }

  // Every zone entity on the chosen device, gathered by the number of its zone.
  _zones() {
    const entities = (this._hass && this._hass.entities) || {};
    const found = {};
    for (const entity_id of Object.keys(entities)) {
      if (entities[entity_id].device_id !== this._config.device) continue;
      const match = entity_id.match(ZONE);
      if (!match) continue;
      const number = match[1];
      let field = match[2].replace("programme", "program");
      (found[number] ||= {})[field] = entity_id;
    }
    return found;
  }

  _value(entity_id) {
    if (!entity_id) return undefined;
    const state = this._hass.states[entity_id];
    return state ? state.state : undefined;
  }

  _render() {
    if (!this._hass) return;
    const zones = this._zones();
    const numbers = Object.keys(zones).sort((a, b) => Number(a) - Number(b));
    const signature = numbers.join(",");

    // Rebuild the frame only when the set of zones changes, so a value moving
    // does not throw the whole card away and build it again.
    if (signature !== this._signature) {
      this._signature = signature;
      this._build(numbers);
    }
    for (const number of numbers) this._paint(number, zones[number]);
  }

  _build(numbers) {
    const columns = Math.max(1, Math.ceil(Math.sqrt(numbers.length || 1)));
    const title = this._config.name || "Hob";
    const tiles = numbers
      .map(
        (n) => `
          <div class="zone" id="zone-${n}">
            <div class="ring"><span class="level"></span></div>
            <div class="under"><span class="temp"></span><span class="left"></span></div>
          </div>`
      )
      .join("");
    const empty = numbers.length
      ? ""
      : `<div class="empty">No zones found for this device.</div>`;

    this.shadowRoot.innerHTML = `
      <style>
        ha-card { padding: 16px; }
        .title { font-size: 1.1em; font-weight: 500; margin: 0 0 12px 4px;
                 color: var(--primary-text-color); }
        .glass {
          position: relative; border-radius: 18px; aspect-ratio: 1 / 1;
          background:
            radial-gradient(120% 90% at 30% 15%, #3a4351 0%, #2b323d 45%, #1c2027 100%);
          box-shadow: inset 0 1px 2px rgba(255,255,255,.06),
                      inset 0 -8px 24px rgba(0,0,0,.5);
          padding: 6%; display: grid; gap: 6%;
          grid-template-columns: repeat(${columns}, 1fr);
          align-content: center;
        }
        .zone { display: flex; flex-direction: column; align-items: center;
                justify-content: center; gap: 6px; min-width: 0; }
        .ring {
          position: relative; width: 100%; aspect-ratio: 1 / 1; max-width: 120px;
          border-radius: 50%; display: flex; align-items: center;
          justify-content: center;
          border: 2px solid rgba(255,255,255,.14);
          background: radial-gradient(circle at 50% 50%,
                      rgba(255,255,255,.05), rgba(0,0,0,.25));
          transition: box-shadow .3s ease, border-color .3s ease;
        }
        .ring::before {
          content: ""; position: absolute; inset: 14%; border-radius: 50%;
          border: 1px solid rgba(255,255,255,.10);
        }
        .zone.on .ring {
          border-color: rgba(255,150,60,.85);
          box-shadow: 0 0 18px rgba(255,120,30,.55),
                      inset 0 0 22px rgba(255,90,20,.45);
        }
        .zone.boost .ring {
          border-color: rgba(255,80,60,.95);
          box-shadow: 0 0 26px rgba(255,50,30,.8),
                      inset 0 0 26px rgba(255,40,20,.6);
        }
        .level { font-size: 1.7em; font-weight: 600; color: #f5f7fa;
                 text-shadow: 0 1px 3px rgba(0,0,0,.6); line-height: 1; }
        .zone:not(.on):not(.boost) .level { color: rgba(230,235,245,.45); }
        .under { display: flex; gap: 10px; font-size: .8em; min-height: 1em;
                 color: rgba(230,235,245,.75); }
        .under:empty { display: none; }
        .empty { color: rgba(230,235,245,.7); grid-column: 1 / -1;
                 text-align: center; align-self: center; }
      </style>
      <ha-card>
        <div class="title">${title}</div>
        <div class="glass">${tiles || empty}</div>
      </ha-card>`;
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
    const tempEl = tile.querySelector(".temp");
    tempEl.textContent = !off && temp && Number(temp) > 0 ? `${Math.round(Number(temp))}°` : "";

    const left = this._value(fields.remaining_program_time);
    const leftEl = tile.querySelector(".left");
    leftEl.textContent = !off && left && Number(left) > 0 ? _clock(Number(left)) : "";
  }
}

// Seconds as an appliance counts them, shown the way a timer reads.
function _clock(seconds) {
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds % 60);
  if (m >= 60) {
    const h = Math.floor(m / 60);
    return `${h}:${String(m % 60).padStart(2, "0")}`;
  }
  return `${m}:${String(s).padStart(2, "0")}`;
}

customElements.define("homeconnect-hob-card", HomeConnectHobCard);

window.customCards = window.customCards || [];
window.customCards.push({
  type: "homeconnect-hob-card",
  name: "Home Connect Hob",
  description: "A cooktop with its zones, their power, heat and timers.",
  preview: false,
});
