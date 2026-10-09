"""Plan mode: size, cost, subsidy, savings and payback for a rooftop solar system.

Every rupee figure comes from a documented rule or an assumption the user can override.
Sources (checked Oct 2026):
* PM Surya Ghar central subsidy: Rs 30,000/kW for the first 2 kW, Rs 18,000 for the 3rd kW,
  capped at Rs 78,000 (PIB, Mar 2025).
* Delhi Solar Policy 2024: extra Rs 2,000/kW capped at Rs 10,000 per consumer; generation-based
  incentive of Rs 3/unit (up to 3 kW) or Rs 2/unit (3-10 kW) for 5 years.
* DERC domestic energy slabs (same for BRPL, BYPL, TPDDL): 0-200 Rs 3, 201-400 Rs 4.5,
  401-800 Rs 6.5, 801-1200 Rs 7, above 1200 Rs 8 per unit. PPAC, fixed charges and tax excluded.
* Delhi Government power subsidy: bill waived up to 200 units/month; 50% (max Rs 800) for 201-400.
* CEA CO2 baseline: 0.727 kg CO2 per kWh (FY 2023-24 weighted average).
"""
from __future__ import annotations

import calendar
import math

from weather import monthly_ghi

SLABS = [(200, 3.0), (200, 4.5), (400, 6.5), (400, 7.0), (math.inf, 8.0)]
M2_PER_KW = 10.0            # shade-free roof area needed per kW (MNRE rule of thumb)
TILT_GAIN = 1.08            # annual gain of a tilted, south-facing panel over flat ground
PLAN_PR = 0.77              # whole-system performance ratio incl. heat losses, for planning
DEGRADATION = 0.005         # panel output lost per year
CO2_KG_PER_KWH = 0.727
DEFAULT_COST_PER_KW = 60000.0
DEFAULT_EXPORT_RATE = 3.0   # Rs per surplus unit credited under net metering (assumption)
LIFETIME_YEARS = 25


def energy_charge(units: float) -> float:
    """Monthly energy charge (Rs) on DERC domestic slabs."""
    units = max(0.0, units)
    bill, remaining = 0.0, units
    for size, rate in SLABS:
        take = min(remaining, size)
        bill += take * rate
        remaining -= take
        if remaining <= 0:
            break
    return bill


def delhi_subsidised(units: float, bill: float) -> float:
    """Bill after the Delhi Government domestic power subsidy."""
    if units <= 200:
        return 0.0
    if units <= 400:
        return bill - min(0.5 * bill, 800.0)
    return bill


def units_from_bill(bill: float) -> float:
    """Invert the slab tariff: monthly bill (Rs, energy charges only) -> units."""
    lo, hi = 0.0, 20000.0
    for _ in range(60):
        mid = (lo + hi) / 2
        if energy_charge(mid) < bill:
            lo = mid
        else:
            hi = mid
    return round(hi, 0)


def central_subsidy(kw: float) -> float:
    return min(30000.0 * min(kw, 2.0) + 18000.0 * max(0.0, min(kw - 2.0, 1.0)), 78000.0)


def delhi_capital_subsidy(kw: float) -> float:
    return min(2000.0 * kw, 10000.0)


def gbi_rate(kw: float) -> float:
    return 3.0 if kw <= 3.0 else 2.0


def plan(req: dict) -> dict:
    lat, lon = float(req["lat"]), float(req["lon"])
    in_delhi = (req.get("state") or "delhi").lower() == "delhi"
    usable_fraction = float(req.get("usable_fraction") or 0.7)
    roof_area = float(req.get("roof_area_m2") or 0)
    if roof_area <= 0:
        raise ValueError("Roof area must be more than 0 square metres.")
    if req.get("monthly_units"):
        units = float(req["monthly_units"])
    elif req.get("monthly_bill"):
        units = units_from_bill(float(req["monthly_bill"]))
    else:
        raise ValueError("Enter your monthly units or your monthly bill.")
    if units <= 0:
        raise ValueError("Monthly units must be more than 0.")
    cost_per_kw = float(req.get("cost_per_kw") or DEFAULT_COST_PER_KW)
    export_rate = float(req.get("export_rate") or DEFAULT_EXPORT_RATE)

    ghi, ghi_source = monthly_ghi(lat, lon)
    days = [calendar.monthrange(2026, m)[1] for m in range(1, 13)]
    kwh_per_kwp = [g * d * TILT_GAIN * PLAN_PR for g, d in zip(ghi, days)]
    yearly_per_kwp = sum(kwh_per_kwp)

    usable_area = roof_area * usable_fraction
    max_by_roof = usable_area / M2_PER_KW
    need_kw = units * 12 / yearly_per_kwp
    kw = min(max_by_roof, need_kw, 10.0)
    kw = math.floor(kw * 2) / 2            # vendors sell in 0.5 kW steps
    limited_by = "roof" if max_by_roof < need_kw else "usage"
    if kw < 1.0:
        if max_by_roof >= 1.0:
            kw = 1.0
        else:
            raise ValueError(f"The usable roof ({usable_area:.0f} m2) fits less than 1 kW of panels.")

    gross_cost = kw * cost_per_kw
    sub_central = central_subsidy(kw)
    sub_state = delhi_capital_subsidy(kw) if in_delhi else 0.0
    net_cost = gross_cost - sub_central - sub_state

    months = []
    for m in range(12):
        gen = kw * kwh_per_kwp[m]
        before = energy_charge(units)
        net_units = units - gen
        after = energy_charge(max(net_units, 0.0))
        if in_delhi:
            before = delhi_subsidised(units, before)
            after = delhi_subsidised(max(net_units, 0.0), after)
        export_credit = max(-net_units, 0.0) * export_rate
        gbi = gen * gbi_rate(kw) if in_delhi else 0.0
        months.append({
            "month": calendar.month_abbr[m + 1],
            "generation_kwh": round(gen, 1),
            "consumption_kwh": round(units, 1),
            "bill_before": round(before, 0),
            "bill_after": round(after, 0),
            "export_credit": round(export_credit, 0),
            "gbi": round(gbi, 0),
        })

    bill_saving_y1 = sum(mo["bill_before"] - mo["bill_after"] + mo["export_credit"] for mo in months)
    gbi_y1 = sum(mo["gbi"] for mo in months)
    yearly_gen = sum(mo["generation_kwh"] for mo in months)

    cumulative, payback, lifetime = 0.0, None, 0.0
    for year in range(1, LIFETIME_YEARS + 1):
        factor = (1 - DEGRADATION) ** (year - 1)
        benefit = bill_saving_y1 * factor + (gbi_y1 * factor if year <= 5 else 0.0)
        if payback is None and cumulative + benefit >= net_cost:
            payback = year - 1 + (net_cost - cumulative) / benefit
        cumulative += benefit
        lifetime += benefit

    notes = []
    if in_delhi and units <= 200:
        notes.append("Your bill is already Rs 0 under the Delhi free-200-units scheme, so most of your "
                     "return comes from the generation incentive and surplus export credit.")
    if limited_by == "roof":
        notes.append("Your roof, not your usage, limits the system size.")

    return {
        "inputs": {"lat": lat, "lon": lon, "roof_area_m2": roof_area, "usable_area_m2": round(usable_area, 1),
                   "monthly_units": units, "state": "delhi" if in_delhi else "other",
                   "cost_per_kw": cost_per_kw, "export_rate": export_rate},
        "system_kw": kw,
        "panels_approx": math.ceil(kw * 1000 / 550),
        "limited_by": limited_by,
        "yearly_generation_kwh": round(yearly_gen, 0),
        "yield_kwh_per_kwp": round(yearly_per_kwp, 0),
        "gross_cost": round(gross_cost, 0),
        "central_subsidy": round(sub_central, 0),
        "state_subsidy": round(sub_state, 0),
        "net_cost": round(net_cost, 0),
        "yearly_bill_saving": round(bill_saving_y1, 0),
        "yearly_gbi_first5": round(gbi_y1, 0),
        "monthly_benefit_avg": round((bill_saving_y1 + gbi_y1) / 12, 0),
        "payback_years": round(payback, 1) if payback is not None else None,
        "lifetime_benefit_25y": round(lifetime, 0),
        "co2_tonnes_per_year": round(yearly_gen * CO2_KG_PER_KWH / 1000, 2),
        "months": months,
        "sunlight_source": ghi_source,
        "notes": notes,
        "assumptions": [
            f"{M2_PER_KW:.0f} m2 of shade-free roof per kW; {int(usable_fraction*100)}% of the roof usable",
            f"Performance ratio {PLAN_PR}, tilt gain {TILT_GAIN}, {DEGRADATION*100:.1f}% panel ageing per year",
            f"Installed cost Rs {cost_per_kw:,.0f} per kW before subsidy (get vendor quotes)",
            "DERC energy slabs only; PPAC, fixed charges and tax not included (real savings are usually higher)",
            f"Surplus units credited at Rs {export_rate:.1f} each",
        ],
    }
