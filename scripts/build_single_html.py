"""Bundle the whole web app into ONE html file: for an Android APK wrapper, or to send as a file.

    python scripts/build_single_html.py
    python scripts/build_single_html.py --api https://xxxx.execute-api.us-east-1.amazonaws.com --web https://main.xxxx.amplifyapp.com

--api  the ApiUrl from the AWS deployment. Leave it out and the app asks for it the first time it opens
       (then remembers it), so an APK built today keeps working once the server is live.
--web  the WebUrl, used in links shared on WhatsApp. Leave it out and the app asks the server for it.

Writes dist/SuryaWatch.html. Needs internet when used (server, map, fonts), like the website.
"""
import argparse
import json
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB_DIR = os.path.join(ROOT, "frontend")


def read(*parts):
    with open(os.path.join(WEB_DIR, *parts), encoding="utf-8") as f:
        return f.read()


def script(code):
    return "<script>\n" + code.replace("</script", "<\\/script") + "\n</script>"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--api", default="", help="server address (ApiUrl); empty = ask inside the app")
    ap.add_argument("--web", default="", help="public website address (WebUrl) for shared links")
    ap.add_argument("--out", default=os.path.join(ROOT, "dist", "SuryaWatch.html"))
    a = ap.parse_args()

    html = read("index.html")
    leaflet_css = re.sub(r"url\(images/[^)]+\)", "none", read("vendor", "leaflet", "leaflet.css"))   # unused icons
    config = f"window.SURYAWATCH_API = {json.dumps(a.api.strip().rstrip('/'))};\n" \
             f"window.SURYAWATCH_WEB = {json.dumps(a.web.strip().rstrip('/'))};"
    swaps = {
        '<link rel="stylesheet" href="vendor/leaflet/leaflet.css">': "<style>\n" + leaflet_css + "\n</style>",
        '<link rel="stylesheet" href="style.css">': "<style>\n" + read("style.css") + "\n</style>",
        '<script src="vendor/leaflet/leaflet.js"></script>': script(read("vendor", "leaflet", "leaflet.js")),
        '<script src="config.js"></script>': script(config),
        '<script src="i18n.js"></script>': script(read("i18n.js")),
        '<script src="app.js"></script>': script(read("app.js")),
    }
    for tag, inline in swaps.items():
        if tag not in html:
            raise SystemExit(f"index.html no longer contains {tag!r}; update this script.")
        html = html.replace(tag, inline)
    html = html.replace('<meta name="viewport"', '<meta name="theme-color" content="#2e7d4f">\n  <meta name="viewport"', 1)
    leftover = re.findall(r'(?:src|href)="(?!https?:|data:|#|\$\{)([^"]+)"', html)
    if leftover:
        raise SystemExit(f"Still points at local files: {leftover}")

    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"Wrote {a.out} ({len(html.encode('utf-8')) // 1024} KB)")
    print("Server address:", a.api or "asked inside the app on first launch")


if __name__ == "__main__":
    main()
