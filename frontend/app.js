/* SuryaWatch web app - Stage 1 (Plan mode + today's expected output). No build step. */
(function () {
  "use strict";

  const API = (window.SURYAWATCH_API || "").replace(/\/$/, "");
  const $ = (id) => document.getElementById(id);
  const DELHI = [28.6139, 77.209];
  const SQFT_PER_M2 = 10.7639;

  if (!API) $("api-banner").hidden = false;

  // ------------------------------------------------------------------ formatting
  const inr = (x) => "₹" + Math.round(x).toLocaleString("en-IN");
  const lakh = (x) => (Math.abs(x) >= 100000 ? "₹" + (x / 100000).toFixed(2).replace(/\.?0+$/, "") + " lakh" : inr(x));
  const n0 = (x) => Math.round(x).toLocaleString("en-IN");
  const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

  async function api(path, opts) {
    if (!API) throw new Error("The app is not connected to its server yet.");
    const res = await fetch(API + path, opts);
    let body = {};
    try { body = await res.json(); } catch (_) { /* empty body */ }
    if (!res.ok) throw new Error(body.error || `Server error (${res.status}). Please try again.`);
    return body;
  }

  // ------------------------------------------------------------------ tabs
  function showTab(name) {
    ["plan", "watch"].forEach((t) => {
      $("view-" + t).hidden = t !== name;
      $("tab-" + t).setAttribute("aria-selected", String(t === name));
    });
    if (name === "plan" && map) setTimeout(() => map.invalidateSize(), 50);
  }
  $("tab-plan").onclick = () => { location.hash = "plan"; };
  $("tab-watch").onclick = () => { location.hash = "watch"; };
  window.addEventListener("hashchange", () => showTab(location.hash === "#watch" ? "watch" : "plan"));

  // ------------------------------------------------------------------ map
  let map = null, marker = null, roof = null, drawing = false, vertices = [];
  const loc = { lat: null, lon: null };

  function initMap() {
    if (typeof L === "undefined") { $("map").textContent = "Map could not load. You can still type your roof area."; return; }
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
    $("map-hint").textContent = "Home placed. Now draw the roof outline, or type the area below.";
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
      $("map-hint").textContent = m2 > 3000
        ? `That outline is ${n0(m2)} m², bigger than most homes. Zoom in to your own roof and draw again.`
        : `Roof outline: ${n0(m2)} m² (${n0(m2 * SQFT_PER_M2)} sq ft).`;
    }
  }

  function finishDrawing() {
    drawing = false;
    map.doubleClickZoom.enable();
    $("draw-btn").textContent = "Draw roof outline";
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
    $("draw-btn").textContent = "Finish outline";
    $("draw-btn").setAttribute("aria-pressed", "true");
    $("map-hint").textContent = "Click each corner of the roof. Double-click or press Finish when done.";
    if (map.getZoom() < 17) {
      map.setView(loc.lat !== null ? [loc.lat, loc.lon] : map.getCenter(), 19);
      $("map-hint").textContent = "Zoomed in. Find your roof, then click each of its corners. Double-click or press Finish when done.";
    }
  };
  $("clear-btn").onclick = () => {
    if (roof) { map.removeLayer(roof); roof = null; }
    vertices = []; drawing = false;
    if (map) map.doubleClickZoom.enable();
    $("draw-btn").textContent = "Draw roof outline";
    $("draw-btn").setAttribute("aria-pressed", "false");
    $("map-hint").textContent = "Outline cleared.";
  };
  $("area-unit").onchange = () => {
    const v = parseFloat($("area").value);
    if (!v) return;
    $("area").value = Math.round($("area-unit").value === "sqft" ? v * SQFT_PER_M2 : v / SQFT_PER_M2);
  };

  async function search() {
    const q = $("search").value.trim();
    if (!q) return;
    $("map-hint").textContent = "Searching...";
    try {
      const url = "https://nominatim.openstreetmap.org/search?format=json&limit=1&countrycodes=in&q=" + encodeURIComponent(q);
      const res = await fetch(url, { headers: { "Accept-Language": "en" } });
      const hits = await res.json();
      if (!hits.length) { $("map-hint").textContent = "No match. Try a nearby landmark or locality."; return; }
      setLocation(parseFloat(hits[0].lat), parseFloat(hits[0].lon), 18);
      $("map-hint").textContent = "Found. Click your exact roof, then draw its outline.";
    } catch (_) {
      $("map-hint").textContent = "Search is unavailable. Click your home on the map instead.";
    }
  }
  $("search-btn").onclick = search;
  $("search").addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); search(); } });
  $("locate-btn").onclick = () => {
    if (!navigator.geolocation) return;
    $("map-hint").textContent = "Finding you...";
    navigator.geolocation.getCurrentPosition(
      (p) => setLocation(p.coords.latitude, p.coords.longitude, 19),
      () => { $("map-hint").textContent = "Location permission denied. Search or click the map instead."; },
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

  function renderPlan(r) {
    const months = r.months.map((m) => ({ label: m.month, value: m.generation_kwh }));
    const subsidy = r.central_subsidy + r.state_subsidy;
    const payback = r.payback_years == null ? "Over 25 years" : `${r.payback_years} years`;
    const notes = r.notes.map((t) => `<p class="note">${esc(t)}</p>`).join("");
    $("plan-result").innerHTML = `
      <div class="hero">
        <div class="label">Recommended system</div>
        <div class="big num">${r.system_kw} kW</div>
        <div class="sub">About ${r.panels_approx} panels of 550 W, making ${n0(r.yearly_generation_kwh)} units a year. Sized by your ${r.limited_by === "roof" ? "roof space" : "electricity use"}.</div>
      </div>
      <div class="stats">
        <div class="stat"><div class="label">You pay after subsidy</div><div class="value num">${lakh(r.net_cost)}</div></div>
        <div class="stat"><div class="label">Benefit per month</div><div class="value good num">${inr(r.monthly_benefit_avg)}</div></div>
        <div class="stat"><div class="label">Pays back in</div><div class="value num">${payback}</div></div>
        <div class="stat"><div class="label">25-year benefit</div><div class="value num">${lakh(r.lifetime_benefit_25y)}</div></div>
        <div class="stat"><div class="label">CO₂ avoided</div><div class="value num">${r.co2_tonnes_per_year} t/yr</div></div>
        <div class="stat"><div class="label">Subsidy total</div><div class="value good num">${lakh(subsidy)}</div></div>
      </div>
      ${notes}
      <table class="breakdown">
        <tr><td>System cost (${r.system_kw} kW × ${inr(r.inputs.cost_per_kw)})</td><td>${inr(r.gross_cost)}</td></tr>
        <tr><td>PM Surya Ghar subsidy</td><td class="minus">− ${inr(r.central_subsidy)}</td></tr>
        ${r.state_subsidy ? `<tr><td>Delhi Solar Policy subsidy</td><td class="minus">− ${inr(r.state_subsidy)}</td></tr>` : ""}
        <tr class="total"><td>You pay</td><td>${inr(r.net_cost)}</td></tr>
      </table>
      <div id="plan-chart"></div>
      <details><summary>Where the yearly benefit comes from</summary><ul>
        <li>Lower electricity bills: ${inr(r.yearly_bill_saving)} a year</li>
        ${r.yearly_gbi_first5 ? `<li>Delhi generation incentive: ${inr(r.yearly_gbi_first5)} a year for the first 5 years</li>` : ""}
        <li>Sunlight data: ${esc(r.sunlight_source)} (${n0(r.yield_kwh_per_kwp)} units per kW per year)</li>
      </ul></details>
      <details><summary>Assumptions</summary><ul>${r.assumptions.map((a) => `<li>${esc(a)}</li>`).join("")}</ul></details>
      <details><summary>How to apply under PM Surya Ghar</summary><ol>${PORTAL_STEPS.map((s) => `<li>${esc(s)}</li>`).join("")}</ol></details>
      <div class="share-row">
        <button type="button" id="plan-watch" class="btn small">We installed this: start watching it</button>
        <button type="button" id="plan-share" class="btn small ghost wa">Share this plan on WhatsApp</button>
      </div>
      <p id="plan-watch-msg" class="hint" hidden></p>
      <div id="plan-ask"></div>`;
    $("plan-watch").onclick = async () => {
      const msg = $("plan-watch-msg");
      const yearly = r.yearly_bill_saving + r.yearly_gbi_first5;
      const unit = Math.min(30, Math.max(1, r.yearly_generation_kwh ? yearly / r.yearly_generation_kwh : 6));
      try {
        const s = await api("/systems", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({
          name: "Our rooftop", lat: r.inputs.lat, lon: r.inputs.lon, kwp: r.system_kw, tilt: 20, facing: 180,
          unit_value: Math.round(unit * 10) / 10, promise_kwh_year: r.yearly_generation_kwh,
          promise_source: "plan", plan_id: r.plan_id }) });
        safeSet(STORE_KEY, s.system_id);
        location.hash = "watch";
        await openSystem(s.system_id);
      } catch (ex) { msg.textContent = ex.message; msg.hidden = false; }
    };
    $("plan-share").onclick = () => shareWhatsApp([
      "SuryaWatch solar plan",
      `${r.system_kw} kW rooftop system (about ${r.panels_approx} panels), ${n0(r.yearly_generation_kwh)} units a year`,
      `Cost after subsidy: ${inr(r.net_cost)} (subsidy ${inr(r.central_subsidy + r.state_subsidy)})`,
      `Benefit: about ${inr(r.monthly_benefit_avg)} a month; ${r.payback_years == null ? "payback over 25 years" : `pays back in ${r.payback_years} years`}`,
      `Plan your own roof: ${appLink("#plan")}`,
    ].join("\n"));
    helperBox($("plan-ask"), "plan", () => ({ system_kw: r.system_kw, yearly_units: r.yearly_generation_kwh, net_cost: r.net_cost,
      central_subsidy: r.central_subsidy, state_subsidy: r.state_subsidy, monthly_benefit: r.monthly_benefit_avg,
      payback_years: r.payback_years, monthly_units: r.inputs.monthly_units, state: r.inputs.state, roof_m2: r.inputs.roof_area_m2,
      limited_by: r.limited_by, notes: r.notes }));
    barChart($("plan-chart"), months, {
      title: "Units your panels make each month",
      sub: "Dashed line: your monthly use",
      ref: r.inputs.monthly_units, refLabel: `Your use: ${n0(r.inputs.monthly_units)} units`,
      tip: (d) => `<b>${d.label}</b><br>${n0(d.value)} units made<br>${n0(r.inputs.monthly_units)} units used`,
    });
  }

  // read units, DISCOM and sanctioned load from a bill photo (Amazon Bedrock; the photo is not stored)
  $("bill-file").onchange = async (e) => {
    const file = (e.target.files || [])[0];
    e.target.value = "";
    if (!file) return;
    const msg = $("bill-msg");
    msg.textContent = "Reading your bill...";
    try {
      const r = await api("/bill", { method: "POST", headers: { "content-type": "application/json" },
        body: JSON.stringify({ image_base64: await shrink(file) }) });
      if (!r.ai_available) { msg.textContent = r.message; return; }
      const units = r.average_monthly_units || r.monthly_units;
      if (units) {
        document.querySelector('input[name="usage-kind"][value="units"]').checked = true;
        $("usage").value = Math.round(units);
      }
      if (r.state) $("state").value = r.state;
      if (r.sanctioned_load_kw) $("sload").value = r.sanctioned_load_kw;
      const parts = [];
      if (r.monthly_units) parts.push(`${n0(r.monthly_units)} units a month on this bill`);
      if (r.average_monthly_units) parts.push(`${r.history.length}-month average ${n0(r.average_monthly_units)} units (used above)`);
      if (r.discom) parts.push(r.discom);
      if (r.sanctioned_load_kw) parts.push(`sanctioned load ${r.sanctioned_load_kw} kW`);
      msg.textContent = units
        ? `Read from your bill (${r.confidence} confidence): ${parts.join(" · ")}. Please check the numbers.${r.notes ? " " + r.notes : ""}`
        : "Could not find the units on this bill. Please type them in.";
    } catch (ex) {
      msg.textContent = ex.name === "InvalidStateError" ? "This photo format can't be opened. Please use a JPG." : ex.message;
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
    if (loc.lat === null) problems.push("place your home on the map");
    if (!(areaRaw > 0)) problems.push("enter the roof area");
    if (!(usage > 0)) problems.push(kind === "units" ? "enter your monthly units" : "enter your monthly bill");
    if (problems.length) { err.textContent = "Please " + problems.join(", ") + "."; err.hidden = false; return; }
    const m2 = $("area-unit").value === "sqft" ? areaRaw / SQFT_PER_M2 : areaRaw;
    const body = {
      lat: loc.lat, lon: loc.lon, roof_area_m2: m2,
      usable_fraction: (parseFloat($("usable").value) || 70) / 100,
      state: $("state").value, cost_per_kw: parseFloat($("cost").value) || 60000,
      sanctioned_load_kw: parseFloat($("sload").value) || null,
    };
    body[kind === "units" ? "monthly_units" : "monthly_bill"] = usage;
    const btn = $("plan-btn");
    btn.disabled = true; btn.textContent = "Working out your plan...";
    try {
      renderPlan(await api("/plan", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body) }));
      if (window.innerWidth < 900) $("plan-result").scrollIntoView({ behavior: "smooth" });
    } catch (ex) {
      err.textContent = ex.message; err.hidden = false;
    } finally {
      btn.disabled = false; btn.textContent = "Plan my solar";
    }
  });

  // ------------------------------------------------------------------ watch mode
  const STORE_KEY = "suryawatch.system";
  const safeGet = (k) => { try { return localStorage.getItem(k); } catch (_) { return null; } };
  const safeSet = (k, v) => { try { v == null ? localStorage.removeItem(k) : localStorage.setItem(k, v); } catch (_) { /* private mode */ } };
  const pad = (n) => String(n).padStart(2, "0");
  const localStamp = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
  const todayStr = () => localStamp(new Date()).slice(0, 10);
  const clock = (t) => { const h = +t.slice(11, 13), m = t.slice(14, 16); return `${h % 12 || 12}:${m} ${h < 12 ? "AM" : "PM"}`; };
  const pct = (x) => (x == null ? "–" : Math.round(x * 100) + "%");
  const hourLabel = (h) => (h === 12 ? "12 PM" : h < 12 ? `${h} AM` : `${h - 12} PM`);

  let sys = null;          // current system meta
  let viewDate = todayStr();
  let review = [];         // readings waiting to be saved

  const STATUS = {
    healthy: { label: "Working well", cls: "good", icon: "M5 12l4 4 10-10" },
    smog: { label: "Smog day", cls: "warn", icon: "M3 9h13M5 13h15M3 17h11" },
    dust: { label: "Clean panels", cls: "serious", icon: "M12 3v12M7 10l5 5 5-5M5 20h14" },
    fault: { label: "Possible fault", cls: "critical", icon: "M12 4v9M12 17v.5" },
    check: { label: "Check system", cls: "warn", icon: "M12 4v9M12 17v.5" },
    no_data: { label: "No reading yet", cls: "none", icon: "M5 12h14" },
    too_early: { label: "Too early", cls: "none", icon: "M12 6v6l4 2" },
  };

  // ---- setup
  function parseLoc(text) {
    const m = String(text).match(/(-?\d+(?:\.\d+)?)\s*[, ]\s*(-?\d+(?:\.\d+)?)/);
    return m ? { lat: parseFloat(m[1]), lon: parseFloat(m[2]) } : null;
  }
  $("s-from-plan").onclick = () => {
    if (loc.lat === null) { $("s-error").textContent = "Place your home on the Plan tab's map first."; $("s-error").hidden = false; return; }
    $("s-loc").value = `${loc.lat.toFixed(5)}, ${loc.lon.toFixed(5)}`;
  };
  $("s-my").onclick = () => navigator.geolocation && navigator.geolocation.getCurrentPosition(
    (p) => { $("s-loc").value = `${p.coords.latitude.toFixed(5)}, ${p.coords.longitude.toFixed(5)}`; },
    () => { $("s-error").textContent = "Location permission denied. Paste the numbers instead."; $("s-error").hidden = false; });

  $("s-save").onclick = async () => {
    const err = $("s-error");
    err.hidden = true;
    const where = parseLoc($("s-loc").value);
    const kwp = parseFloat($("s-kwp").value);
    if (!where) { err.textContent = "Enter the location as two numbers, like 28.7041, 77.1025."; err.hidden = false; return; }
    if (!(kwp > 0)) { err.textContent = "Enter the system size in kW (it is on the inverter label or the installer's bill)."; err.hidden = false; return; }
    const btn = $("s-save");
    btn.disabled = true;
    try {
      const r = await api("/systems", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({
        name: $("s-name").value, lat: where.lat, lon: where.lon, kwp, tilt: $("s-tilt").value, facing: $("s-facing").value,
        unit_value: $("s-unit").value, promise_kwh_year: $("s-promise").value || null }) });
      safeSet(STORE_KEY, r.system_id);
      await openSystem(r.system_id);
    } catch (ex) { err.textContent = ex.message; err.hidden = false; } finally { btn.disabled = false; }
  };

  $("s-open").onclick = () => {
    const raw = $("s-open-id").value.trim();
    const m = raw.match(/system=([a-z0-9]+)/i) || raw.match(/^([a-z0-9]{6,20})$/i);
    if (!m) { $("s-error").textContent = "Paste the full link or the 10-character system ID."; $("s-error").hidden = false; return; }
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
      $("s-error").textContent = ex.message; $("s-error").hidden = false;
      return;
    }
    $("w-setup").hidden = true; $("w-dash").hidden = false;
    $("d-name").textContent = sys.name;
    const facing = { 180: "south", 135: "south-east", 225: "south-west", 90: "east", 270: "west", 0: "north" }[Math.round(sys.facing)] || `${sys.facing}°`;
    $("d-meta").textContent = `${sys.kwp} kW · panels face ${facing}, ${sys.tilt}° tilt · ${sys.lat.toFixed(3)}, ${sys.lon.toFixed(3)}`;
    $("d-date").max = todayStr();
    loadOutlook();
    await loadDay(viewDate);
  }

  async function loadDay(date) {
    viewDate = date;
    $("d-date").value = date;
    $("d-next").disabled = date >= todayStr();
    $("d-verdict").innerHTML = '<p class="hint">Checking the sunlight and air for this day...</p>';
    try {
      const d = await api(`/systems/${sys.system_id}/day?date=${date}`);
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
    const badge = `<span class="badge ${st.cls}"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="${st.icon}"/></svg>${st.label}</span>`;
    let stats = "";
    if (v.actual_kwh != null) {
      stats = `<div class="stats">
        <div class="stat"><div class="label">${v.final ? "Made" : "Made so far"}</div><div class="value num">${v.actual_kwh} kWh</div></div>
        <div class="stat"><div class="label">Sunlight allowed</div><div class="value num">${v.expected_kwh} kWh</div></div>
        <div class="stat"><div class="label">Performance</div><div class="value num">${pct(v.performance)}</div></div>
        <div class="stat"><div class="label">Haze cut sunlight</div><div class="value num">${pct(v.haze_loss)}</div></div>
        <div class="stat"><div class="label">Panel loss</div><div class="value num">${pct(v.panel_loss)}</div></div>
        <div class="stat"><div class="label">Lost per week</div><div class="value num">${inr(v.rupees_lost_per_week || 0)}</div></div>
      </div>`;
    }
    const total = d.curve.length ? d.curve[d.curve.length - 1].expected_cum_kwh : null;
    const air = v.pm25 != null ? `Air: PM2.5 ${Math.round(v.pm25)} µg/m³, aerosol depth ${v.aod}.` : "";
    const sky = v.sky && v.sky.sky_factor != null ? ` Sunlight ${Math.round(v.sky.sky_factor * 100)}% of a clear day.` : "";
    $("d-verdict").innerHTML = `
      ${badge}
      <h3 class="verdict-title">${esc(v.title)}</h3>
      <p>${esc(v.message)}</p>
      ${stats}
      <p class="hint">${d.is_today ? "Today" : "That day"} a ${sys.kwp} kW system here should make about <b>${total != null ? total.toFixed(1) : "–"} kWh</b> in total.${sky} ${air}</p>
      <div class="share-row"><button type="button" id="v-share" class="btn small ghost wa">Share on WhatsApp</button></div>
      <div id="watch-ask"></div>`;
    $("v-share").onclick = () => {
      const nice = new Date(d.date + "T12:00").toLocaleDateString("en-IN", { weekday: "short", day: "numeric", month: "short" });
      const lines = [`SuryaWatch: ${sys.name}, ${nice}`, v.title, v.message];
      if (v.actual_kwh != null) lines.push(`Made ${v.actual_kwh} kWh; the sunlight allowed about ${v.expected_kwh} kWh.`);
      lines.push(appLink(`?system=${sys.system_id}&date=${d.date}#watch`));
      shareWhatsApp(lines.join("\n"));
    };
    helperBox($("watch-ask"), "watch", () => ({ date: d.date, system_kw: sys.kwp, result: v.title, explanation: v.message,
      made_kwh: v.actual_kwh, sunlight_allowed_kwh: v.expected_kwh, haze_loss: v.haze_loss, panel_loss: v.panel_loss,
      rupees_lost_per_week: v.rupees_lost_per_week, pm25: v.pm25, aerosol_optical_depth: v.aod }));
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
      if (near && near.d < 0.35) html += `<br>${esc(o.actualLabel)} at ${clock(near.p.t)}: ${o.fmt(near.p.y)} ${o.unit}`;
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
      title: "Energy made so far in the day (kWh)", unit: "kWh", fmt: (v) => v.toFixed(1),
      expectedLabel: "What the sunlight allowed", actualLabel: "Your E-Today readings",
      expected: [{ x: 5, y: 0 }].concat(d.curve.map((c) => ({ x: hrs(c.time) || 24, y: c.expected_cum_kwh }))), actual: energy,
    });
    if (power.length) {
      lineDotChart($("c-power"), {
        title: "Power at each reading (kW)", unit: "kW", fmt: (v) => v.toFixed(2),
        expectedLabel: "Expected power", actualLabel: "Your power readings",
        expected: d.curve.map((c) => ({ x: hrs(c.time) - 0.5, y: c.expected_kw })), actual: power,
      });
    } else {
      $("c-power").innerHTML = '<p class="hint">Add a photo of the "power now" screen to compare power through the day.</p>';
    }
  }

  function renderReadings(d) {
    const box = $("d-readings");
    if (!d.readings.length) {
      box.innerHTML = '<p class="hint">No readings for this day yet.</p>';
    } else {
      const val = (x, u) => (x == null ? "–" : `${x} ${u}`);
      box.innerHTML = `<div class="table-wrap"><table class="rtable"><thead><tr><th>Time</th><th>Power</th><th>Today</th><th>Total</th><th>State</th><th>From</th><th></th></tr></thead><tbody>
        ${d.readings.map((r) => `<tr><td>${clock(r.time)}</td><td class="num">${val(r.power_kw, "kW")}</td><td class="num">${val(r.e_today_kwh, "kWh")}</td>
          <td class="num">${val(r.e_total_kwh, "kWh")}</td><td>${esc(r.state || "–")}</td><td>${r.source === "photo" ? "Photo" : "Typed"}</td>
          <td><button type="button" class="link-btn" data-del="${esc(r.time)}" aria-label="Delete reading at ${clock(r.time)}">Remove</button></td></tr>`).join("")}
      </tbody></table></div>`;
      box.querySelectorAll("[data-del]").forEach((b) => (b.onclick = async () => {
        await api(`/systems/${sys.system_id}/readings/delete`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ time: b.dataset.del }) });
        loadDay(viewDate);
      }));
    }
    const cleaned = d.events.filter((e) => e.type === "cleaned").map((e) => e.time);
    $("d-events").textContent = cleaned.length ? `Last cleaned: ${cleaned[cleaned.length - 1].slice(0, 10)} at ${clock(cleaned[cleaned.length - 1])}` : "";
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
    $("r-save").textContent = review.length === 1 ? "Save 1 reading" : `Save ${review.length} readings`;
    box.innerHTML = review.map((r, i) => `
      <div class="rrow" data-i="${i}">
        ${r.thumb ? `<img src="${r.thumb}" alt="Inverter photo ${i + 1}">` : '<div class="nothumb">Typed</div>'}
        <div class="rfields">
          <label>Time<input type="datetime-local" data-k="time" value="${esc(r.time || "")}"></label>
          <label>Power now (kW)<input type="number" step="0.01" min="0" data-k="power_kw" value="${r.power_kw ?? ""}" inputmode="decimal"></label>
          <label>Today (kWh)<input type="number" step="0.1" min="0" data-k="e_today_kwh" value="${r.e_today_kwh ?? ""}" inputmode="decimal"></label>
          <label>Total (kWh)<input type="number" step="1" min="0" data-k="e_total_kwh" value="${r.e_total_kwh ?? ""}" inputmode="decimal"></label>
          <label>Inverter state<input type="text" maxlength="40" data-k="state" value="${esc(r.state ?? "")}" placeholder="Normal"></label>
          <p class="rnote ${r.status === "error" ? "error" : ""}">${esc(r.note || "")}</p>
        </div>
        <button type="button" class="link-btn" data-drop="${i}" aria-label="Discard">Discard</button>
      </div>`).join("");
    box.querySelectorAll("input[data-k]").forEach((inp) => (inp.oninput = () => {
      const i = +inp.closest(".rrow").dataset.i, k = inp.dataset.k;
      review[i][k] = k === "time" || k === "state" ? (inp.value || null) : inp.value === "" ? null : parseFloat(inp.value);
    }));
    box.querySelectorAll("[data-drop]").forEach((b) => (b.onclick = () => { review.splice(+b.dataset.drop, 1); renderReview(); }));
  }

  $("r-manual").onclick = () => {
    const now = new Date(), t = viewDate === todayStr() ? localStamp(now) : `${viewDate}T18:30`;
    review.push({ time: t, source: "manual", note: "Type the numbers shown on the display." });
    renderReview();
  };

  async function handleFiles(e) {
    const files = Array.from(e.target.files || []);
    e.target.value = "";
    $("r-error").hidden = true;
    for (const file of files) {
      const row = { source: "photo", note: "Reading the display...", status: "busy" };
      review.push(row);
      renderReview();
      try {
        const [time, dataUrl] = await Promise.all([exifTime(file), shrink(file)]);
        row.thumb = dataUrl;
        row.time = time || localStamp(new Date(file.lastModified || Date.now()));
        const timeNote = time ? "" : " Photo time not found (WhatsApp copies lose it), so check the time.";
        renderReview();
        const r = await api(`/systems/${sys.system_id}/photo`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ image_base64: dataUrl }) });
        row.photo_key = r.photo_key;
        if (r.ai_available) {
          Object.assign(row, { power_kw: r.power_kw, e_today_kwh: r.e_today_kwh, e_total_kwh: r.e_total_kwh, state: r.state });
          row.note = `Read by AI (${r.confidence} confidence). Check the numbers before saving.${r.notes ? " " + r.notes : ""}${timeNote}`;
        } else {
          row.note = (r.message || "AI reading is not available here. Type the numbers.") + timeNote;
        }
        row.status = "ok";
      } catch (ex) {
        row.status = "error";
        row.note = ex.message.includes("decode") || ex.name === "InvalidStateError"
          ? "This photo format can't be opened. Use JPG (set the phone camera to 'Most compatible')."
          : ex.message;
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
    if (bad) { err.textContent = "Every reading needs a time and at least one value."; err.hidden = false; return; }
    $("r-save").disabled = true;
    try {
      await api(`/systems/${sys.system_id}/readings`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ readings: items }) });
      const day = items.map((r) => r.time.slice(0, 10)).sort().pop();
      review = []; renderReview();
      await loadDay(day);
    } catch (ex) { err.textContent = ex.message; err.hidden = false; } finally { $("r-save").disabled = false; }
  };

  $("d-cleaned").onclick = async () => {
    const t = viewDate === todayStr() ? localStamp(new Date()) : `${viewDate}T08:00`;
    await api(`/systems/${sys.system_id}/events`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ type: "cleaned", time: t }) });
    loadDay(viewDate);
  };

  const shiftDay = (n) => { const d = new Date(viewDate + "T12:00"); d.setDate(d.getDate() + n); return localStamp(d).slice(0, 10); };
  $("d-prev").onclick = () => loadDay(shiftDay(-1));
  $("d-next").onclick = () => { if (viewDate < todayStr()) loadDay(shiftDay(1)); };
  $("d-date").onchange = () => { if ($("d-date").value) loadDay($("d-date").value); };
  $("d-share").onclick = async () => {
    const link = `${location.origin}${location.pathname}?system=${sys.system_id}#watch`;
    try { await navigator.clipboard.writeText(link); $("d-share").textContent = "Link copied"; } catch (_) { prompt("Copy this link", link); }
    setTimeout(() => { $("d-share").textContent = "Copy link"; }, 2000);
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
      <div class="ask-head"><h3>Ask SuryaWatch</h3>
        <div class="seg small" role="radiogroup" aria-label="Answer language">
          <label><input type="radio" name="lang-${n}" value="en" checked> English</label>
          <label><input type="radio" name="lang-${n}" value="hi"> हिंदी</label>
        </div></div>
      <div class="chips"></div>
      <div class="search-row"><input class="ask-q" type="text" maxlength="500" placeholder="Type a question in English or Hindi" aria-label="Your question">
        <button type="button" class="btn ask-go">Ask</button></div>
      <div class="ask-a" aria-live="polite"></div></div>`;
    const lang = () => el.querySelector(`input[name="lang-${n}"]:checked`).value;
    const drawChips = () => {
      el.querySelector(".chips").innerHTML = CHIPS[kind][lang()].map((q) => `<button type="button" class="chip">${esc(q)}</button>`).join("");
      el.querySelectorAll(".chip").forEach((c) => (c.onclick = () => { el.querySelector(".ask-q").value = c.textContent; go(); }));
    };
    const go = async () => {
      const q = el.querySelector(".ask-q").value.trim();
      const out = el.querySelector(".ask-a");
      if (q.length < 3) { out.innerHTML = '<p class="hint">Type a question first.</p>'; return; }
      out.innerHTML = '<p class="hint">Thinking...</p>';
      try {
        const r = await api("/ask", { method: "POST", headers: { "content-type": "application/json" },
          body: JSON.stringify({ question: q, lang: lang(), context: getContext() }) });
        out.innerHTML = r.answer
          ? `<div class="who">SuryaWatch${r.model && r.model !== "mock" ? " · Amazon Bedrock" : ""}</div><p>${esc(r.answer).replace(/\n+/g, "<br>")}</p>`
          : `<p class="hint">${esc(r.unavailable || "The helper is not available right now.")}</p>`;
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
  const DOW = ["Mon", "", "Wed", "", "Fri", "", "Sun"];

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
      const nice = d.toLocaleDateString("en-IN", { weekday: "short", day: "numeric", month: "short" });
      if (!v || v.performance_after_haze == null) {
        cells += `<button type="button" class="cell empty${key === viewDate ? " sel" : ""}" data-day="${key}" data-tip="${esc(nice)}: no reading" aria-label="${esc(nice)}, no reading"></button>`;
      } else {
        const label = (STATUS[v.code] || STATUS.no_data).label;
        const tipText = `${nice}: ${pct(v.performance_after_haze)} of possible output · ${label}${v.final ? "" : " (part day)"}`;
        cells += `<button type="button" class="cell${v.code === "fault" ? " fault" : ""}${key === viewDate ? " sel" : ""}" style="background:${heatColor(v.performance_after_haze)}" data-day="${key}" data-tip="${esc(tipText)}" aria-label="${esc(tipText)}"></button>`;
      }
    }
    $("d-heat").innerHTML = `<div class="heat-wrap"><div class="heat-days">${DOW.map((d) => `<span>${d}</span>`).join("")}</div><div class="heat">${cells}</div></div>
      <div class="heat-legend">${HEAT.map((h) => `<span><i style="background:${h.color}"></i>${h.label}</span>`).join("")}<span><i style="box-shadow:inset 0 0 0 1px #c9cfc5"></i>no reading</span></div>`;
    $("d-heat").querySelectorAll(".cell[data-day]").forEach((c) => {
      c.onmousemove = (ev) => showTip(esc(c.dataset.tip), ev);
      c.onmouseleave = hideTip;
      c.onclick = () => { hideTip(); loadDay(c.dataset.day); };
    });

    const c = summary.cleaning;
    const box = $("d-clean");
    if (!c) { box.innerHTML = '<p class="hint">After you clean the panels, press "We cleaned the panels today" below. SuryaWatch will compare the days before and after.</p>'; return; }
    const when = `${c.cleaned_at.slice(0, 10)} at ${clock(c.cleaned_at)}`;
    if (!c.ready) {
      box.innerHTML = `<div class="clean-box"><b>Cleaned on ${esc(when)}.</b><p class="hint" style="margin-top:4px">Waiting for full days of readings: ${c.days_before} before and ${c.days_after} after the cleaning so far. Add the evening reading on each day.</p></div>`;
      return;
    }
    const w = (x) => Math.max(4, Math.min(100, x * 100));
    box.innerHTML = `<div class="clean-box">
      <div>Cleaning on ${esc(when)} changed output by</div>
      <div class="big2 num">${c.gain_pct > 0 ? "+" : ""}${c.gain_pct}%</div>
      <div class="hint" style="margin-top:0">about ${c.kwh_per_day} kWh a day, worth ${inr(c.rupees_per_week)} a week</div>
      <div class="clean-bars">
        <span>Before</span><div class="track"><div class="fill before" style="width:${w(c.before)}%"></div></div><span class="num">${pct(c.before)}</span>
        <span>After</span><div class="track"><div class="fill" style="width:${w(c.after)}%"></div></div><span class="num">${pct(c.after)}</span>
      </div>
      <p class="hint">Share of possible output after allowing for haze. Average of ${c.days_before} day(s) before and ${c.days_after} after.</p></div>`;
  }

  const OUTLOOK = {
    clear: { label: "Clear", cls: "good", icon: "M12 5v2M12 17v2M5 12h2M17 12h2M7.8 7.8l1.4 1.4M14.8 14.8l1.4 1.4M7.8 16.2l1.4-1.4M14.8 9.2l1.4-1.4M12 9.5a2.5 2.5 0 1 0 0 5a2.5 2.5 0 1 0 0-5" },
    haze: { label: "Hazy", cls: "warn", icon: "M3 9h13M5 13h15M3 17h11" },
    smog_heavy: { label: "Heavy smog", cls: "serious", icon: "M3 8h16M5 12h15M3 16h16M6 20h10" },
    cloudy: { label: "Cloudy", cls: "none", icon: "M7 17h10a3.5 3.5 0 0 0 0-7a5 5 0 0 0-9.6 1.4A3 3 0 0 0 7 17z" },
    rain: { label: "Rain", cls: "none", icon: "M7 14h10a3.5 3.5 0 0 0 0-7a5 5 0 0 0-9.6 1.4A3 3 0 0 0 7 14zM9 17l-1 3M13 17l-1 3M17 17l-1 3" },
  };

  async function loadOutlook() {
    const box = $("d-outlook");
    try {
      const o = await api(`/systems/${sys.system_id}/outlook`);
      box.hidden = false;
      box.innerHTML = `<h2>Next two days</h2><p class="hint">From the sunlight, cloud, rain and air-quality forecast for this roof.</p>
        <div class="outlook">${o.days.map((d, i) => {
          const st = OUTLOOK[d.code] || OUTLOOK.clear;
          const nice = new Date(d.date + "T12:00").toLocaleDateString("en-IN", { weekday: "long", day: "numeric", month: "short" });
          const facts = [];
          if (d.sky_factor != null) facts.push(`sunlight ${Math.round(d.sky_factor * 100)}% of a clear day`);
          if (d.haze_loss >= 0.02) facts.push(`haze about ${Math.round(d.haze_loss * 100)}%`);
          if (d.pm25 != null) facts.push(`PM2.5 ${Math.round(d.pm25)}`);
          if ((d.rain_mm || 0) >= 0.5) facts.push(`rain ${Math.round(d.rain_mm)} mm${d.rain_prob_pct != null ? ` (${d.rain_prob_pct}% chance)` : ""}`);
          return `<div class="day">
            <div class="day-name">${i === 0 ? "Tomorrow" : "Day after"} · ${esc(nice)}</div>
            <span class="badge ${st.cls}"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="${st.icon}"/></svg>${st.label}</span>
            <div class="day-kwh num">${d.likely_kwh} kWh</div>
            <div class="hint" style="margin-top:0">expected from your ${sys.kwp} kW system</div>
            <p class="day-msg"><b>${esc(d.title)}.</b> ${esc(d.message)}</p>
            <p class="hint">${esc(facts.join(" · "))}</p></div>`;
        }).join("")}</div>`;
    } catch (ex) {
      box.hidden = false;
      box.innerHTML = `<h2>Next two days</h2><p class="hint">The forecast is not available right now (${esc(ex.message)}).</p>`;
    }
  }

  function renderPromise(p) {
    const box = $("d-promise");
    if (!p) { box.hidden = true; return; }
    box.hidden = false;
    const src = p.source === "installer" ? `your installer's promise of ${n0(p.promise_kwh_year)} units a year`
      : p.source === "plan" ? `your SuryaWatch plan: ${n0(p.promise_kwh_year)} units a year`
      : `SuryaWatch's estimate for this roof: ${n0(p.promise_kwh_year)} units a year`;
    let html = `<h2>Promised vs got</h2><p class="hint">Checked against ${esc(src)}.</p>`;
    if (!p.ready) {
      box.innerHTML = html + '<p class="hint">Add two photos of the Total (E-Total) screen taken a day or more apart, and SuryaWatch will compare what you got with what was promised.</p>';
      return;
    }
    const nice = (t) => new Date(t.slice(0, 10) + "T12:00").toLocaleDateString("en-IN", { day: "numeric", month: "short" });
    const block = (title, q) => {
      const top = Math.max(q.promised_kwh, q.actual_kwh, 0.1);
      const pctv = Math.round(q.ratio * 100);
      const verdict = q.ratio >= 1.05 ? `Ahead of the promise: ${pctv}%.`
        : q.ratio >= 0.95 ? `On track: ${pctv}% of the promise.`
        : `Behind by ${n0(q.gap_kwh)} units (about ${inr(q.gap_rupees)}): ${pctv}% of the promise.`;
      return `<div class="promise-block"><div class="promise-title">${esc(title)} <span class="hint">(${nice(q.first_day || q.from)} to ${nice(q.to)})</span></div>
        <div class="clean-bars">
          <span>Promised</span><div class="track"><div class="fill before" style="width:${(q.promised_kwh / top) * 100}%"></div></div><span class="num">${n0(q.promised_kwh)}</span>
          <span>Got</span><div class="track"><div class="fill" style="width:${(q.actual_kwh / top) * 100}%"></div></div><span class="num">${n0(q.actual_kwh)}</span>
        </div><p class="promise-verdict ${q.ratio < 0.95 ? "behind" : ""}">${verdict}</p></div>`;
    };
    if (p.month) html += block("This month so far", p.month);
    if (p.all && (!p.month || p.all.from !== p.month.from)) html += block(p.method === "daily" ? "Days with a final reading" : "Since tracking began", p.all);
    html += `<p class="hint">${p.method === "e_total" ? "Uses the inverter's Total counter, so days without a photo still count." : "Add Total (E-Total) photos for a more complete count."} Units are kWh.</p>`;
    box.innerHTML = html;
  }

  async function refreshSummary() {
    if (!sys) return;
    try {
      const s = await api("/systems/" + sys.system_id);
      sys = { ...sys, ...s };
      renderHistory(s);
      renderPromise(s.promise);
      if (s.alert_emails && !$("a-msg").textContent) $("a-msg").textContent = `${s.alert_emails} email address(es) get alerts for this system.`;
    } catch (_) { /* history is optional */ }
  }

  // ------------------------------------------------------------------ alerts (Amazon SNS)
  $("a-save").onclick = async () => {
    const msg = $("a-msg");
    try {
      const r = await api(`/systems/${sys.system_id}/alerts`, { method: "POST", headers: { "content-type": "application/json" },
        body: JSON.stringify({ email: $("a-email").value }) });
      msg.textContent = r.message;
    } catch (ex) { msg.textContent = ex.message; }
  };
  $("a-test").onclick = async () => {
    const msg = $("a-msg");
    msg.textContent = "Running today's check...";
    try {
      const r = await api(`/systems/${sys.system_id}/alerts/test`, { method: "POST", headers: { "content-type": "application/json" }, body: "{}" });
      msg.textContent = r.sent ? `Today's check (${(STATUS[r.code] || {}).label || r.code}) was ${r.sent}.` : "Nothing to report today.";
    } catch (ex) { msg.textContent = ex.message; }
  };

  function initWatch() {
    const qs = new URLSearchParams(location.search);
    const fromUrl = qs.get("system");
    const day = qs.get("date");
    if (day && /^\d{4}-\d{2}-\d{2}$/.test(day) && day <= todayStr()) viewDate = day;
    if (fromUrl) safeSet(STORE_KEY, fromUrl);
    const id = fromUrl || safeGet(STORE_KEY);
    if (id && API) openSystem(id);
    else $("w-setup").hidden = false;
  }

  // ------------------------------------------------------------------ boot
  initMap();
  initWatch();
  showTab(location.hash === "#watch" ? "watch" : "plan");
})();
