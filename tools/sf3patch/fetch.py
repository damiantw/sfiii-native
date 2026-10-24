"""Downloading the translation project's files from its own server (never redistributed).

`fetch` saves SF3Patch.exe (the V25.1 wizard, a 7-Zip self-extracting archive) and every
add-on zip listed in the V25+ folder into a directory of the user's choosing.
"""
import html.parser
from pathlib import Path
import urllib.parse
import urllib.request

SITE = "https://sf3transftp.shiningforcecentral.com/"
WIZARD = SITE + "SF3Patch.exe"
ADDONS = SITE + "V25+/"
# Not patches: a Windows display-scaling fix for the wizard itself.
SKIP = {"SF3Translation_PatchWizard_WinScalingFix.zip"}
UA = {"User-Agent": "sf3patch (sfiii-native)"}


class _Links(html.parser.HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            href = dict(attrs).get("href")
            if href:
                self.links.append(href)


def addon_urls(index_url=ADDONS):
    with urllib.request.urlopen(urllib.request.Request(index_url, headers=UA), timeout=60) as r:
        page = r.read().decode("utf-8", errors="replace")
    p = _Links()
    p.feed(page)
    out = []
    for href in p.links:
        url = urllib.parse.urljoin(index_url, href)
        name = urllib.parse.unquote(url.rsplit("/", 1)[-1])
        if name.lower().endswith(".zip") and name not in SKIP and url.startswith(index_url):
            out.append((name, url))
    return out


def download(url, dest, log=print):
    dest = Path(dest)
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=120) as r:
        size = int(r.headers.get("Content-Length") or 0)
        if dest.exists() and size and dest.stat().st_size == size:
            log("have %s" % dest.name)
            return dest
        tmp = dest.with_name(dest.name + ".part")
        with open(tmp, "wb") as f:
            while True:
                chunk = r.read(1 << 20)
                if not chunk:
                    break
                f.write(chunk)
    tmp.replace(dest)
    log("got  %s (%d bytes)" % (dest.name, dest.stat().st_size))
    return dest


def fetch(dest, wizard=True, addons=True, log=print):
    dest = Path(dest)
    (dest / "V25+").mkdir(parents=True, exist_ok=True)
    got = {}
    if wizard:
        got["wizard"] = download(WIZARD, dest / "SF3Patch.exe", log)
    if addons:
        got["addons"] = [download(url, dest / "V25+" / name, log) for name, url in addon_urls()]
    return got
