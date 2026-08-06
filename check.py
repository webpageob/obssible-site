#!/usr/bin/env python3
"""
check.py — the single quality gate for this site.

Run it before every commit:

    python check.py

It fails loudly on the first problem. Everything it checks is fast and free;
none of it needs the network.

What it runs, in order:
  1. ruff       — lint and formatting
  2. pytest     — unit tests for the markdown converter and the build
  3. build      — the site must build cleanly
  4. idempotent — building twice must produce the same output
  5. output     — required metadata on every page, valid RSS and sitemap
  6. links      — no internal link points at a file that does not exist
"""

import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).parent

# On a Korean Windows install the console defaults to cp949, which cannot print
# the em dashes and arrows this project uses. Force UTF-8 so output never crashes.
for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")

# rss.xml embeds the build timestamp, so it legitimately differs between runs.
# Everything else must be byte-identical.
VOLATILE = re.compile(r"<lastBuildDate>.*?</lastBuildDate>")

GENERATED_PAGES = ["index.html", "about.html", "log/index.html"]

failures = []


def step(name):
    print("\n=== %s ===" % name)


def fail(message):
    failures.append(message)
    print("  FAIL: %s" % message)


def ok(message):
    print("  ok: %s" % message)


def run(cmd, name):
    step(name)
    # encoding is explicit: on a Korean Windows install the default is cp949,
    # which cannot decode the em dashes and arrows in this project's output.
    result = subprocess.run(
        cmd,
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    output = ((result.stdout or "") + (result.stderr or "")).strip()
    if output:
        print(output)
    if result.returncode != 0:
        fail("%s exited with code %d" % (name, result.returncode))
    else:
        ok(name)
    return result.returncode == 0


# ---------------------------------------------------------------- helpers


class LinkFinder(HTMLParser):
    """Collects href/src values so we can check they resolve to real files."""

    def __init__(self):
        super().__init__()
        self.links = []

    def handle_starttag(self, tag, attrs):
        for key, value in attrs:
            if key in ("href", "src") and value:
                self.links.append(value)


def all_generated_pages():
    pages = [ROOT / p for p in GENERATED_PAGES]
    pages += sorted(ROOT.glob("log/*/index.html"))
    return [p for p in pages if p.exists()]


def snapshot():
    """Text of every generated file, with volatile fields masked."""
    data = {}
    for path in all_generated_pages() + [ROOT / "rss.xml", ROOT / "sitemap.xml"]:
        if path.exists():
            text = path.read_text(encoding="utf-8")
            data[str(path.relative_to(ROOT))] = VOLATILE.sub("", text)
    return data


# ---------------------------------------------------------------- checks


def check_idempotent():
    step("build is idempotent (building twice changes nothing)")
    before = snapshot()
    result = subprocess.run(
        [sys.executable, "build.py"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        fail("second build failed:\n" + (result.stdout or "") + (result.stderr or ""))
        return
    after = snapshot()

    if before.keys() != after.keys():
        fail("second build produced a different set of files")
        return
    drifted = [name for name in before if before[name] != after[name]]
    if drifted:
        fail("these files changed on a second build with no source change: %s" % ", ".join(drifted))
    else:
        ok("%d generated files identical across two builds" % len(after))


def check_page_metadata():
    step("every page has the metadata it needs")
    required = [
        ("<title>", "a <title>"),
        ('name="description"', "a meta description"),
        ('property="og:title"', "an Open Graph title"),
        ('property="og:image"', "an Open Graph image"),
        ('rel="icon"', "a favicon link"),
        ("goatcounter", "the analytics script"),
    ]
    for page in all_generated_pages():
        text = page.read_text(encoding="utf-8")
        name = page.relative_to(ROOT)
        for needle, description in required:
            if needle not in text:
                fail("%s is missing %s" % (name, description))
        if not re.search(r"<h1[ >]", text):
            fail("%s has no <h1>" % name)
    if not failures:
        ok(
            "%d pages carry title, description, social tags, favicon, analytics, h1"
            % len(all_generated_pages())
        )


def check_feeds():
    step("rss.xml and sitemap.xml are valid")
    rss_path = ROOT / "rss.xml"
    try:
        rss = ET.fromstring(rss_path.read_text(encoding="utf-8"))
    except ET.ParseError as exc:
        fail("rss.xml is not valid XML: %s" % exc)
        return

    items = rss.findall(".//item")
    content_ns = "{http://purl.org/rss/1.0/modules/content/}encoded"
    for item in items:
        guid = item.findtext("guid") or ""
        if not guid.startswith("https://"):
            fail("an RSS item has a guid that is not an absolute URL: %r" % guid)
        body = item.find(content_ns)
        if body is None or not (body.text or "").strip():
            fail(
                "RSS item %r carries no full content — the newsletter would send an "
                "empty email" % item.findtext("title")
            )
    ok("rss.xml valid, %d item(s), all with absolute guids and full content" % len(items))

    try:
        sitemap = ET.fromstring((ROOT / "sitemap.xml").read_text(encoding="utf-8"))
    except ET.ParseError as exc:
        fail("sitemap.xml is not valid XML: %s" % exc)
        return
    ns = "{http://www.sitemaps.org/schemas/sitemap/0.9}"
    locs = [e.text for e in sitemap.findall("%surl/%sloc" % (ns, ns))]
    ok("sitemap.xml valid, %d URL(s)" % len(locs))


def check_internal_links():
    step("internal links point at files that exist")
    broken = 0
    for page in all_generated_pages():
        finder = LinkFinder()
        finder.feed(page.read_text(encoding="utf-8"))
        for link in finder.links:
            if link.startswith(("http://", "https://", "//", "mailto:", "#", "data:")):
                continue
            path = link.split("#")[0].split("?")[0]
            if not path.startswith("/"):
                fail(
                    "%s uses the relative link %r — use a root-absolute path (/...) "
                    "so page depth cannot break it" % (page.relative_to(ROOT), link)
                )
                broken += 1
                continue
            target = ROOT / path.lstrip("/")
            if path.endswith("/"):
                target = target / "index.html"
            if not target.exists():
                fail("%s links to %s, which does not exist" % (page.relative_to(ROOT), path))
                broken += 1
    if broken == 0:
        ok("no broken internal links")


def check_no_generated_files_tracked():
    step("generated files are not committed to git")
    result = subprocess.run(
        ["git", "ls-files"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    tracked = set((result.stdout or "").split())
    leaked = [
        name for name in ("index.html", "about.html", "rss.xml", "sitemap.xml") if name in tracked
    ] + [name for name in tracked if name.startswith("log/")]
    if leaked:
        fail(
            "these generated files are tracked by git and should not be: %s"
            % ", ".join(sorted(leaked))
        )
    else:
        ok("only sources are tracked")


def check_production_dependency_is_pinned():
    step("requirements.txt exists and pins an exact version")
    req = ROOT / "requirements.txt"
    if not req.exists():
        fail("requirements.txt is missing — Netlify's build command depends on it")
        return
    text = req.read_text(encoding="utf-8")
    if "markdown-it-py==" not in text:
        fail(
            "requirements.txt does not pin an exact markdown-it-py version — "
            "an unpinned dependency could change output on the next Netlify build "
            "with nothing to review locally first"
        )
    else:
        ok("markdown-it-py is version-pinned")


# ---------------------------------------------------------------- main


def main():
    run([sys.executable, "-m", "ruff", "check", "."], "ruff lint")
    run([sys.executable, "-m", "ruff", "format", "--check", "."], "ruff format")
    run([sys.executable, "-m", "pytest", "-q"], "pytest")
    run([sys.executable, "build.py"], "build")

    check_production_dependency_is_pinned()
    check_idempotent()
    check_page_metadata()
    check_feeds()
    check_internal_links()
    check_no_generated_files_tracked()

    print("\n" + "=" * 50)
    if failures:
        print("FAILED — %d problem(s):" % len(failures))
        for item in failures:
            print("  - %s" % item)
        return 1
    print("All checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
