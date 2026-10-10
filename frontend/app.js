/* SuryaWatch web app: Plan + Watch, in English or Hindi. No build step. */
(function () {
  "use strict";

  const API = (window.SURYAWATCH_API || "").replace(/\/$/, "");
  const $ = (id) => document.getElementById(id);
  const DELHI = [28.6139, 77.209];
  const SQFT_PER_M2 = 10.7639;

  if (!API) $("api-banner").hidden = false;

  // ------------------------------------------------------------------ language (English | हिंदी)
  // Every visible string is written in English and passed through t(); i18n.js holds the Hindi.
  const LANG_KEY = "suryawatch.lang";
  const HI = window.SW_HI || {};
  let LANG = (() => { try { return localStorage.getItem(LANG_KEY) === "hi" ? "hi" : "en"; } catch (_) { return "en"; } })();
  function t(s, vars) {
    let out = (LANG === "hi" && HI[s]) || s;
    if (vars) out = out.replace(/\{(\w+)\}/g, (m, k) => (k in vars ? vars[k] : m));
    return out;
  }
  const LOCALE = () => (LANG === "hi" ? "hi-IN" : "en-IN");
  const niceDate = (date, opts) => new Date(date.slice(0, 10) + "T12:00").toLocaleDateString(LOCALE(), opts);
  const SAID = new Set();
  function say(el, key, vars) {          // set a message that follows the language switch
    el._say = [key, vars];
    SAID.add(el);
    el.textContent = key ? t(key, vars) : "";
  }

  // ------------------------------------------------------------------ formatting
  const inr = (x) => "₹" + Math.round(x).toLocaleString("en-IN");
  const lakh = (x) => (Math.abs(x) >= 100000 ? "₹" + (x / 100000).toFixed(2).replace(/\.?0+$/, "") + " " + t("lakh") : inr(x));
  const n0 = (x) => Math.round(x).toLocaleString("en-IN");
  const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

  async function api(path, opts) {
    if (!API) throw new Error(t("The app is not connected to its server yet."));
    const res = await fetch(API + path, opts);
    let body = {};
    try { body = await res.json(); } catch (_) { /* empty body */ }
    if (!res.ok) throw new Error(body.error ? t(body.error) : t("Server error ({status}). Please try again.", { status: res.status }));
    return body;
  }

  // ------------------------------------------------------------------ tabs
  const TABS = ["plan", "watch", "impact"], VIEWS = TABS.concat("report");
  const tabFromHash = () => (VIEWS.includes(location.hash.slice(1)) ? location.hash.slice(1) : "plan");
  function showTab(name) {
    VIEWS.forEach((x) => { $("view-" + x).hidden = x !== name; });
    TABS.forEach((x) => $("tab-" + x).setAttribute("aria-selected", String(x === name || (name === "report" && x === "watch"))));
    if (name === "plan" && map) setTimeout(() => map.invalidateSize(), 50);
    if (name === "impact") loadImpact();
    if (name === "report") { window.scrollTo(0, 0); loadReport(); }
  }
  TABS.forEach((x) => { $("tab-" + x).onclick = () => { location.hash = x; }; });
  window.addEventListener("hashchange", () => showTab(tabFromHash()));

  // ------------------------------------------------------------------ map
  let map = null, marker = null, roof = null, drawing = false, vertices = [];
  const loc = { lat: null, lon: null };

  function initMap() {
    if (typeof L === "undefined") { $("map").textContent = t("Map could not load. You can still type your roof area."); return; }
    map = L.map("map", { zoomControl: true }).setView(DELHI, 11);
    L.tileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}", {
      maxZoom: 20, maxNativeZoom: 19, attribution: "Imagery © Esri, Maxar, Earthstar Geographics",
    }).addTo(map);
    L.tileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}", {
      maxZoom: 20, maxNativeZoom: 19, opacity: 0.85,
    }).addTo(map);
    map.on("click", (e) => (drawing ? addVertex(e.latlng) : setLocation(e.latlng.lat, e.latlng.lng)));
    map.on("dblclick", () => { if (drawing) finishDrawing(); });
  }

  function setLocation(lat, lon, zoom) {
    loc.lat = lat; loc.lon = lon;
    if (!map) return;
    if (marker) marker.setLatLng([lat, lon]);
    else marker = L.circleMarker([lat, lon], { radius: 7, color: "#fff", weight: 2, fillColor: "#c98a00", fillOpacity: 1 }).addTo(map);
    if (zoom) map.setView([lat, lon], zoom);
    say($("map-hint"), "Home placed. Now draw the roof outline, or type the area below.");
  }

  function polygonAreaM2(pts) {
    if (pts.length < 3) return 0;
    const R = 6371008.8, rad = Math.PI / 180;
    const lat0 = (pts.reduce((s, p) => s + p.lat, 0) / pts.length) * rad;
    const xy = pts.map((p) => [R * p.lng * rad * Math.cos(lat0), R * p.lat * rad]);
    let a = 0;
    for (let i = 0; i < xy.length; i++) {
      const [x1, y1] = xy[i], [x2, y2] = xy[(i + 1) % xy.length];
      a += x1 * y2 - x2 * y1;
    }
    return Math.abs(a) / 2;
  }

  function addVertex(latlng) {
    vertices.push(latlng);
    if (roof) roof.setLatLngs(vertices);
    else roof = L.polygon(vertices, { color: "#f2c14e", weight: 2, fillColor: "#f2c14e", fillOpacity: 0.25 }).addTo(map);
    updateAreaFromRoof();
  }

  function updateAreaFromRoof() {
    const m2 = polygonAreaM2(vertices);
    if (m2 > 0) {
      const unit = $("area-unit").value;
      $("area").value = Math.round(unit === "sqft" ? m2 * SQFT_PER_M2 : m2);
      if (m2 > 3000) say($("map-hint"), "That outline is {m2} m², bigger than most homes. Zoom in to your own roof and draw again.", { m2: n0(m2) });
      else say($("map-hint"), "Roof outline: {m2} m² ({sqft} sq ft).", { m2: n0(m2), sqft: n0(m2 * SQFT_PER_M2) });
    }
  }

  const drawLabel = () => { $("draw-btn").textContent = t(drawing ? "Finish outline" : "Draw roof outline"); };
  function finishDrawing() {
    drawing = false;
    map.doubleClickZoom.enable();
    drawLabel();
    $("draw-btn").setAttribute("aria-pressed", "false");
    if (vertices.length >= 3) {
      const c = roof.getBounds().getCenter();
      setLocation(c.lat, c.lng);
      updateAreaFromRoof();
    }
  }

  $("draw-btn").onclick = () => {
    if (!map) return;
    if (drawing) { finishDrawing(); return; }
    drawing = true;
    vertices = [];
    if (roof) { map.removeLayer(roof); roof = null; }
    map.doubleClickZoom.disable();
    drawLabel();
    $("draw-btn").setAttribute("aria-pressed", "true");
    say($("map-hint"), "Click each corner of the roof. Double-click or press Finish when done.");
    if (map.getZoom() < 17) {
      map.setView(loc.lat !== null ? [loc.lat, loc.lon] : map.getCenter(), 19);
      say($("map-hint"), "Zoomed in. Find your roof, then click each of its corners. Double-click or press Finish when done.");
    }
  };
  $("clear-btn").onclick = () => {
    if (roof) { map.removeLayer(roof); roof = null; }
    vertices = []; drawing = false;
    if (map) map.doubleClickZoom.enable();
    drawLabel();
    $("draw-btn").setAttribute("aria-pressed", "false");
    say($("map-hint"), "Outline cleared.");
  };
  $("area-unit").onchange = () => {
    const v = parseFloat($("area").value);
    if (!v) return;
    $("area").value = Math.round($("area-unit").value === "sqft" ? v * SQFT_PER_M2 : v / SQFT_PER_M2);
  };

  async function search() {
    const q = $("search").value.trim();
    if (!q) return;
    say($("map-hint"), "Searching...");
    try {
      const url = "https://nominatim.openstreetmap.org/search?format=json&limit=1&countrycodes=in&q=" + encodeURIComponent(q);
      const res = await fetch(url, { headers: { "Accept-Language": "en" } });
      const hits = await res.json();
      if (!hits.length) { say($("map-hint"), "No match. Try a nearby landmark or locality."); return; }
      setLocation(parseFloat(hits[0].lat), parseFloat(hits[0].lon), 18);
      say($("map-hint"), "Found. Click your exact roof, then draw its outline.");
    } catch (_) {
      say($("map-hint"), "Search is unavailable. Click your home on the map instead.");
    }
  }
  $("search-btn").onclick = search;
  $("search").addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); search(); } });
  $("locate-btn").onclick = () => {
    if (!navigator.geolocation) return;
    say($("map-hint"), "Finding you...");
    navigator.geolocation.getCurrentPosition(
      (p) => setLocation(p.coords.latitude, p.coords.longitude, 19),
      () => { say($("map-hint"), "Location permission denied. Search or click the map instead."); },
      { enableHighAccuracy: true, timeout: 10000 });
  };

  // ------------------------------------------------------------------ chart (hand-rolled SVG, single series)
  const tip = $("tip");
  function showTip(html, ev) {
    tip.innerHTML = html; tip.hidden = false;
    const x = Math.min(ev.clientX + 14, window.innerWidth - tip.offsetWidth - 8);
    tip.style.left = x + "px"; tip.style.top = (ev.clientY - tip.offsetHeight - 12) + "px";
  }
  const hideTip = () => { tip.hidden = true; };

  function niceStep(max, target) {
    const raw = max / target, pow = Math.pow(10, Math.floor(Math.log10(raw)));
    return [1, 2, 2.5, 5, 10].map((m) => m * pow).find((s) => raw <= s) || pow * 10;
  }

  function barChart(el, data, o) {
    const W = Math.round(Math.max(300, el.clientWidth || 560)), H = 230, ml = 40, mr = 8, mt = 26, mb = 28;
    const iw = W - ml - mr, ih = H - mt - mb;
    const peak = Math.max(...data.map((d) => d.value), o.ref || 0, 0.001);
    const step = niceStep(peak, 4), ymax = Math.ceil(peak / step) * step;
    const y = (v) => mt + ih - (v / ymax) * ih;
    const band = iw / data.length, bw = Math.min(24, band * 0.62);
    const every = o.labelEvery || (band < 30 ? 2 : 1);
    let svg = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(o.title)}">`;
    for (let v = 0; v <= ymax + 1e-9; v += step) {
      svg += `<line class="gridline" x1="${ml}" x2="${W - mr}" y1="${y(v)}" y2="${y(v)}"/>`;
      svg += `<text class="axis-text" x="${ml - 8}" y="${y(v) + 4}" text-anchor="end">${o.fmtTick ? o.fmtTick(v) : n0(v)}</text>`;
    }
    data.forEach((d, i) => {
      const cx = ml + band * i + band / 2, x0 = cx - bw / 2, top = y(d.value), base = y(0);
      const h = base - top, r = Math.min(4, h / 2, bw / 2);
      if (h > 0.5) {
        svg += `<path class="bar" data-i="${i}" d="M${x0},${base} V${top + r} Q${x0},${top} ${x0 + r},${top} H${x0 + bw - r} Q${x0 + bw},${top} ${x0 + bw},${top + r} V${base} Z"/>`;
      }
      if (i % every === 0) {
        svg += `<text class="axis-text" x="${cx}" y="${H - 8}" text-anchor="middle">${esc(d.label)}</text>`;
      }
      svg += `<rect class="hit" data-i="${i}" x="${ml + band * i}" y="${mt}" width="${band}" height="${ih}"/>`;
    });
    if (o.ref) {
      svg += `<line class="ref" x1="${ml}" x2="${W - mr}" y1="${y(o.ref)}" y2="${y(o.ref)}"/>`;
      svg += `<text class="ref-text" x="${W - mr}" y="${y(o.ref) - 6}" text-anchor="end">${esc(o.refLabel)}</text>`;
    }
    svg += "</svg>";
    el.innerHTML = `<p class="chart-title">${esc(o.title)}</p>${o.sub ? `<p class="chart-sub">${esc(o.sub)}</p>` : ""}<div class="chart">${svg}</div>`;
    el.querySelectorAll(".hit").forEach((hit) => {
      const i = +hit.dataset.i, bar = el.querySelector(`.bar[data-i="${i}"]`);
      const move = (ev) => { showTip(o.tip(data[i]), ev); if (bar) bar.classList.add("hl"); };
      hit.addEventListener("mousemove", move);
      hit.addEventListener("click", move);
      hit.addEventListener("mouseleave", () => { hideTip(); if (bar) bar.classList.remove("hl"); });
    });
  }

  // ------------------------------------------------------------------ sharing (WhatsApp)
  const appLink = (q) => `${location.origin}${location.pathname}${q || ""}`;
  function shareWhatsApp(text) {
    window.open("https://wa.me/?text=" + encodeURIComponent(text), "_blank", "noopener");
  }

  // ------------------------------------------------------------------ plan
  const PORTAL_STEPS = [
    "Register on pmsuryaghar.gov.in with your state, electricity company and consumer number.",
    "Log in with your consumer number and mobile number.",
    "Apply for rooftop solar using the online form.",
    "Wait for approval from your electricity company (DISCOM).",
    "Get the system installed by a registered vendor (vendor ratings are on the portal).",
    "Submit the plant details and apply for a net meter.",
    "The DISCOM installs the net meter, inspects, and issues a commissioning certificate.",
    "Submit your bank details and a cancelled cheque on the portal.",
    "Receive the central subsidy in your bank account (the scheme targets about 30 days).",
  ];

  const monthName = (i) => new Date(2026, i, 1).toLocaleDateString(LOCALE(), { month: "short" });

  function renderPlan(r) {
    const months = r.months.map((m, i) => ({ label: monthName(i), value: m.generation_kwh }));
    const subsidy = r.central_subsidy + r.state_subsidy;
    const payback = r.payback_years == null ? t("Over 25 years") : t("{n} years", { n: r.payback_years });
    const notes = r.notes.map((x) => `<p class="note">${esc(x)}</p>`).join("");
    $("plan-result").innerHTML = `
      <div class="hero">
        <div class="label">${t("Recommended system")}</div>
        <div class="big num">${r.system_kw} kW</div>
        <div class="sub">${esc(t(r.limited_by === "roof"
          ? "About {panels} panels of 550 W, making {units} units a year. Sized by your roof space."
          : "About {panels} panels of 550 W, making {units} units a year. Sized by your electricity use.",
          { panels: r.panels_approx, units: n0(r.yearly_generation_kwh) }))}</div>
      </div>
      <div class="stats">
        <div class="stat"><div class="label">${t("You pay after subsidy")}</div><div class="value num">${lakh(r.net_cost)}</div></div>
        <div class="stat"><div class="label">${t("Benefit per month")}</div><div class="value good num">${inr(r.monthly_benefit_avg)}</div></div>
        <div class="stat"><div class="label">${t("Pays back in")}</div><div class="value num">${payback}</div></div>
        <div class="stat"><div class="label">${t("25-year benefit")}</div><div class="value num">${lakh(r.lifetime_benefit_25y)}</div></div>
        <div class="stat"><div class="label">${t("CO₂ avoided")}</div><div class="value num">${t("{n} t/yr", { n: r.co2_tonnes_per_year })}</div></div>
        <div class="stat"><div class="label">${t("Subsidy total")}</div><div class="value good num">${lakh(subsidy)}</div></div>
      </div>
      ${notes}
      <table class="breakdown">
        <tr><td>${t("System cost ({kw} kW × {cost})", { kw: r.system_kw, cost: inr(r.inputs.cost_per_kw) })}</td><td>${inr(r.gross_cost)}</td></tr>
        <tr><td>${t("PM Surya Ghar subsidy")}</td><td class="minus">− ${inr(r.central_subsidy)}</td></tr>
        ${r.state_subsidy ? `<tr><td>${t("Delhi Solar Policy subsidy")}</td><td class="minus">− ${inr(r.state_subsidy)}</td></tr>` : ""}
        <tr class="total"><td>${t("You pay")}</td><td>${inr(r.net_cost)}</td></tr>
      </table>
      <div id="plan-chart"></div>
      <details><summary>${t("Where the yearly benefit comes from")}</summary><ul>
        <li>${t("Lower electricity bills: {rs} a year", { rs: inr(r.yearly_bill_saving) })}</li>
        ${r.yearly_gbi_first5 ? `<li>${t("Delhi generation incentive: {rs} a year for the first 5 years", { rs: inr(r.yearly_gbi_first5) })}</li>` : ""}
        <li>${esc(t("Sunlight data: {src} ({n} units per kW per year)", { src: t(r.sunlight_source), n: n0(r.yield_kwh_per_kwp) }))}</li>
      </ul></details>
      <details><summary>${t("Assumptions")}</summary><ul>${r.assumptions.map((a) => `<li>${esc(a)}</li>`).join("")}</ul></details>
      <details><summary>${t("How to apply under PM Surya Ghar")}</summary><ol>${PORTAL_STEPS.map((x) => `<li>${esc(t(x))}</li>`).join("")}</ol></details>
      <div class="share-row">
        <button type="button" id="plan-watch" class="btn small">${t("We installed this: start watching it")}</button>
        <button type="button" id="plan-share" class="btn small ghost wa">${t("Share this plan on WhatsApp")}</button>
      </div>
      <p id="plan-watch-msg" class="hint" hidden></p>
      <div id="plan-ask"></div>`;
    $("plan-watch").onclick = async () => {
      const msg = $("plan-watch-msg");
      const yearly = r.yearly_bill_saving + r.yearly_gbi_first5;
      const unit = Math.min(30, Math.max(1, r.yearly_generation_kwh ? yearly / r.yearly_generation_kwh : 6));
      try {
        const s = await api("/systems", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({
          name: t("Our rooftop"), lat: r.inputs.lat, lon: r.inputs.lon, kwp: r.system_kw, tilt: 20, facing: 180,
          unit_value: Math.round(unit * 10) / 10, promise_kwh_year: r.yearly_generation_kwh,
          promise_source: "plan", plan_id: r.plan_id }) });
        safeSet(STORE_KEY, s.system_id);
        location.hash = "watch";
        await openSystem(s.system_id);
      } catch (ex) { say(msg, ex.message); msg.hidden = false; }
    };
    $("plan-share").onclick = () => shareWhatsApp([
      t("SuryaWatch solar plan"),
      t("{kw} kW rooftop system (about {panels} panels), {units} units a year", { kw: r.system_kw, panels: r.panels_approx, units: n0(r.yearly_generation_kwh) }),
      t("Cost after subsidy: {cost} (subsidy {subsidy})", { cost: inr(r.net_cost), subsidy: inr(r.central_subsidy + r.state_subsidy) }),
      t("Benefit: about {rs} a month", { rs: inr(r.monthly_benefit_avg) }) + "; " +
        (r.payback_years == null ? t("payback over 25 years") : t("pays back in {n} years", { n: r.payback_years })),
      t("Plan your own roof: {link}", { link: appLink("#plan") }),
    ].join("\n"));
    helperBox($("plan-ask"), "plan", () => ({ system_kw: r.system_kw, yearly_units: r.yearly_generation_kwh, net_cost: r.net_cost,
      central_subsidy: r.central_subsidy, state_subsidy: r.state_subsidy, monthly_benefit: r.monthly_benefit_avg,
      payback_years: r.payback_years, monthly_units: r.inputs.monthly_units, state: r.inputs.state, roof_m2: r.inputs.roof_area_m2,
      limited_by: r.limited_by, notes: r.notes }));
    barChart($("plan-chart"), months, {
      title: t("Units your panels make each month"),
      sub: t("Dashed line: your monthly use"),
      ref: r.inputs.monthly_units, refLabel: t("Your use: {n} units", { n: n0(r.inputs.monthly_units) }),
      tip: (d) => `<b>${esc(d.label)}</b><br>${t("{n} units made", { n: n0(d.value) })}<br>${t("{n} units used", { n: n0(r.inputs.monthly_units) })}`,
    });
  }

  // read units, DISCOM and sanctioned load from a bill photo (Amazon Bedrock; the photo is not stored)
  $("bill-file").onchange = async (e) => {
    const file = (e.target.files || [])[0];
    e.target.value = "";
    if (!file) return;
    const msg = $("bill-msg");
    say(msg, "Reading your bill...");
    try {
      const r = await api("/bill", { method: "POST", headers: { "content-type": "application/json" },
        body: JSON.stringify({ image_base64: await shrink(file) }) });
      if (!r.ai_available) { say(msg, r.message); return; }
      const units = r.average_monthly_units || r.monthly_units;
      if (units) {
        document.querySelector('input[name="usage-kind"][value="units"]').checked = true;
        $("usage").value = Math.round(units);
      }
      if (r.state) $("state").value = r.state;
      if (r.sanctioned_load_kw) $("sload").value = r.sanctioned_load_kw;
      const parts = [];
      if (r.monthly_units) parts.push(t("{n} units a month on this bill", { n: n0(r.monthly_units) }));
      if (r.average_monthly_units) parts.push(t("{m}-month average {n} units (used above)", { m: r.history.length, n: n0(r.average_monthly_units) }));
      if (r.discom) parts.push(r.discom);
      if (r.sanctioned_load_kw) parts.push(t("sanctioned load {n} kW", { n: r.sanctioned_load_kw }));
      if (units) say(msg, "Read from your bill ({conf} confidence): {parts}. Please check the numbers.", { conf: t(r.confidence || "medium"), parts: parts.join(" · ") });
      else say(msg, "Could not find the units on this bill. Please type them in.");
      if (units && r.notes) msg.textContent += " " + r.notes;
    } catch (ex) {
      say(msg, ex.name === "InvalidStateError" ? "This photo format can't be opened. Please use a JPG." : ex.message);
    }
  };

  $("plan-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const err = $("plan-error");
    err.hidden = true;
    const areaRaw = parseFloat($("area").value);
    const usage = parseFloat($("usage").value);
    const kind = document.querySelector('input[name="usage-kind"]:checked').value;
    const problems = [];
    if (loc.lat === null) problems.push(t("place your home on the map"));
    if (!(areaRaw > 0)) problems.push(t("enter the roof area"));
    if (!(usage > 0)) problems.push(t(kind === "units" ? "enter your monthly units" : "enter your monthly bill"));
    if (problems.length) { say(err, "Please {list}.", { list: problems.join(", ") }); err.hidden = false; return; }
    const m2 = $("area-unit").value === "sqft" ? areaRaw / SQFT_PER_M2 : areaRaw;
    const body = {
      lat: loc.lat, lon: loc.lon, roof_area_m2: m2,
      usable_fraction: (parseFloat($("usable").value) || 70) / 100,
      state: $("state").value, cost_per_kw: parseFloat($("cost").value) || 60000,
      sanctioned_load_kw: parseFloat($("sload").value) || null,
    };
    body[kind === "units" ? "monthly_units" : "monthly_bill"] = usage;
    const btn = $("plan-btn");
    btn.disabled = true; btn.textContent = t("Working out your plan...");
    try {
      await runPlan(body);
      if (window.innerWidth < 900) $("plan-result").scrollIntoView({ behavior: "smooth" });
    } catch (ex) {
      say(err, ex.message); err.hidden = false;
    } finally {
      btn.disabled = false; btn.textContent = t("Plan my solar");
    }
  });
  let lastPlanBody = null;
  async function runPlan(body) {
    const r = await api("/plan", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ ...body, lang: LANG }) });
    lastPlanBody = body;
    renderPlan(r);
  }

  // ------------------------------------------------------------------ watch mode
  const STORE_KEY = "suryawatch.system";
  const safeGet = (k) => { try { return localStorage.getItem(k); } catch (_) { return null; } };
  const safeSet = (k, v) => { try { v == null ? localStorage.removeItem(k) : localStorage.setItem(k, v); } catch (_) { /* private mode */ } };
  const pad = (n) => String(n).padStart(2, "0");
  const localStamp = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
  const todayStr = () => localStamp(new Date()).slice(0, 10);
  const clock = (ts) => { const h = +ts.slice(11, 13), m = ts.slice(14, 16); return `${h % 12 || 12}:${m} ${h < 12 ? "AM" : "PM"}`; };
  const pct = (x) => (x == null ? "–" : Math.round(x * 100) + "%");
  const hourLabel = (h) => (h === 12 ? "12 PM" : h < 12 ? `${h} AM` : `${h - 12} PM`);

  let sys = null;          // current system meta
  let sysReady = null;     // the first openSystem() call, so the report view can wait for it
  let viewDate = todayStr();
  let review = [];         // readings waiting to be saved

  const STATUS = {        // labels go through t() when shown
    healthy: { label: "Working well", cls: "good", icon: "M5 12l4 4 10-10" },
    smog: { label: "Smog day", cls: "warn", icon: "M3 9h13M5 13h15M3 17h11" },
    dust: { label: "Clean panels", cls: "serious", icon: "M12 3v12M7 10l5 5 5-5M5 20h14" },
    fault: { label: "Possible fault", cls: "critical", icon: "M12 4v9M12 17v.5" },
    check: { label: "Check system", cls: "warn", icon: "M12 4v9M12 17v.5" },
    no_data: { label: "No reading yet", cls: "none", icon: "M5 12h14" },
    too_early: { label: "Too early", cls: "none", icon: "M12 6v6l4 2" },
    area: { label: "Area-wide dip", cls: "warn", icon: "M3 20v-8l4-3 4 3v8M13 20v-6l4-3 4 3v6M2 20h20" },
  };

  // ---- setup
  function parseLoc(text) {
    const m = String(text).match(/(-?\d+(?:\.\d+)?)\s*[, ]\s*(-?\d+(?:\.\d+)?)/);
    return m ? { lat: parseFloat(m[1]), lon: parseFloat(m[2]) } : null;
  }
  $("s-from-plan").onclick = () => {
    if (loc.lat === null) { say($("s-error"), "Place your home on the Plan tab's map first."); $("s-error").hidden = false; return; }
    $("s-loc").value = `${loc.lat.toFixed(5)}, ${loc.lon.toFixed(5)}`;
  };
  $("s-my").onclick = () => navigator.geolocation && navigator.geolocation.getCurrentPosition(
    (p) => { $("s-loc").value = `${p.coords.latitude.toFixed(5)}, ${p.coords.longitude.toFixed(5)}`; },
    () => { say($("s-error"), "Location permission denied. Paste the numbers instead."); $("s-error").hidden = false; });

  $("s-save").onclick = async () => {
    const err = $("s-error");
    err.hidden = true;
    const where = parseLoc($("s-loc").value);
    const kwp = parseFloat($("s-kwp").value);
    if (!where) { say(err, "Enter the location as two numbers, like 28.7041, 77.1025."); err.hidden = false; return; }
    if (!(kwp > 0)) { say(err, "Enter the system size in kW (it is on the inverter label or the installer's bill)."); err.hidden = false; return; }
    const btn = $("s-save");
    btn.disabled = true;
    try {
      const r = await api("/systems", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({
        name: $("s-name").value, lat: where.lat, lon: where.lon, kwp, tilt: $("s-tilt").value, facing: $("s-facing").value,
        unit_value: $("s-unit").value, promise_kwh_year: $("s-promise").value || null }) });
      safeSet(STORE_KEY, r.system_id);
      await openSystem(r.system_id);
    } catch (ex) { say(err, ex.message); err.hidden = false; } finally { btn.disabled = false; }
  };

  $("s-open").onclick = () => {
    const raw = $("s-open-id").value.trim();
    const m = raw.match(/system=([a-z0-9]+)/i) || raw.match(/^([a-z0-9]{6,20})$/i);
    if (!m) { say($("s-error"), "Paste the full link or the 10-character system ID."); $("s-error").hidden = false; return; }
    $("s-error").hidden = true;
    safeSet(STORE_KEY, m[1].toLowerCase());
    openSystem(m[1].toLowerCase());
  };

  // ---- dashboard
  async function openSystem(id) {
    try {
      sys = await api("/systems/" + encodeURIComponent(id));
    } catch (ex) {
      safeSet(STORE_KEY, null);
      $("w-setup").hidden = false; $("w-dash").hidden = true;
      say($("s-error"), ex.message); $("s-error").hidden = false;
      return;
    }
    $("w-setup").hidden = true; $("w-dash").hidden = false;
    renderHead();
    $("d-date").max = todayStr();
    loadOutlook();
    loadDust();
    await loadDay(viewDate);
  }

  const FACING = { 180: "south", 135: "south-east", 225: "south-west", 90: "east", 270: "west", 0: "north" };
  const sysName = (s) => (s.name === "Our rooftop" ? t(s.name) : s.name);
  function renderHead() {
    $("d-name").textContent = sysName(sys);
    const facing = FACING[Math.round(sys.facing)];
    $("d-meta").textContent = t("{kw} kW · panels face {facing}, {tilt}° tilt · {lat}, {lon}", {
      kw: sys.kwp, facing: facing ? t(facing) : `${sys.facing}°`, tilt: sys.tilt, lat: sys.lat.toFixed(3), lon: sys.lon.toFixed(3) });
  }

  async function loadDay(date) {
    viewDate = date;
    $("d-date").value = date;
    $("d-next").disabled = date >= todayStr();
    $("d-verdict").innerHTML = `<p class="hint">${t("Checking the sunlight and air for this day...")}</p>`;
    try {
      const d = await api(`/systems/${sys.system_id}/day?date=${date}&lang=${LANG}`);
      renderVerdict(d);
      renderCharts(d);
      renderReadings(d);
      refreshSummary();
    } catch (ex) {
      $("d-verdict").innerHTML = `<p class="error">${esc(ex.message)}</p>`;
    }
  }

  function renderVerdict(d) {
    const v = d.verdict, st = STATUS[v.code] || STATUS.no_data;
    const badge = `<span class="badge ${st.cls}"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="${st.icon}"/></svg>${t(st.label)}</span>`;
    let stats = "";
    if (v.actual_kwh != null) {
      stats = `<div class="stats">
        <div class="stat"><div class="label">${t(v.final ? "Made" : "Made so far")}</div><div class="value num">${v.actual_kwh} kWh</div></div>
        <div class="stat"><div class="label">${t("Sunlight allowed")}</div><div class="value num">${v.expected_kwh} kWh</div></div>
        <div class="stat"><div class="label">${t("Performance")}</div><div class="value num">${pct(v.performance)}</div></div>
        <div class="stat"><div class="label">${t("Haze cut sunlight")}</div><div class="value num">${pct(v.haze_loss)}</div></div>
        <div class="stat"><div class="label">${t("Panel loss")}</div><div class="value num">${v.code === "area" ? "–" : pct(v.panel_loss)}</div></div>
        <div class="stat"><div class="label">${t("Lost per week")}</div><div class="value num">${v.code === "area" ? "–" : inr(v.rupees_lost_per_week || 0)}</div></div>
      </div>`;
    }
    const total = d.curve.length ? d.curve[d.curve.length - 1].expected_cum_kwh : null;
    const air = v.pm25 != null ? t("Air: PM2.5 {pm} µg/m³, aerosol depth {aod}.", { pm: Math.round(v.pm25), aod: v.aod }) : "";
    const sky = v.sky && v.sky.sky_factor != null ? " " + t("Sunlight {n}% of a clear day.", { n: Math.round(v.sky.sky_factor * 100) }) : "";
    const should = t(d.is_today ? "Today a {kw} kW system here should make about {kwh} kWh in total." : "That day a {kw} kW system here should make about {kwh} kWh in total.",
      { kw: sys.kwp, kwh: "\u0000" }).split("\u0000");
    $("d-verdict").innerHTML = `
      ${badge}
      <h3 class="verdict-title">${esc(v.title)}</h3>
      <p>${esc(v.message)}</p>
      ${stats}
      <p class="hint">${esc(should[0])}<b>${total != null ? total.toFixed(1) : "–"}</b>${esc(should[1] || "")}${esc(sky)} ${esc(air)}</p>
      ${neighbourBlock(d.neighbours)}
      <div class="share-row"><button type="button" id="v-share" class="btn small ghost wa">${t("Share on WhatsApp")}</button></div>
      <div id="watch-ask"></div>`;
    if ($("nb-invite")) $("nb-invite").onclick = () => shareWhatsApp(t("I check my rooftop solar with SuryaWatch. It tells me whether a low day is smog, dust or a fault. Add your roof so we can compare our neighbourhood: {link}", { link: appLink("#watch") }));
    $("v-share").onclick = () => {
      const nice = niceDate(d.date, { weekday: "short", day: "numeric", month: "short" });
      const lines = [`SuryaWatch: ${sys.name}, ${nice}`, v.title, v.message];
      if (v.actual_kwh != null) lines.push(t("Made {made} kWh; the sunlight allowed about {kwh} kWh.", { made: v.actual_kwh, kwh: v.expected_kwh }));
      lines.push(appLink(`?system=${sys.system_id}&date=${d.date}#watch`));
      shareWhatsApp(lines.join("\n"));
    };
    helperBox($("watch-ask"), "watch", () => ({ date: d.date, system_kw: sys.kwp, result: v.title, explanation: v.message,
      made_kwh: v.actual_kwh, sunlight_allowed_kwh: v.expected_kwh, haze_loss: v.haze_loss, panel_loss: v.panel_loss,
      rupees_lost_per_week: v.rupees_lost_per_week, pm25: v.pm25, aerosol_optical_depth: v.aod }));
  }

  // ---- neighbourhood check: a count and a middle value from rooftops nearby, never one roof's figure
  const NB_TEXT = {
    area_wide: "Rooftops nearby were low too ({n} roofs within {km} km, middle value {median}). This dip is probably the sky (smog, dust or cloud), not your panels.",
    only_you: "Rooftops nearby did fine ({n} roofs within {km} km, middle value {median}) but yours did not. That points to your own panels: dust, new shade or a fault.",
    you_ok_area_low: "Your roof did better than its neighbours ({n} roofs within {km} km, middle value {median}).",
    all_ok: "Your roof did about as well as its neighbours ({n} roofs within {km} km, middle value {median}).",
    area_low: "Rooftops nearby were low on this day ({n} roofs within {km} km, middle value {median}).",
    area_ok: "Rooftops nearby did well on this day ({n} roofs within {km} km, middle value {median}).",
  };
  const HOUSES = "M3 20v-8l4-3 4 3v8M13 20v-6l4-3 4 3v6M2 20h20";
  function neighbourBlock(nb) {
    if (!nb) return "";
    const km = nb.radius_km;
    let text;
    if (nb.code === "too_few") {
      text = nb.nearby
        ? t("{n} SuryaWatch rooftop(s) within {km} km, but not enough evening readings from them for this day yet.", { n: nb.nearby, km })
        : t("No other SuryaWatch rooftops within {km} km yet. Invite your neighbours so you can compare.", { km });
    } else {
      text = t(NB_TEXT[nb.code] || NB_TEXT.all_ok, { n: nb.reporting, km, median: pct(nb.median) });
    }
    const cls = nb.code === "area_wide" ? " area" : nb.code === "only_you" ? " you" : "";
    return `<div class="nb-box${cls}">
      <div class="nb-head"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="${HOUSES}"/></svg>${t("Neighbourhood check")}</div>
      <p>${esc(text)}</p>
      ${nb.code === "too_few" ? `<button type="button" id="nb-invite" class="btn small ghost wa">${t("Invite neighbours on WhatsApp")}</button>` : ""}
      <p class="nb-privacy">${t("Only a count and a middle value are shared, never names, places or one roof's figure.")}</p></div>`;
  }

  // two-series chart: expected line (with wash) + measured dots, one y-axis
  function lineDotChart(el, o) {
    const W = Math.round(Math.max(300, el.clientWidth || 560)), H = 220, ml = 44, mr = 10, mt = 14, mb = 28;
    const iw = W - ml - mr, ih = H - mt - mb, x0 = 5, x1 = 20;
    const peak = Math.max(0.1, ...o.expected.map((p) => p.y), ...o.actual.map((p) => p.y));
    const step = niceStep(peak, 4), ymax = Math.ceil(peak / step) * step;
    const X = (h) => ml + ((h - x0) / (x1 - x0)) * iw, Y = (v) => mt + ih - (v / ymax) * ih;
    let svg = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(o.title)}">`;
    for (let v = 0; v <= ymax + 1e-9; v += step) {
      svg += `<line class="gridline" x1="${ml}" x2="${W - mr}" y1="${Y(v)}" y2="${Y(v)}"/><text class="axis-text" x="${ml - 8}" y="${Y(v) + 4}" text-anchor="end">${o.fmt(v)}</text>`;
    }
    for (let h = 6; h <= 20; h += 2) svg += `<text class="axis-text" x="${X(h)}" y="${H - 8}" text-anchor="middle">${hourLabel(h)}</text>`;
    const pts = o.expected.filter((p) => p.x >= x0 && p.x <= x1);
    if (pts.length > 1) {
      const line = pts.map((p, i) => `${i ? "L" : "M"}${X(p.x).toFixed(1)},${Y(p.y).toFixed(1)}`).join(" ");
      svg += `<path class="wash" d="${line} L${X(pts[pts.length - 1].x)},${Y(0)} L${X(pts[0].x)},${Y(0)} Z"/><path class="exp-line" d="${line}"/>`;
    }
    o.actual.forEach((p, i) => { svg += `<circle class="dot" data-i="${i}" cx="${X(p.x)}" cy="${Y(p.y)}" r="5"/>`; });
    svg += `<line class="cross" x1="0" x2="0" y1="${mt}" y2="${mt + ih}" visibility="hidden"/><rect class="hit" x="${ml}" y="${mt}" width="${iw}" height="${ih}"/></svg>`;
    el.innerHTML = `<p class="chart-title">${esc(o.title)}</p>
      <div class="legend"><span><i class="key-line"></i>${esc(o.expectedLabel)}</span><span><i class="key-dot"></i>${esc(o.actualLabel)}</span></div>
      <div class="chart">${svg}</div>`;
    const svgEl = el.querySelector("svg"), cross = el.querySelector(".cross"), hit = el.querySelector(".hit");
    const expAt = (h) => {
      for (let i = 1; i < pts.length; i++) if (pts[i].x >= h) { const a = pts[i - 1], b = pts[i]; return a.y + ((h - a.x) / (b.x - a.x)) * (b.y - a.y); }
      return null;
    };
    hit.addEventListener("mousemove", (ev) => {
      const r = svgEl.getBoundingClientRect(), px = ((ev.clientX - r.left) / r.width) * W;
      const h = x0 + ((px - ml) / iw) * (x1 - x0);
      cross.setAttribute("x1", px); cross.setAttribute("x2", px); cross.setAttribute("visibility", "visible");
      const near = o.actual.map((p, i) => ({ p, i, d: Math.abs(p.x - h) })).sort((a, b) => a.d - b.d)[0];
      const e = expAt(h);
      let html = `<b>${clock(localStamp(new Date(2000, 0, 1, Math.floor(h), Math.round((h % 1) * 60))))}</b>`;
      if (e != null) html += `<br>${esc(o.expectedLabel)}: ${o.fmt(e)} ${o.unit}`;
      if (near && near.d < 0.35) html += `<br>${esc(t("{what} at {time}", { what: o.actualLabel, time: clock(near.p.t) }))}: ${o.fmt(near.p.y)} ${o.unit}`;
      showTip(html, ev);
    });
    hit.addEventListener("mouseleave", () => { hideTip(); cross.setAttribute("visibility", "hidden"); });
  }

  function renderCharts(d) {
    const hrs = (t) => +t.slice(11, 13) + +t.slice(14, 16) / 60;
    const energy = d.readings.filter((r) => r.e_today_kwh != null).map((r) => ({ x: hrs(r.time), y: r.e_today_kwh, t: r.time }));
    const power = d.readings.filter((r) => r.power_kw != null).map((r) => ({ x: hrs(r.time), y: r.power_kw, t: r.time }));
    $("d-charts").innerHTML = '<div id="c-energy"></div><div id="c-power" style="margin-top:18px"></div>';
    lineDotChart($("c-energy"), {
      title: t("Energy made so far in the day (kWh)"), unit: "kWh", fmt: (v) => v.toFixed(1),
      expectedLabel: t("What the sunlight allowed"), actualLabel: t("Your E-Today readings"),
      expected: [{ x: 5, y: 0 }].concat(d.curve.map((c) => ({ x: hrs(c.time) || 24, y: c.expected_cum_kwh }))), actual: energy,
    });
    if (power.length) {
      lineDotChart($("c-power"), {
        title: t("Power at each reading (kW)"), unit: "kW", fmt: (v) => v.toFixed(2),
        expectedLabel: t("Expected power"), actualLabel: t("Your power readings"),
        expected: d.curve.map((c) => ({ x: hrs(c.time) - 0.5, y: c.expected_kw })), actual: power,
      });
    } else {
      $("c-power").innerHTML = `<p class="hint">${t('Add a photo of the "power now" screen to compare power through the day.')}</p>`;
    }
  }

  function renderReadings(d) {
    const box = $("d-readings");
    if (!d.readings.length) {
      box.innerHTML = `<p class="hint">${t("No readings for this day yet.")}</p>`;
    } else {
      const val = (x, u) => (x == null ? "–" : `${x} ${u}`);
      box.innerHTML = `<div class="table-wrap"><table class="rtable"><thead><tr><th>${t("Time")}</th><th>${t("Power")}</th><th>${t("Today")}</th><th>${t("Total")}</th><th>${t("State")}</th><th>${t("From")}</th><th></th></tr></thead><tbody>
        ${d.readings.map((r) => `<tr><td>${clock(r.time)}</td><td class="num">${val(r.power_kw, "kW")}</td><td class="num">${val(r.e_today_kwh, "kWh")}</td>
          <td class="num">${val(r.e_total_kwh, "kWh")}</td><td>${esc(r.state || "–")}</td><td>${t(r.source === "photo" ? "Photo" : "Typed")}</td>
          <td><button type="button" class="link-btn" data-del="${esc(r.time)}" aria-label="${esc(t("Delete reading at {time}", { time: clock(r.time) }))}">${t("Remove")}</button></td></tr>`).join("")}
      </tbody></table></div>`;
      box.querySelectorAll("[data-del]").forEach((b) => (b.onclick = async () => {
        await api(`/systems/${sys.system_id}/readings/delete`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ time: b.dataset.del }) });
        loadDay(viewDate);
      }));
    }
    const cleaned = d.events.filter((e) => e.type === "cleaned").map((e) => e.time);
    const last = cleaned[cleaned.length - 1];
    say($("d-events"), last ? "Last cleaned: {date} at {time}" : "", last && { date: niceDate(last, { day: "numeric", month: "short" }), time: clock(last) });
  }

  // ---- adding readings (photos are read by Amazon Bedrock on the server)
  async function exifTime(file) {
    try {
      const v = new DataView(await file.slice(0, 196608).arrayBuffer());
      if (v.getUint16(0) !== 0xffd8) return null;
      let off = 2;
      while (off < v.byteLength - 10) {
        const marker = v.getUint16(off), size = v.getUint16(off + 2);
        if (marker === 0xffe1 && v.getUint32(off + 4) === 0x45786966) {
          const tiff = off + 10, le = v.getUint16(tiff) === 0x4949;
          const u16 = (o) => v.getUint16(o, le), u32 = (o) => v.getUint32(o, le);
          const str = (o, n) => { let s = ""; for (let i = 0; i < n - 1; i++) s += String.fromCharCode(v.getUint8(o + i)); return s; };
          const ifd = (start) => { const t = {}, n = u16(start); for (let i = 0; i < n; i++) { const e = start + 2 + i * 12; t[u16(e)] = { count: u32(e + 4), at: e + 8 }; } return t; };
          const ifd0 = ifd(tiff + u32(tiff + 4));
          let dt = null;
          if (ifd0[0x8769]) { const sub = ifd(tiff + u32(ifd0[0x8769].at)); const t = sub[0x9003] || sub[0x9004]; if (t) dt = str(tiff + u32(t.at), t.count); }
          if (!dt && ifd0[0x0132]) dt = str(tiff + u32(ifd0[0x0132].at), ifd0[0x0132].count);
          const m = dt && dt.match(/(\d{4}):(\d{2}):(\d{2}) (\d{2}):(\d{2})/);
          return m ? `${m[1]}-${m[2]}-${m[3]}T${m[4]}:${m[5]}` : null;
        }
        if ((marker & 0xff00) !== 0xff00) break;
        off += 2 + size;
      }
    } catch (_) { /* unreadable EXIF: fall back */ }
    return null;
  }

  async function shrink(file) {
    const bmp = await createImageBitmap(file);
    const k = Math.min(1, 1600 / Math.max(bmp.width, bmp.height));
    const c = document.createElement("canvas");
    c.width = Math.round(bmp.width * k); c.height = Math.round(bmp.height * k);
    c.getContext("2d").drawImage(bmp, 0, 0, c.width, c.height);
    return c.toDataURL("image/jpeg", 0.85);
  }

  function renderReview() {
    const box = $("r-review");
    $("r-save").hidden = !review.length;
    $("r-save").textContent = review.length === 1 ? t("Save 1 reading") : t("Save {n} readings", { n: review.length });
    const note = (r) => (r.note || []).map((p) => (Array.isArray(p) ? t(p[0], p[1]) : t(p))).join(" ");
    box.innerHTML = review.map((r, i) => `
      <div class="rrow" data-i="${i}">
        ${r.thumb ? `<img src="${r.thumb}" alt="${esc(t("Inverter photo {n}", { n: i + 1 }))}">` : `<div class="nothumb">${t("Typed")}</div>`}
        <div class="rfields">
          <label>${t("Time")}<input type="datetime-local" data-k="time" value="${esc(r.time || "")}"></label>
          <label>${t("Power now (kW)")}<input type="number" step="0.01" min="0" data-k="power_kw" value="${r.power_kw ?? ""}" inputmode="decimal"></label>
          <label>${t("Today (kWh)")}<input type="number" step="0.1" min="0" data-k="e_today_kwh" value="${r.e_today_kwh ?? ""}" inputmode="decimal"></label>
          <label>${t("Total (kWh)")}<input type="number" step="1" min="0" data-k="e_total_kwh" value="${r.e_total_kwh ?? ""}" inputmode="decimal"></label>
          <label>${t("Inverter state")}<input type="text" maxlength="40" data-k="state" value="${esc(r.state ?? "")}" placeholder="Normal"></label>
          <p class="rnote ${r.status === "error" ? "error" : ""}">${esc(note(r))}</p>
        </div>
        <button type="button" class="link-btn" data-drop="${i}">${t("Discard")}</button>
      </div>`).join("");
    box.querySelectorAll("input[data-k]").forEach((inp) => (inp.oninput = () => {
      const i = +inp.closest(".rrow").dataset.i, k = inp.dataset.k;
      review[i][k] = k === "time" || k === "state" ? (inp.value || null) : inp.value === "" ? null : parseFloat(inp.value);
    }));
    box.querySelectorAll("[data-drop]").forEach((b) => (b.onclick = () => { review.splice(+b.dataset.drop, 1); renderReview(); }));
  }

  $("r-manual").onclick = () => {
    const time = viewDate === todayStr() ? localStamp(new Date()) : `${viewDate}T18:30`;
    review.push({ time, source: "manual", note: ["Type the numbers shown on the display."] });
    renderReview();
  };

  async function handleFiles(e) {
    const files = Array.from(e.target.files || []);
    e.target.value = "";
    $("r-error").hidden = true;
    for (const file of files) {
      const row = { source: "photo", note: ["Reading the display..."], status: "busy" };
      review.push(row);
      renderReview();
      try {
        const [time, dataUrl] = await Promise.all([exifTime(file), shrink(file)]);
        row.thumb = dataUrl;
        row.time = time || localStamp(new Date(file.lastModified || Date.now()));
        const timeNote = time ? [] : ["Photo time not found (WhatsApp copies lose it), so check the time."];
        renderReview();
        const r = await api(`/systems/${sys.system_id}/photo`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ image_base64: dataUrl }) });
        row.photo_key = r.photo_key;
        if (r.ai_available) {
          Object.assign(row, { power_kw: r.power_kw, e_today_kwh: r.e_today_kwh, e_total_kwh: r.e_total_kwh, state: r.state });
          row.note = [["Read by AI ({conf} confidence). Check the numbers before saving.", { conf: t(r.confidence || "medium") }]]
            .concat(r.notes ? [r.notes] : [], timeNote);
        } else {
          row.note = [r.message || "AI reading is not available here. Type the numbers."].concat(timeNote);
        }
        row.status = "ok";
      } catch (ex) {
        row.status = "error";
        row.note = [ex.message.includes("decode") || ex.name === "InvalidStateError"
          ? "This photo format can't be opened. Use JPG (set the phone camera to 'Most compatible')."
          : ex.message];
      }
      renderReview();
    }
  }
  $("r-files").onchange = handleFiles;
  $("r-camera").onchange = handleFiles;

  $("r-save").onclick = async () => {
    const err = $("r-error");
    err.hidden = true;
    const items = review.map((r) => ({ time: r.time, power_kw: r.power_kw ?? null, e_today_kwh: r.e_today_kwh ?? null,
      e_total_kwh: r.e_total_kwh ?? null, state: r.state || null, source: r.source, photo_key: r.photo_key }));
    const bad = items.find((r) => !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/.test(r.time || "") || (r.power_kw == null && r.e_today_kwh == null && r.e_total_kwh == null && !r.state));
    if (bad) { say(err, "Every reading needs a time and at least one value."); err.hidden = false; return; }
    $("r-save").disabled = true;
    try {
      await api(`/systems/${sys.system_id}/readings`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ readings: items }) });
      const day = items.map((r) => r.time.slice(0, 10)).sort().pop();
      review = []; renderReview();
      await loadDay(day);
      loadDust();
    } catch (ex) { say(err, ex.message); err.hidden = false; } finally { $("r-save").disabled = false; }
  };

  $("d-cleaned").onclick = async () => {
    const time = viewDate === todayStr() ? localStamp(new Date()) : `${viewDate}T08:00`;
    await api(`/systems/${sys.system_id}/events`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ type: "cleaned", time }) });
    loadDay(viewDate);
    loadDust();
  };

  const shiftDay = (n) => { const d = new Date(viewDate + "T12:00"); d.setDate(d.getDate() + n); return localStamp(d).slice(0, 10); };
  $("d-prev").onclick = () => loadDay(shiftDay(-1));
  $("d-next").onclick = () => { if (viewDate < todayStr()) loadDay(shiftDay(1)); };
  $("d-date").onchange = () => { if ($("d-date").value) loadDay($("d-date").value); };
  $("d-share").onclick = async () => {
    const link = `${location.origin}${location.pathname}?system=${sys.system_id}#watch`;
    try { await navigator.clipboard.writeText(link); $("d-share").textContent = t("Link copied"); } catch (_) { prompt(t("Copy this link"), link); }
    setTimeout(() => { $("d-share").textContent = t("Copy link"); }, 2000);
  };
  $("d-switch").onclick = () => { safeSet(STORE_KEY, null); sys = null; $("w-dash").hidden = true; $("w-setup").hidden = false; };

  // ------------------------------------------------------------------ helper (Amazon Bedrock, English or Hindi)
  const CHIPS = {
    plan: { en: ["What documents do I need?", "How does net metering work?", "Is my roof big enough?"],
            hi: ["कौन से कागज़ चाहिए?", "नेट मीटरिंग क्या है?", "सब्सिडी कब मिलेगी?"] },
    watch: { en: ["Why is my output low today?", "How do I clean panels safely?", "What does this result mean?"],
             hi: ["आज बिजली कम क्यों बनी?", "पैनल सुरक्षित तरीके से कैसे साफ़ करें?", "इस नतीजे का मतलब क्या है?"] },
  };
  let helperCount = 0;
  function helperBox(el, kind, getContext) {
    const n = ++helperCount;
    el.innerHTML = `<div class="ask">
      <div class="ask-head"><h3>${t("Ask SuryaWatch")}</h3>
        <div class="seg small" role="radiogroup" aria-label="${t("Answer language")}">
          <label><input type="radio" name="lang-${n}" value="en"${LANG === "en" ? " checked" : ""}> English</label>
          <label lang="hi"><input type="radio" name="lang-${n}" value="hi"${LANG === "hi" ? " checked" : ""}> हिंदी</label>
        </div></div>
      <div class="chips"></div>
      <div class="search-row"><input class="ask-q" type="text" maxlength="500" placeholder="${t("Type a question in English or Hindi")}" aria-label="${t("Your question")}">
        <button type="button" class="btn ask-go">${t("Ask")}</button></div>
      <div class="ask-a" aria-live="polite"></div></div>`;
    const lang = () => el.querySelector(`input[name="lang-${n}"]:checked`).value;
    const drawChips = () => {
      el.querySelector(".chips").innerHTML = CHIPS[kind][lang()].map((q) => `<button type="button" class="chip">${esc(q)}</button>`).join("");
      el.querySelectorAll(".chip").forEach((c) => (c.onclick = () => { el.querySelector(".ask-q").value = c.textContent; go(); }));
    };
    const go = async () => {
      const q = el.querySelector(".ask-q").value.trim();
      const out = el.querySelector(".ask-a");
      if (q.length < 3) { out.innerHTML = `<p class="hint">${t("Type a question first.")}</p>`; return; }
      out.innerHTML = `<p class="hint">${t("Thinking...")}</p>`;
      try {
        const r = await api("/ask", { method: "POST", headers: { "content-type": "application/json" },
          body: JSON.stringify({ question: q, lang: lang(), context: getContext() }) });
        out.innerHTML = r.answer
          ? `<div class="who">SuryaWatch${r.model && r.model !== "mock" ? " · Amazon Bedrock" : ""}</div><p>${esc(r.answer).replace(/\n+/g, "<br>")}</p>`
          : `<p class="hint">${esc(t(r.unavailable || "The helper is not available right now."))}</p>`;
      } catch (ex) { out.innerHTML = `<p class="error">${esc(ex.message)}</p>`; }
    };
    el.querySelectorAll(`input[name="lang-${n}"]`).forEach((r) => (r.onchange = drawChips));
    el.querySelector(".ask-go").onclick = go;
    el.querySelector(".ask-q").addEventListener("keydown", (e) => { if (e.key === "Enter") go(); });
    drawChips();
  }

  // ------------------------------------------------------------------ history heatmap (sequential green) + cleaning effect
  const HEAT = [
    { max: 0.7, color: "#d5eadb", label: "under 70%" },
    { max: 0.8, color: "#a6d1b3", label: "70–80%" },
    { max: 0.9, color: "#6db488", label: "80–90%" },
    { max: 1.0, color: "#3a8b5c", label: "90–100%" },
    { max: Infinity, color: "#1f5c39", label: "100%+" },
  ];
  const heatColor = (p) => HEAT.find((h) => p < h.max).color;
  const DOW = ["Mon", "", "Wed", "", "Fri", "", "Sun"];      // through t() when drawn

  function renderHistory(summary) {
    const byDate = {};
    (summary.verdicts || []).forEach((v) => { byDate[v.date] = v; });
    const today = new Date(todayStr() + "T12:00");
    const start = new Date(today); start.setDate(start.getDate() - 34);
    start.setDate(start.getDate() - ((start.getDay() + 6) % 7));        // back to Monday
    let cells = "";
    for (let d = new Date(start); d <= today || (d.getDay() + 6) % 7 !== 0; d.setDate(d.getDate() + 1)) {
      const key = localStamp(d).slice(0, 10);
      if (d > today) { cells += '<span class="cell future"></span>'; continue; }
      const v = byDate[key];
      const nice = d.toLocaleDateString(LOCALE(), { weekday: "short", day: "numeric", month: "short" });
      if (!v || v.performance_after_haze == null) {
        const none = `${nice}: ${t("no reading")}`;
        cells += `<button type="button" class="cell empty${key === viewDate ? " sel" : ""}" data-day="${key}" data-tip="${esc(none)}" aria-label="${esc(none)}"></button>`;
      } else {
        const label = t((STATUS[v.code] || STATUS.no_data).label);
        const tipText = `${nice}: ${t("{pct} of possible output", { pct: pct(v.performance_after_haze) })} · ${label}${v.final ? "" : " " + t("(part day)")}`;
        cells += `<button type="button" class="cell${v.code === "fault" ? " fault" : ""}${key === viewDate ? " sel" : ""}" style="background:${heatColor(v.performance_after_haze)}" data-day="${key}" data-tip="${esc(tipText)}" aria-label="${esc(tipText)}"></button>`;
      }
    }
    $("d-heat").innerHTML = `<div class="heat-wrap"><div class="heat-days">${DOW.map((d) => `<span>${d ? t(d) : ""}</span>`).join("")}</div><div class="heat">${cells}</div></div>
      <div class="heat-legend">${HEAT.map((h) => `<span><i style="background:${h.color}"></i>${t(h.label)}</span>`).join("")}<span><i style="box-shadow:inset 0 0 0 1px #c9cfc5"></i>${t("no reading")}</span></div>`;
    $("d-heat").querySelectorAll(".cell[data-day]").forEach((c) => {
      c.onmousemove = (ev) => showTip(esc(c.dataset.tip), ev);
      c.onmouseleave = hideTip;
      c.onclick = () => { hideTip(); loadDay(c.dataset.day); };
    });

    const c = summary.cleaning;
    const box = $("d-clean");
    if (!c) { box.innerHTML = `<p class="hint">${t('After you clean the panels, press "We cleaned the panels today" below. SuryaWatch will compare the days before and after.')}</p>`; return; }
    const when = t("{date} at {time}", { date: niceDate(c.cleaned_at, { day: "numeric", month: "short" }), time: clock(c.cleaned_at) });
    if (!c.ready) {
      box.innerHTML = `<div class="clean-box"><b>${esc(t("Cleaned on {when}.", { when }))}</b><p class="hint" style="margin-top:4px">${t("Waiting for full days of readings: {before} before and {after} after the cleaning so far. Add the evening reading on each day.", { before: c.days_before, after: c.days_after })}</p></div>`;
      return;
    }
    const w = (x) => Math.max(4, Math.min(100, x * 100));
    box.innerHTML = `<div class="clean-box">
      <div>${esc(t("Cleaning on {when} changed output by", { when }))}</div>
      <div class="big2 num">${c.gain_pct > 0 ? "+" : ""}${c.gain_pct}%</div>
      <div class="hint" style="margin-top:0">${t("about {kwh} kWh a day, worth {rs} a week", { kwh: c.kwh_per_day, rs: inr(c.rupees_per_week) })}</div>
      <div class="clean-bars">
        <span>${t("Before")}</span><div class="track"><div class="fill before" style="width:${w(c.before)}%"></div></div><span class="num">${pct(c.before)}</span>
        <span>${t("After")}</span><div class="track"><div class="fill" style="width:${w(c.after)}%"></div></div><span class="num">${pct(c.after)}</span>
      </div>
      <p class="hint">${t("Share of possible output after allowing for haze. Average of {before} day(s) before and {after} after.", { before: c.days_before, after: c.days_after })}</p></div>`;
  }

  const OUTLOOK = {
    clear: { label: "Clear sky", cls: "good", icon: "M12 5v2M12 17v2M5 12h2M17 12h2M7.8 7.8l1.4 1.4M14.8 14.8l1.4 1.4M7.8 16.2l1.4-1.4M14.8 9.2l1.4-1.4M12 9.5a2.5 2.5 0 1 0 0 5a2.5 2.5 0 1 0 0-5" },
    haze: { label: "Hazy", cls: "warn", icon: "M3 9h13M5 13h15M3 17h11" },
    smog_heavy: { label: "Heavy smog", cls: "serious", icon: "M3 8h16M5 12h15M3 16h16M6 20h10" },
    cloudy: { label: "Cloudy", cls: "none", icon: "M7 17h10a3.5 3.5 0 0 0 0-7a5 5 0 0 0-9.6 1.4A3 3 0 0 0 7 17z" },
    rain: { label: "Rain", cls: "none", icon: "M7 14h10a3.5 3.5 0 0 0 0-7a5 5 0 0 0-9.6 1.4A3 3 0 0 0 7 14zM9 17l-1 3M13 17l-1 3M17 17l-1 3" },
  };

  async function loadOutlook() {
    const box = $("d-outlook");
    try {
      const o = await api(`/systems/${sys.system_id}/outlook?lang=${LANG}`);
      box.hidden = false;
      box.innerHTML = `<h2>${t("Next two days")}</h2><p class="hint">${t("From the sunlight, cloud, rain and air-quality forecast for this roof.")}</p>
        <div class="outlook">${o.days.map((d, i) => {
          const st = OUTLOOK[d.code] || OUTLOOK.clear;
          const nice = niceDate(d.date, { weekday: "long", day: "numeric", month: "short" });
          const facts = [];
          if (d.sky_factor != null) facts.push(t("sunlight {n}% of a clear day", { n: Math.round(d.sky_factor * 100) }));
          if (d.haze_loss >= 0.02) facts.push(t("haze about {n}%", { n: Math.round(d.haze_loss * 100) }));
          if (d.pm25 != null) facts.push(`PM2.5 ${Math.round(d.pm25)}`);
          if ((d.rain_mm || 0) >= 0.5) facts.push(t("rain {mm} mm", { mm: Math.round(d.rain_mm) }) + (d.rain_prob_pct != null ? " " + t("({n}% chance)", { n: d.rain_prob_pct }) : ""));
          return `<div class="day">
            <div class="day-name">${t(i === 0 ? "Tomorrow" : "Day after")} · ${esc(nice)}</div>
            <span class="badge ${st.cls}"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="${st.icon}"/></svg>${t(st.label)}</span>
            <div class="day-kwh num">${d.likely_kwh} kWh</div>
            <div class="hint" style="margin-top:0">${t("expected from your {kw} kW system", { kw: sys.kwp })}</div>
            <p class="day-msg"><b>${esc(d.title)}${LANG === "hi" ? "।" : "."}</b> ${esc(d.message)}</p>
            <p class="hint">${esc(facts.join(" · "))}</p></div>`;
        }).join("")}</div>`;
    } catch (ex) {
      box.hidden = false;
      box.innerHTML = `<h2>${t("Next two days")}</h2><p class="hint">${esc(t("The forecast is not available right now ({why}).", { why: ex.message }))}</p>`;
    }
  }

  // ---- dust build-up and the best day to clean
  let dustData = null;
  const CAL_ICON = "M5 7h14v12H5zM5 11h14M9 4v4M15 4v4";
  const DUST_ADVICE = {
    clean_now: { cls: "serious", icon: STATUS.dust.icon, title: "Clean today or tomorrow morning",
                 msg: "Dust now costs more than a cleaning. Clean early in the morning or in the evening with plain water and a soft cloth." },
    clean_on: { cls: "good", icon: CAL_ICON, title: "Best day to clean: {date}", msg: "Until then, dust costs you less than a cleaning would." },
    wait_rain: { cls: "none", icon: OUTLOOK.rain.icon, title: "Wait for the rain on {date}",
                 msg: "About {mm} mm of rain is forecast. It will wash the panels for free, so save the water and the cost." },
    no_buildup: { cls: "good", icon: STATUS.healthy.icon, title: "No dust build-up seen yet",
                  msg: "Your panels are keeping their output between washes. Keep adding evening readings." },
    unknown_wash: { cls: "none", icon: CAL_ICON, title: "When were the panels last washed?",
                    msg: "Press \"We cleaned the panels today\" after the next cleaning to start the count. Rain is counted by itself." },
  };

  async function loadDust() {
    if (!sys) return;
    const box = $("d-dust");
    try {
      dustData = await api(`/systems/${sys.system_id}/dust`);
      renderDust(dustData);
    } catch (ex) {
      box.hidden = false;
      box.innerHTML = `<h2>${t("Dust and the best day to clean")}</h2><p class="hint">${esc(ex.message)}</p>`;
    }
  }

  function renderDust(d) {
    const box = $("d-dust"), a = d.advice, adv = DUST_ADVICE[a.code] || DUST_ADVICE.unknown_wash;
    const dayName = (x) => niceDate(x, { weekday: "long", day: "numeric", month: "short" });
    const vars = { date: a.date ? dayName(a.date) : "", mm: a.rain_mm };
    const stat = (label, value, sub) => `<div class="stat"><div class="label">${t(label)}</div><div class="value num">${value}</div>${sub ? `<div class="stat-sub">${esc(sub)}</div>` : ""}</div>`;
    const rateSub = d.rate_source === "learned"
      ? t(d.learned.confidence === "good" ? "learned from {n} days on your roof" : "rough estimate from {n} days on your roof", { n: d.learned.n })
      : t("typical value, until {n} more evening readings", { n: Math.max(1, d.points_needed) });
    const last = d.last_wash;
    box.hidden = false;
    box.innerHTML = `
      <h2>${t("Dust and the best day to clean")}</h2>
      <div class="dust-advice">
        <span class="badge ${adv.cls}"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="${adv.icon}"/></svg>${esc(t(adv.title, vars))}</span>
        <p>${esc(t(adv.msg, vars))}${a.code === "wait_rain" && a.rain_prob != null ? " " + esc(t("({n}% chance)", { n: a.rain_prob })) : ""}</p>
      </div>
      <div class="stats four">
        ${stat("Dust build-up", t("{n}% a day", { n: (d.rate * 100).toFixed(1) }), rateSub)}
        ${stat("Since the last wash", d.days_since != null ? t("{n} days", { n: d.days_since }) : "–",
          last ? t(last.kind === "rain" ? "rain, from {date}" : "cleaned, from {date}", { date: niceDate(last.date, { day: "numeric", month: "short" }) }) : t("not known yet"))}
        ${stat("Dust is costing you", d.rupees_day_now != null ? t("{rs} a day", { rs: inr(d.rupees_day_now) }) : "–",
          d.loss_now != null ? t("about {pct} of output", { pct: pct(d.loss_now) }) : "")}
        ${stat("Clean about every", d.best_interval_days ? t("{n} days", { n: d.best_interval_days }) : "–",
          t("when one cleaning costs {rs}", { rs: inr(d.clean_cost) }))}
      </div>
      <div id="dust-chart"></div>
      <div class="dust-cost">
        <label class="field" for="dust-cost">${t("Cost of one cleaning (₹)")}</label>
        <div class="search-row">
          <input id="dust-cost" type="number" min="0" max="5000" step="10" inputmode="numeric" value="${Math.round(d.clean_cost)}">
          <button type="button" id="dust-save" class="btn ghost">${t("Save")}</button>
        </div>
        <p class="hint" id="dust-msg">${t("A paid cleaner, or your own water and time. SuryaWatch weighs this against what dust costs you.")}</p>
      </div>
      <p class="hint">${esc(d.rate_source === "learned"
        ? t("Learned from {n} evening readings in {k} clean spell(s). A cleaning, or a day with 2 mm of rain or more, counts as a wash.", { n: d.learned.n, k: d.learned.spells })
        : t("Typical rate: 0.4% of output lost a day, measured on an IIT Bombay rooftop in the dry season. SuryaWatch switches to your roof's own rate once it has enough evening readings after a wash."))}</p>`;
    dustChart($("dust-chart"), d);
    $("dust-save").onclick = async () => {
      try {
        await api(`/systems/${sys.system_id}/settings`, { method: "POST", headers: { "content-type": "application/json" },
          body: JSON.stringify({ clean_cost: $("dust-cost").value }) });
        await loadDust();
        say($("dust-msg"), "Saved.");
      } catch (ex) { say($("dust-msg"), ex.message); }
    };
  }

  // performance after haze against days since a wash: your readings (dots) and the fitted dust trend (line)
  function dustChart(el, d) {
    if (!d.points.length || !d.line) { el.innerHTML = ""; return; }
    const W = Math.round(Math.max(300, el.clientWidth || 560)), H = 210, ml = 44, mr = 12, mt = 12, mb = 32;
    const iw = W - ml - mr, ih = H - mt - mb;
    const xmax = Math.max(7, d.line.x_max, ...d.points.map((p) => p.x)) + 1;     // a day of room on the right
    const lineY = (x) => d.line.y0 - d.line.rate * x;
    const ys = d.points.map((p) => p.y).concat(lineY(0), lineY(xmax));
    const lo = Math.max(0, Math.floor((Math.min(...ys) - 0.03) * 20) / 20), hi = Math.ceil((Math.max(...ys) + 0.02) * 20) / 20;
    const X = (x) => ml + (x / xmax) * iw, Y = (v) => mt + ih - ((v - lo) / (hi - lo)) * ih;
    const step = niceStep((hi - lo) * 100, 4) / 100;
    let svg = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(t("Output after haze against days since a wash"))}">`;
    for (let v = Math.ceil(lo / step) * step; v <= hi + 1e-9; v += step) {
      svg += `<line class="gridline" x1="${ml}" x2="${W - mr}" y1="${Y(v)}" y2="${Y(v)}"/><text class="axis-text" x="${ml - 8}" y="${Y(v) + 4}" text-anchor="end">${Math.round(v * 100)}%</text>`;
    }
    const xs = niceStep(xmax, 6);
    for (let x = 0; x <= xmax + 1e-9; x += xs) svg += `<text class="axis-text" x="${X(x)}" y="${H - 12}" text-anchor="middle">${x}</text>`;
    svg += `<path class="exp-line" d="M${X(0)},${Y(lineY(0))} L${X(xmax)},${Y(lineY(xmax))}"/>`;
    d.points.forEach((p, i) => { svg += `<circle class="dot" data-i="${i}" cx="${X(p.x)}" cy="${Y(p.y)}" r="5"/>`; });
    svg += "</svg>";
    el.innerHTML = `<p class="chart-title">${t("Output after haze against days since a wash")}</p>
      <div class="legend"><span><i class="key-line"></i>${t("Your roof's dust trend")}</span><span><i class="key-dot"></i>${t("Each evening reading")}</span></div>
      <div class="chart">${svg}</div><p class="axis-note">${t("Days since the panels were washed")}</p>`;
    el.querySelectorAll(".dot").forEach((c) => {
      const p = d.points[+c.dataset.i];
      const html = `<b>${esc(niceDate(p.date, { weekday: "short", day: "numeric", month: "short" }))}</b><br>${esc(t("{n} days after a wash: {pct} of possible output", { n: p.x, pct: pct(p.y) }))}`;
      c.addEventListener("mousemove", (ev) => showTip(html, ev));
      c.addEventListener("click", (ev) => showTip(html, ev));
      c.addEventListener("mouseleave", hideTip);
    });
  }

  function renderPromise(p) {
    const box = $("d-promise");
    if (!p) { box.hidden = true; return; }
    box.hidden = false;
    const units = n0(p.promise_kwh_year);
    const src = p.source === "installer" ? t("your installer's promise of {n} units a year", { n: units })
      : p.source === "plan" ? t("your SuryaWatch plan: {n} units a year", { n: units })
      : t("SuryaWatch's estimate for this roof: {n} units a year", { n: units });
    let html = `<h2>${t("Promised vs got")}</h2><p class="hint">${esc(t("Checked against {src}.", { src }))}</p>`;
    if (!p.ready) {
      box.innerHTML = html + `<p class="hint">${t("Add two photos of the Total (E-Total) screen taken a day or more apart, and SuryaWatch will compare what you got with what was promised.")}</p>`;
      return;
    }
    const nice = (ts) => niceDate(ts, { day: "numeric", month: "short" });
    const block = (title, q) => {
      const top = Math.max(q.promised_kwh, q.actual_kwh, 0.1);
      const pctv = Math.round(q.ratio * 100);
      const verdict = q.ratio >= 1.05 ? t("Ahead of the promise: {pct}%.", { pct: pctv })
        : q.ratio >= 0.95 ? t("On track: {pct}% of the promise.", { pct: pctv })
        : t("Behind by {n} units (about {rs}): {pct}% of the promise.", { n: n0(q.gap_kwh), rs: inr(q.gap_rupees), pct: pctv });
      return `<div class="promise-block"><div class="promise-title">${esc(t(title))} <span class="hint">(${esc(t("{from} to {to}", { from: nice(q.first_day || q.from), to: nice(q.to) }))})</span></div>
        <div class="clean-bars">
          <span>${t("Promised")}</span><div class="track"><div class="fill before" style="width:${(q.promised_kwh / top) * 100}%"></div></div><span class="num">${n0(q.promised_kwh)}</span>
          <span>${t("Got")}</span><div class="track"><div class="fill" style="width:${(q.actual_kwh / top) * 100}%"></div></div><span class="num">${n0(q.actual_kwh)}</span>
        </div><p class="promise-verdict ${q.ratio < 0.95 ? "behind" : ""}">${esc(verdict)}</p></div>`;
    };
    if (p.month) html += block("This month so far", p.month);
    if (p.all && (!p.month || p.all.from !== p.month.from)) html += block(p.method === "daily" ? "Days with a final reading" : "Since tracking began", p.all);
    html += `<p class="hint">${t(p.method === "e_total" ? "Uses the inverter's Total counter, so days without a photo still count." : "Add Total (E-Total) photos for a more complete count.")} ${t("Units are kWh.")}</p>`;
    box.innerHTML = html;
  }

  async function refreshSummary() {
    if (!sys) return;
    try {
      const s = await api("/systems/" + sys.system_id);
      sys = { ...sys, ...s };
      renderHistory(s);
      renderPromise(s.promise);
      if (s.alert_emails && !$("a-msg").textContent) say($("a-msg"), "{n} email address(es) get alerts for this system.", { n: s.alert_emails });
    } catch (_) { /* history is optional */ }
  }

  // ------------------------------------------------------------------ alerts (Amazon SNS)
  $("a-save").onclick = async () => {
    const msg = $("a-msg");
    try {
      const r = await api(`/systems/${sys.system_id}/alerts`, { method: "POST", headers: { "content-type": "application/json" },
        body: JSON.stringify({ email: $("a-email").value }) });
      say(msg, r.message);
    } catch (ex) { say(msg, ex.message); }
  };
  $("a-test").onclick = async () => {
    const msg = $("a-msg");
    say(msg, "Running today's check...");
    try {
      const r = await api(`/systems/${sys.system_id}/alerts/test`, { method: "POST", headers: { "content-type": "application/json" }, body: "{}" });
      if (r.sent) say(msg, "Today's check ({what}) was {how}.", { what: t((STATUS[r.code] || {}).label || r.code), how: t(r.sent) });
      else say(msg, "Nothing to report today.");
    } catch (ex) { say(msg, ex.message); }
  };

  function initWatch() {
    const qs = new URLSearchParams(location.search);
    const fromUrl = qs.get("system");
    const day = qs.get("date");
    if (day && /^\d{4}-\d{2}-\d{2}$/.test(day) && day <= todayStr()) viewDate = day;
    if (fromUrl) safeSet(STORE_KEY, fromUrl);
    const id = fromUrl || safeGet(STORE_KEY);
    if (id && API) sysReady = openSystem(id);
    else $("w-setup").hidden = false;
  }

  // ------------------------------------------------------------------ public impact page
  let impactData = null;
  let impactDemo = new URLSearchParams(location.search).get("demo") === "1";
  const co2Text = (kg) => (kg >= 1000 ? t("{n} t", { n: (kg / 1000).toFixed(1) }) : t("{n} kg", { n: n0(kg) }));
  const units1 = (x) => (x >= 100 ? n0(x) : (Math.round(x * 10) / 10).toLocaleString("en-IN"));

  async function loadImpact() {
    const box = $("impact-body");
    if (!impactData) box.innerHTML = `<p class="hint">${t("Loading...")}</p>`;
    try {
      impactData = await api("/impact" + (impactDemo ? "?demo=1" : ""));
      renderImpact(impactData);
    } catch (ex) {
      box.innerHTML = `<p class="error">${esc(ex.message)}</p>`;
    }
  }

  function tile(label, value, cls) {
    return `<div class="stat"><div class="label">${t(label)}</div><div class="value num${cls ? " " + cls : ""}">${value}</div></div>`;
  }

  function renderImpact(d) {
    const w = d.watch, p = d.plan;
    const finding = (code, n, text) => {            // text: [plural, singular]
      const st = STATUS[code];
      return `<li class="finding"><span class="badge ${st.cls}"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="${st.icon}"/></svg>${t(st.label)}</span>
        <span class="finding-n num">${n0(n)}</span><span class="finding-text">${esc(t(text[n === 1 ? 1 : 0]))}</span></li>`;
    };
    const demoRow = d.demo_systems ? `<label class="demo-toggle"><input type="checkbox" id="imp-demo"${impactDemo ? " checked" : ""}> ${t("Include the sample rooftop (made-up readings)")}</label>` : "";
    const demoNote = d.includes_demo ? `<p class="note warn-note">${t("These totals include the sample rooftop. Its readings are made up for the demo, not measured.")}</p>` : "";
    const nothing = !w.rooftops && !p.roofs;
    const updated = new Date(d.updated).toLocaleString(LOCALE(), { day: "numeric", month: "short", hour: "numeric", minute: "2-digit" });

    $("impact-body").innerHTML = `
      ${demoNote}
      ${nothing ? `<div class="card"><p>${t("No rooftops yet. Plan a roof or start watching one, and the totals appear here.")}</p></div>` : ""}
      <section class="card">
        <h2>${t("Rooftops SuryaWatch watches")}</h2>
        <div class="stats">
          ${tile("Rooftops watched", n0(w.rooftops))}
          ${tile("Solar capacity", `${units1(w.kw)} kW`)}
          ${tile("Units made while watched", `${units1(w.units)} kWh`, "good")}
          ${tile("CO₂ avoided", co2Text(w.co2_kg), "good")}
          ${tile("Worth to the owners", inr(w.rupees))}
          ${tile("Days checked", n0(w.days_checked))}
        </div>
        <p class="hint">${t("Units are counted from inverter photos. CO₂ uses {f} kg per unit, India's grid average (CEA).", { f: d.co2_kg_per_kwh })}</p>
      </section>

      <div class="dash-grid">
        <section class="card">
          <h2>${t("What the daily checks found")}</h2>
          <ul class="findings">
            ${finding("smog", w.smog_days, ["days when low output was smog, not dirty panels, so nobody washed them for nothing",
                                             "day when low output was smog, not dirty panels, so nobody washed them for nothing"])}
            ${finding("dust", w.dust_days, ["days the panels needed cleaning", "day the panels needed cleaning"])}
            ${w.area_days ? finding("area", w.area_days, ["days when every roof nearby dipped together, so nobody blamed their own panels",
                                                        "day when every roof nearby dipped together, so nobody blamed their own panels"]) : ""}
            ${finding("fault", w.fault_days, ["days with a sudden drop or an inverter error", "day with a sudden drop or an inverter error"])}
            ${finding("healthy", w.healthy_days, ["days the panels made what the sunlight allowed", "day the panels made what the sunlight allowed"])}
          </ul>
          <p class="hint">${esc(t(w.recovered_kwh_day > 0
            ? "Cleanings logged: {n}. The latest ones brought back about {kwh} kWh a day."
            : "Cleanings logged: {n}.", { n: n0(w.cleanings), kwh: w.recovered_kwh_day }))}
            ${esc(t("Rooftops with evening email alerts: {n}.", { n: n0(w.with_alerts) }))}</p>
        </section>
        <section class="card">
          <h2>${t("Every rooftop, day by day")}</h2>
          <p class="hint">${t("Each square is one day: the average share of possible output, after allowing for haze, across the rooftops checked that day.")}</p>
          <div id="imp-heat"></div>
        </section>
      </div>

      <section class="card" id="imp-units"></section>

      <section class="card">
        <h2>${t("Roofs planned")}</h2>
        <div class="stats">
          ${tile("Roofs planned", n0(p.roofs))}
          ${tile("Solar they could fit", `${units1(p.kw)} kW`)}
          ${tile("Units a year", n0(p.units_year), "good")}
          ${tile("CO₂ they could avoid", t("{n} t/yr", { n: p.co2_tonnes_year }), "good")}
          ${tile("Subsidy they qualify for", lakh(p.subsidy))}
        </div>
        <p class="hint">${t("Each roof counts once, however many times it was planned.")}</p>
      </section>

      <details class="card how"><summary>${t("How we count")}</summary><ul>
        <li>${t("Units made: the rise of the inverter's Total counter between the first and last photo, or the sum of each evening's E-Today reading, whichever is larger.")}</li>
        <li>${t("Worth: each owner's value of one unit (bill saving plus incentive).")}</li>
        <li>${t("Smog, dust and fault days come from the evening check: expected output from the sun's position, forecast sunlight and the haze in the air, compared with what the panels made.")}</li>
        <li>${t("Demo data is left out unless you include it. Totals refresh about once a minute.")}</li>
      </ul></details>

      <div class="share-row impact-foot">
        <button type="button" id="imp-share" class="btn small ghost wa">${t("Share on WhatsApp")}</button>
        ${demoRow}
        <span class="hint">${esc(t("Updated {when}", { when: updated }))}</span>
      </div>`;

    const firstMonday = d.calendar.findIndex((c) => new Date(c.date + "T12:00").getDay() === 1);
    const cal = d.calendar.slice(Math.max(0, firstMonday));     // whole weeks, so the grid starts on Monday
    renderImpactHeat(cal);
    const days = cal.map((c) => ({ label: niceDate(c.date, { day: "numeric", month: "short" }), value: c.units, c }));
    if (days.some((x) => x.value > 0)) {
      barChart($("imp-units"), days, {
        title: t("Units made each day, all rooftops (kWh)"), labelEvery: 7,
        tip: (x) => `<b>${esc(x.label)}</b><br>${t("{n} kWh from {r} rooftop(s)", { n: x.value, r: x.c.rooftops })}`,
      });
    } else {
      $("imp-units").innerHTML = `<p class="chart-title">${t("Units made each day, all rooftops (kWh)")}</p><p class="hint">${t("No finished days in the last few weeks yet.")}</p>`;
    }
    if ($("imp-demo")) $("imp-demo").onchange = (e) => { impactDemo = e.target.checked; loadImpact(); };
    $("imp-share").onclick = () => shareWhatsApp([
      t("SuryaWatch so far"),
      t("{n} rooftops ({kw} kW) watched: {units} units tracked, {co2} of CO₂ avoided", { n: w.rooftops, kw: units1(w.kw), units: units1(w.units), co2: co2Text(w.co2_kg) }),
      t("{smog} smog days explained, {dust} dust warnings, {fault} possible faults caught", { smog: w.smog_days, dust: w.dust_days, fault: w.fault_days }),
      t("{n} roofs planned: {kw} kW that could make {units} units a year", { n: p.roofs, kw: units1(p.kw), units: n0(p.units_year) }),
      d.includes_demo ? t("(includes made-up sample data)") : "",
      t("See it live: {link}", { link: appLink("#impact") }),
    ].filter(Boolean).join("\n"));
  }

  function renderImpactHeat(cal) {
    const first = new Date(cal[0].date + "T12:00");
    const lead = (first.getDay() + 6) % 7;                     // empty slots before the first day (week starts Monday)
    let cells = '<span class="cell future"></span>'.repeat(lead);
    cal.forEach((c) => {
      const nice = niceDate(c.date, { weekday: "short", day: "numeric", month: "short" });
      if (c.performance == null) {
        const none = `${nice}: ${t("no reading")}`;
        cells += `<span class="cell empty static" role="img" tabindex="0" data-tip="${esc(none)}" aria-label="${esc(none)}"></span>`;
        return;
      }
      let tipText = `${nice}: ${t("{pct} of possible output on average", { pct: pct(c.performance) })} · ${t("{n} kWh from {r} rooftop(s)", { n: c.units, r: c.rooftops })}`;
      if (c.smog) tipText += ` · ${t("smog at {n} rooftop(s)", { n: c.smog })}`;
      cells += `<span class="cell static" role="img" tabindex="0" style="background:${heatColor(c.performance)}" data-tip="${esc(tipText)}" aria-label="${esc(tipText)}"></span>`;
    });
    $("imp-heat").innerHTML = `<div class="heat-wrap"><div class="heat-days">${DOW.map((x) => `<span>${x ? t(x) : ""}</span>`).join("")}</div><div class="heat">${cells}</div></div>
      <div class="heat-legend">${HEAT.map((h) => `<span><i style="background:${h.color}"></i>${t(h.label)}</span>`).join("")}<span><i style="box-shadow:inset 0 0 0 1px #c9cfc5"></i>${t("no reading")}</span></div>`;
    $("imp-heat").querySelectorAll(".cell[data-tip]").forEach((c) => {
      c.onmousemove = (ev) => showTip(esc(c.dataset.tip), ev);
      c.onclick = (ev) => showTip(esc(c.dataset.tip), ev);
      c.onmouseleave = hideTip;
      c.onblur = hideTip;
    });
  }

  // ------------------------------------------------------------------ installer report (print or save as PDF)
  let reportData = null;
  const DATE_OK = (x) => /^\d{4}-\d{2}-\d{2}$/.test(x || "");
  const ymd = (d) => localStamp(d).slice(0, 10);
  const longDate = (x) => niceDate(x, { day: "numeric", month: "short", year: "numeric" });

  function presetRange(p) {
    const now = new Date(todayStr() + "T12:00");
    if (p === "7" || p === "30") { const f = new Date(now); f.setDate(f.getDate() - (+p - 1)); return [ymd(f), ymd(now)]; }
    if (p === "month") return [todayStr().slice(0, 8) + "01", todayStr()];
    if (p === "prev") return [ymd(new Date(now.getFullYear(), now.getMonth() - 1, 1, 12)), ymd(new Date(now.getFullYear(), now.getMonth(), 0, 12))];
    return [$("rep-from").value, $("rep-to").value];
  }
  function initReportPeriod() {
    const qs = new URLSearchParams(location.search);
    const [a, b] = DATE_OK(qs.get("from")) && DATE_OK(qs.get("to")) ? [qs.get("from"), qs.get("to")] : presetRange("30");
    if (qs.get("from")) $("rep-preset").value = "custom";
    $("rep-from").value = a; $("rep-to").value = b;
    $("rep-from").max = $("rep-to").max = todayStr();
  }
  $("rep-preset").onchange = () => {
    if ($("rep-preset").value === "custom") return;
    const [a, b] = presetRange($("rep-preset").value);
    $("rep-from").value = a; $("rep-to").value = b;
    loadReport();
  };
  $("rep-from").onchange = $("rep-to").onchange = () => { $("rep-preset").value = "custom"; loadReport(); };
  $("rep-back").onclick = () => { location.hash = "watch"; };
  $("d-report").onclick = () => { location.hash = "report"; };
  $("rep-print").onclick = () => window.print();
  const reportLink = (r) => appLink(`?system=${r.system.system_id}&from=${r.from}&to=${r.to}#report`);
  $("rep-share").onclick = () => {
    if (!reportData) return;
    const r = reportData, m = r.summary;
    shareWhatsApp([
      t("SuryaWatch report: {name}, {from} to {to}", { name: sysName(r.system), from: longDate(r.from), to: longDate(r.to) }),
      m.performance_after_haze != null ? t("Performance after haze: {pct}. Units made: {kwh} kWh.", { pct: pct(m.performance_after_haze), kwh: m.made_kwh }) : "",
      r.actions.map((a) => "• " + actionText(a)).join("\n"),
      t("Full report: {link}", { link: reportLink(r) }),
    ].filter(Boolean).join("\n"));
  };

  const ACTIONS = {
    fault: "The inverter showed an error, or output dropped suddenly, on {n} day(s). Please inspect the inverter and the messages listed below.",
    check: "Output was low on {n} day(s) although the panels had been cleaned or rained on. Please check for new shade, loose DC connectors or a failed string.",
    behind: "Since tracking began the system has made {pct}% of the promised units ({units} units short). Please explain the gap or inspect the system.",
    low_after_clean: "Even with cleaning, the panels gave only {pct}% of possible output in this period. Please check the panels and wiring.",
    dust: "Dust cut output on {n} day(s). Cleaning is the owner's job; no visit is needed for this.",
    ok: "No problems found. The system made what the sunlight allowed.",
  };
  const actionText = (a) => t(ACTIONS[a.code] || a.code, a);

  async function loadReport() {
    const doc = $("report-doc");
    if (!sys && sysReady) await sysReady;
    if (!sys) { doc.innerHTML = `<p class="hint">${t("Open your rooftop on the Watch tab first, then come back to make its report.")}</p>`; return; }
    const from = $("rep-from").value, to = $("rep-to").value;
    if (!DATE_OK(from) || !DATE_OK(to)) return;
    doc.innerHTML = `<p class="hint">${t("Preparing the report...")}</p>`;
    try {
      reportData = await api(`/systems/${sys.system_id}/report?from=${from}&to=${to}&lang=${LANG}`);
      renderReport(reportData);
    } catch (ex) {
      doc.innerHTML = `<p class="error">${esc(ex.message)}</p>`;
    }
  }

  function renderReport(r) {
    const s = r.system, m = r.summary, kwh = (x) => (x == null ? "–" : (+x).toFixed(1));
    const facing = FACING[Math.round(s.facing)];
    const result = (d) => (d.code ? t((STATUS[d.code] || STATUS.no_data).label) + (d.final === false && d.code !== "fault" ? " " + t("(part day)") : "") : t("Not checked"));
    const promiseText = s.promise_kwh_year
      ? t(s.promise_source === "plan" ? "SuryaWatch plan: {n} units a year" : "Installer: {n} units a year", { n: n0(s.promise_kwh_year) })
      : t("None given (SuryaWatch's estimate is used)");
    const p = r.promise;
    const promiseRows = p && p.ready ? [["This month so far", p.month], [p.method === "daily" ? "Days with a final reading" : "Since tracking began", p.all]]
      .filter(([, q]) => q).map(([label, q]) => `<tr><td>${esc(t(label))} <span class="hint">(${esc(t("{from} to {to}", { from: niceDate(q.first_day || q.from, { day: "numeric", month: "short" }), to: niceDate(q.to, { day: "numeric", month: "short" }) }))})</span></td>
        <td class="num">${n0(q.promised_kwh)}</td><td class="num">${n0(q.actual_kwh)}</td><td class="num">${q.ratio != null ? Math.round(q.ratio * 100) + "%" : "–"}</td></tr>`).join("") : "";
    const c = r.counter;
    const eff = r.cleaning_effect;
    const effText = eff && eff.ready
      ? t("Cleaning on {when} changed output from {before} to {after} of possible ({gain}).", { when: longDate(eff.cleaned_at), before: pct(eff.before), after: pct(eff.after), gain: `${eff.gain_pct > 0 ? "+" : ""}${eff.gain_pct}%` })
      : "";

    $("report-doc").innerHTML = `
      <header class="rep-head">
        <div>
          <p class="rep-brand">SuryaWatch</p>
          <h1>${t("Rooftop solar report")}</h1>
          <p class="rep-sub">${esc(sysName(s))} · ${esc(t("{from} to {to}", { from: longDate(r.from), to: longDate(r.to) }))}</p>
        </div>
        <div class="rep-meta">${esc(t("Made on {date}", { date: longDate(r.made_on) }))}<br>${esc(t("System ID {id}", { id: s.system_id }))}</div>
      </header>

      <section class="rep-sec">
        <h2>${t("The system")}</h2>
        <table class="rep-kv">
          <tr><th>${t("Size")}</th><td>${s.kwp} kW</td><th>${t("Panels face")}</th><td>${esc(t("{facing}, {tilt}° tilt", { facing: facing ? t(facing) : `${s.facing}°`, tilt: s.tilt }))}</td></tr>
          <tr><th>${t("Location")}</th><td>${(+s.lat).toFixed(4)}, ${(+s.lon).toFixed(4)}</td><th>${t("Watched since")}</th><td>${s.created ? longDate(s.created) : "–"}</td></tr>
          <tr><th>${t("Promise")}</th><td>${esc(promiseText)}</td><th>${t("Value of one unit")}</th><td>₹${s.unit_value}</td></tr>
        </table>
      </section>

      <section class="rep-sec">
        <h2>${t("Summary")}</h2>
        <div class="stats rep-stats">
          ${tile("Days with readings", t("{n} ({full} full days)", { n: m.days_with_readings, full: m.full_days }))}
          ${tile("Units made", `${kwh(m.made_kwh)} kWh`)}
          ${tile("Sunlight allowed, after haze", `${kwh(m.allowed_after_haze_kwh)} kWh`)}
          ${tile("Performance after haze", pct(m.performance_after_haze))}
          ${tile("Lost to dust or faults", `${kwh(m.lost_kwh)} kWh · ${inr(m.lost_rupees)}`)}
          ${tile("Lost to the sky (smog, haze, area-wide dips)", `${kwh(m.haze_kwh)} kWh`)}
        </div>
        <p class="hint">${t("A healthy system gives {pct} or more of the output the sunlight allows, after haze.", { pct: pct(r.healthy_at) })}
          ${m.unchecked_days ? esc(t("{n} day(s) could not be checked because a weather service did not answer. Open the report again later.", { n: m.unchecked_days })) : ""}</p>
      </section>

      <section class="rep-sec">
        <h2>${t("What needs attention")}</h2>
        ${r.actions.length ? `<ol class="rep-actions">${r.actions.map((a) => `<li>${esc(actionText(a))}</li>`).join("")}</ol>` : `<p class="hint">${t("No full days in this period yet.")}</p>`}
      </section>

      <section class="rep-sec rep-two">
        <div>
          <h3>${t("Promised vs got")}</h3>
          ${promiseRows ? `<table class="rep-table"><thead><tr><th>${t("Period")}</th><th class="num">${t("Promised")}</th><th class="num">${t("Got")}</th><th class="num">${t("Share")}</th></tr></thead><tbody>${promiseRows}</tbody></table>
            <p class="hint">${t("Units are kWh.")}</p>` : `<p class="hint">${t("Not enough readings yet. Photos of the Total (E-Total) screen taken a day or more apart are needed.")}</p>`}
        </div>
        <div>
          <h3>${t("Inverter Total counter")}</h3>
          ${c ? `<p>${esc(t("{a} kWh on {d1} to {b} kWh on {d2}: {units} kWh in between.", { a: n0(c.from_kwh), d1: `${niceDate(c.from_time, { day: "numeric", month: "short" })}, ${clock(c.from_time)}`, b: n0(c.to_kwh), d2: `${niceDate(c.to_time, { day: "numeric", month: "short" })}, ${clock(c.to_time)}`, units: c.units }))}</p>`
            : `<p class="hint">${t("Needs two photos of the Total (E-Total) screen in this period.")}</p>`}
        </div>
      </section>

      <section class="rep-sec">
        <h2>${t("Inverter faults and messages")}</h2>
        ${r.faults.length ? `<table class="rep-table"><thead><tr><th>${t("When")}</th><th>${t("The display showed")}</th></tr></thead><tbody>
          ${r.faults.map((f) => `<tr><td>${esc(niceDate(f.time, { weekday: "short", day: "numeric", month: "short" }))}, ${clock(f.time)}</td><td><b>${esc(f.state)}</b></td></tr>`).join("")}</tbody></table>`
          : `<p class="hint">${t("No fault messages on the photos in this period.")}</p>`}
      </section>

      <section class="rep-sec">
        <h2>${t("Cleanings")}</h2>
        ${r.cleanings.length ? `<p>${esc(r.cleanings.map((x) => `${longDate(x)}, ${clock(x)}`).join(" · "))}</p>` : `<p class="hint">${t("No cleanings logged in this period.")}</p>`}
        ${effText ? `<p>${esc(effText)}</p>` : ""}
      </section>

      <section class="rep-sec rep-days">
        <h2>${t("Day by day")}</h2>
        <div id="rep-chart"></div>
        ${r.days.length ? `<table class="rep-table"><thead><tr><th>${t("Date")}</th><th class="num">${t("Made (kWh)")}</th><th class="num">${t("Sunlight allowed (kWh)")}</th>
          <th class="num">${t("Haze")}</th><th class="num">${t("Performance after haze")}</th><th>${t("Result")}</th></tr></thead><tbody>
          ${r.days.map((d) => `<tr><td>${esc(niceDate(d.date, { weekday: "short", day: "numeric", month: "short" }))}</td><td class="num">${kwh(d.actual_kwh)}</td>
            <td class="num">${kwh(d.expected_kwh)}</td><td class="num">${pct(d.haze_loss)}</td><td class="num">${pct(d.performance_after_haze)}</td><td>${esc(result(d))}</td></tr>`).join("")}
          </tbody></table>` : `<p class="hint">${t("No readings in this period.")}</p>`}
      </section>

      <section class="rep-sec rep-method">
        <h2>${t("How this report was made")}</h2>
        <ul>
          <li>${t("Readings come from photos of the inverter display, read by AI and checked by the owner, or typed in.")}</li>
          <li>${t("Expected output uses the sun's position over this roof, measured sunlight from Open-Meteo, and the system's size, tilt and direction.")}</li>
          <li>${t("Haze comes from the air-quality data (aerosol optical depth). Output lost to haze is not counted against the panels.")}</li>
          <li>${t("Each day is judged on its evening E-Today reading; a part day had no evening reading.")}</li>
          <li>${t("These are estimates to guide a check-up. A site visit is the final word.")}</li>
        </ul>
      </section>
      <footer class="rep-foot">${esc(t("Made with SuryaWatch. Open this report online: {link}", { link: reportLink(r) }))}</footer>`;

    const full = r.days.filter((d) => d.final && d.performance_after_haze != null);
    if (full.length) {
      barChart($("rep-chart"), full.map((d) => ({ label: niceDate(d.date, { day: "numeric", month: "short" }), value: Math.round(d.performance_after_haze * 100), d })), {
        title: t("Share of possible output each full day, after haze (%)"),
        ref: Math.round(r.healthy_at * 100), refLabel: t("Healthy: {pct}", { pct: pct(r.healthy_at) }),
        fmtTick: (v) => `${v}%`, labelEvery: Math.max(1, Math.ceil(full.length / 10)),
        tip: (x) => `<b>${esc(x.label)}</b><br>${x.value}% · ${esc(result(x.d))}`,
      });
    }
  }

  // ------------------------------------------------------------------ English | हिंदी switch
  const ORIG_TEXT = new WeakMap(), ORIG_ATTR = new WeakMap(), ATTRS = ["placeholder", "aria-label", "title"];
  const REV = Object.fromEntries(Object.entries(HI).filter(([k]) => !k.includes("{")).map(([k, v]) => [v, k]));
  function applyStatic() {           // fixed page text: translate text nodes and labels in place
    document.documentElement.lang = LANG;
    const walk = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT, {
      acceptNode: (n) => (n.parentElement.closest("[data-dyn],script,style") ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT) });
    for (let n = walk.nextNode(); n; n = walk.nextNode()) {
      if (!ORIG_TEXT.has(n)) {
        const k = n.nodeValue.trim();
        if (k in HI) ORIG_TEXT.set(n, n.nodeValue);
        else if (k in REV) ORIG_TEXT.set(n, n.nodeValue.replace(k, REV[k]));     // text set in Hindi by the app
        else continue;
      }
      const en = ORIG_TEXT.get(n), key = en.trim();
      n.nodeValue = en.replace(key, t(key));
    }
    document.querySelectorAll(ATTRS.map((a) => `[${a}]`).join(",")).forEach((el) => {
      if (el.closest("[data-dyn]")) return;
      if (!ORIG_ATTR.has(el)) {
        const o = {};
        ATTRS.forEach((a) => { const v = el.getAttribute(a); if (v && v in HI) o[a] = v; });
        ORIG_ATTR.set(el, o);
      }
      Object.entries(ORIG_ATTR.get(el)).forEach(([a, en]) => el.setAttribute(a, t(en)));
    });
    const nm = $("s-name");
    if (nm.value === "Our rooftop" || nm.value === HI["Our rooftop"]) nm.value = t("Our rooftop");
    const btn = $("lang-btn");
    btn.textContent = LANG === "hi" ? "English" : "हिंदी";
    btn.lang = LANG === "hi" ? "en" : "hi";
    btn.setAttribute("aria-label", LANG === "hi" ? "Switch to English" : "हिंदी में देखें");
  }

  function setLang(lang) {
    LANG = lang;
    try { localStorage.setItem(LANG_KEY, lang); } catch (_) { /* private mode */ }
    applyStatic();
    drawLabel();
    SAID.forEach((el) => { if (el.isConnected && el._say) el.textContent = el._say[0] ? t(el._say[0], el._say[1]) : ""; });
    if (lastPlanBody) runPlan(lastPlanBody).catch(() => { /* keep the old result */ });
    if (sys && !$("w-dash").hidden) { renderHead(); loadOutlook(); loadDay(viewDate); if (dustData) renderDust(dustData); }
    if (impactData) renderImpact(impactData);
    if (reportData && !$("view-report").hidden) renderReport(reportData);
    renderReview();
  }
  $("lang-btn").onclick = () => setLang(LANG === "hi" ? "en" : "hi");

  // ------------------------------------------------------------------ boot
  applyStatic();
  initReportPeriod();
  initMap();
  initWatch();
  showTab(tabFromHash());
})();
