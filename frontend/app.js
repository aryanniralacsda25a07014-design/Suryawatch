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
      <details><summary>How to apply under PM Surya Ghar</summary><ol>${PORTAL_STEPS.map((s) => `<li>${esc(s)}</li>`).join("")}</ol></details>`;
    barChart($("plan-chart"), months, {
      title: "Units your panels make each month",
      sub: "Dashed line: your monthly use",
      ref: r.inputs.monthly_units, refLabel: `Your use: ${n0(r.inputs.monthly_units)} units`,
      tip: (d) => `<b>${d.label}</b><br>${n0(d.value)} units made<br>${n0(r.inputs.monthly_units)} units used`,
    });
  }

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

  // ------------------------------------------------------------------ watch: today's expected output
  $("w-btn").onclick = async () => {
    const err = $("w-error");
    err.hidden = true;
    const lat = loc.lat ?? DELHI[0], lon = loc.lon ?? DELHI[1];
    const kwp = parseFloat($("w-kwp").value) || 3;
    const q = new URLSearchParams({ lat, lon, kwp, tilt: $("w-tilt").value || 20, facing: $("w-facing").value });
    const btn = $("w-btn");
    btn.disabled = true;
    try {
      const r = await api("/expected?" + q.toString());
      const hours = r.hourly
        .map((h) => ({ hour: parseInt(h.time.slice(11, 13), 10), kw: h.expected_kw }))
        .filter((h) => h.hour >= 6 && h.hour <= 19)
        .map((h) => ({ label: h.hour <= 12 ? `${h.hour}${h.hour === 12 ? " PM" : " AM"}` : `${h.hour - 12} PM`, value: h.kw }));
      const sf = r.sky.sky_factor;
      const sky = sf == null ? "" : sf >= 0.8 ? "Mostly clear sky" : sf >= 0.55 ? "Hazy or partly cloudy" : "Heavy cloud or haze";
      const where = loc.lat === null ? "central Delhi (place your home on the Plan tab for your exact roof)" : "your roof";
      $("w-result").innerHTML = `
        <div class="hero" style="margin-top:18px">
          <div class="label">A ${kwp} kW system at ${esc(where)} should make today</div>
          <div class="big num">${r.expected_kwh} kWh</div>
          <div class="sub">${sky}${sf != null ? ` (sunlight ${Math.round(sf * 100)}% of a perfectly clear day)` : ""}.</div>
        </div><div id="w-chart"></div>`;
      barChart($("w-chart"), hours, {
        title: "Expected power through the day (kW)",
        sub: "Each bar is the average for the hour ending at that time",
        labelEvery: 2, fmtTick: (v) => v.toFixed(1),
        tip: (d) => `<b>${d.label}</b><br>${d.value.toFixed(2)} kW expected`,
      });
    } catch (ex) {
      err.textContent = ex.message; err.hidden = false;
    } finally {
      btn.disabled = false;
    }
  };

  // ------------------------------------------------------------------ boot
  initMap();
  showTab(location.hash === "#watch" ? "watch" : "plan");
})();
