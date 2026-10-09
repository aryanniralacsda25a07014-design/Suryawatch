# SuryaWatch — plan it, then watch it

**Rooftop solar for Indian homes, from "should I?" to "is it working?"**
Built for **Environmental Hacks 2026** (WeMakeDevs × AWS, Bharat Builds Tour), Track 03: Waste and Energy.

- **Plan** — mark your roof on a satellite map and enter your electricity use. SuryaWatch sizes the system and shows the cost after PM Surya Ghar and Delhi subsidies, the monthly benefit, the payback period and the CO₂ avoided.
- **Watch** — for homes that already have panels. Photograph the inverter display; AI reads the numbers, SuryaWatch compares them with what that day's sunlight should have produced, and says whether a shortfall is **smog** (not your fault), **dust** (clean now, ₹ lost per week) or a **fault** (call your installer).

> Plan promises you a number of units a year. Watch makes sure you actually get them.

## Why

- PM Surya Ghar crossed 50 lakh rooftop systems in August 2026, and most new owners never check their output.
- Dust and air pollution cut Indian solar output by 17–25% (Duke University study at IIT Gandhinagar); Delhi's October–November smog is the worst case.
- Over 1 crore households had registered on the PM Surya Ghar portal by May 2026, but far fewer had installed; many stall at sizing, cost and paperwork.

## Architecture (AWS)

| Piece | AWS service | Role |
|---|---|---|
| Web app | **AWS Amplify Hosting** | Static site (HTML, CSS, JS, no build step) |
| API | **Amazon API Gateway** (HTTP API) + **AWS Lambda** (Python 3.12, arm64) | `/plan`, `/expected`, Watch routes |
| Data | **Amazon DynamoDB** | Plans, systems, readings, daily verdicts |
| Photos | **Amazon S3** | Inverter-display photos (private bucket, pre-signed uploads) |
| AI | **Amazon Bedrock** (Amazon Nova 2 Lite) | Reads inverter photos, writes advice *(Stage 2–3)* |
| Daily check | **Amazon EventBridge Scheduler** + **Amazon SNS** | Evening check and email alerts *(Stage 3)* |
| Infrastructure | **AWS SAM** (CloudFormation) | Everything above is defined in `template.yaml` |

Free public data: [Open-Meteo](https://open-meteo.com/) (hourly sunlight on the panel plane, temperature, cloud, rain, and air quality incl. aerosol optical depth) and [NASA POWER](https://power.larc.nasa.gov/) (long-term monthly sunlight).

## How the solar engine works

All maths is plain Python in `backend/` (no third-party packages), unit-tested in `tests/`.

1. **Sun position** (NOAA equations) and **clear-sky sunlight** (Haurwitz model) for any place and minute.
2. **Expected output** = system kW × sunlight on the panel ÷ 1000 × performance ratio (0.85 when clean) × heat loss (−0.35% per °C of cell temperature above 25 °C).
3. **Watch verdict**: actual ÷ expected. Weather models only know *average* haze, so on smoggy days we estimate the extra haze loss from that day's aerosol optical depth, then call the rest **panel loss**. A sudden drop against recent days means a likely **fault**; a gradual loss with no recent rain or cleaning means **dust**.
4. **Plan**: long-term monthly sunlight → units per kW per year → system size limited by roof (10 m² per kW) and by use → slab-wise bill before and after (DERC domestic tariff, Delhi power subsidy, net metering) → PM Surya Ghar and Delhi subsidies, Delhi's generation incentive → payback with 0.5%/year panel ageing.

Sources for every rule are listed at the top of `backend/planner.py`.

## Repository layout

```
backend/        Lambda code: api.py (routes), solar.py, weather.py, planner.py, verdict.py, store.py
frontend/       Web app: index.html, style.css, app.js, config.js (written at deploy), vendor/leaflet
tests/          Offline unit tests:  python3 -m unittest discover -s tests -v
scripts/        deploy.sh (CloudShell deploy), local_server.py (run everything on a laptop)
template.yaml   AWS SAM template      samconfig.toml   deploy settings (stack "suryawatch", us-east-1)
```

## Deploy (AWS CloudShell, region us-east-1)

```bash
git clone https://github.com/<your-user>/suryawatch.git && cd suryawatch
bash scripts/deploy.sh
```

The script runs the tests, deploys the backend with SAM, points the web app at the new API, and publishes it to Amplify Hosting. It prints the API and web-app URLs at the end.

To ship a newer version later: `cd suryawatch && git pull && bash scripts/deploy.sh`

## Run locally

```bash
python3 scripts/local_server.py --offline   # sample sunny-day weather, no internet needed
python3 scripts/local_server.py             # live weather data
# open http://localhost:8080
```

## Build stages

- [x] **Stage 1** — solar engine, AWS backend, Plan mode, today's expected output
- [ ] **Stage 2** — Watch mode: photo → Bedrock reading → expected vs actual → verdict
- [ ] **Stage 3** — daily EventBridge check and SNS email alerts, Hindi/English AI helper, cleaning before/after
- [ ] **Stage 4** — polish, real rooftop results, demo video

## Built with AI assistance

Code and documentation were written with **Claude (Anthropic)** as the AI coding assistant, directed and reviewed by the team. The team collected the real rooftop data, set up and deployed AWS, tested the app and recorded the demo. (Disclosed as required by the hackathon rules.)

## Team

Aryan Nirala, Agrim Chaturvedi, Prakhar, and a fourth member.

Estimates only: get vendor quotes before buying. Map imagery © Esri; Leaflet (BSD-2-Clause) is bundled in `frontend/vendor/leaflet`.
