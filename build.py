#!/usr/bin/env python3
"""
build.py — turns posts/*.md into the /log/ pages, keeps nav + the
homepage "latest log" teaser in sync, and regenerates the RSS feed.
No external packages needed.

Run it every time you add, edit, delete, or rename a file in posts/,
or after editing partials/nav.html:

    python build.py

SOURCE (edit these):
  - posts/*.md                 your writing
  - partials/*.html            page templates and the shared nav
  - assets/style.css           all styling

GENERATED (never edit — wiped and rewritten on every build):
  - index.html                 from partials/home-template.html
  - about.html                 from partials/about-template.html
  - log/index.html             the post list
  - log/<slug>/index.html      one directory per post
  - rss.xml                    full post content, for RSS-to-email
  - sitemap.xml

Post URLs are permanent: https://obssible.com/log/<slug>/
Locked 2026-08-06. The RSS <guid> is this URL and the newsletter service
uses it to decide what has already been sent — changing it would break
shared links and can cause duplicate sends.

See README.md for the full "how do I publish a new post" walkthrough.
"""

import html as htmllib
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).parent
POSTS_DIR = ROOT / "posts"
LOG_DIR = ROOT / "log"
PARTIALS_DIR = ROOT / "partials"

# Used only to build absolute links in rss.xml (RSS requires full URLs).
# Change this if the site ever moves to a different domain.
SITE_URL = "https://obssible.com"


# ---------------------------------------------------------------- markdown


def escape(text):
    return htmllib.escape(text, quote=False)


def inline_md(text):
    text = escape(text)
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"<em>\1</em>", text)
    text = re.sub(r"`(.+?)`", r"<code>\1</code>", text)
    text = re.sub(r"\[(.+?)\]\((.+?)\)", r'<a href="\2">\1</a>', text)
    return text


def md_to_html(md_text):
    lines = md_text.strip("\n").split("\n")
    blocks = []
    current = []
    for line in lines:
        if line.strip() == "":
            if current:
                blocks.append(current)
                current = []
        else:
            current.append(line)
    if current:
        blocks.append(current)

    out = []
    for block in blocks:
        first = block[0]
        if first.startswith("## "):
            out.append("<h2>%s</h2>" % inline_md(first[3:].strip()))
        elif all(row.startswith("> ") or row == ">" for row in block):
            quoted = " ".join(row[2:] if row.startswith("> ") else "" for row in block)
            out.append("<blockquote>%s</blockquote>" % inline_md(quoted.strip()))
        elif all(row.strip().startswith("- ") for row in block):
            items = "".join("<li>%s</li>" % inline_md(row.strip()[2:].strip()) for row in block)
            out.append("<ul>%s</ul>" % items)
        else:
            out.append("<p>%s</p>" % inline_md(" ".join(row.strip() for row in block)))
    return "\n".join(out)


# ---------------------------------------------------------------- posts


def parse_post(path):
    text = path.read_text(encoding="utf-8")
    meta = {}
    body = text
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            front = text[3:end].strip("\n")
            body = text[end + 4 :]
            for line in front.split("\n"):
                if ":" in line:
                    key, _, val = line.partition(":")
                    meta[key.strip().lower()] = val.strip()

    slug = meta.get("slug", "").strip()
    if not slug or "/" in slug or "\\" in slug or ".." in slug:
        if slug:
            print("  ! bad slug in %s, using filename instead" % path.name)
        slug = path.stem

    title = meta.get("title", slug)
    date = meta.get("date", "")
    if not date:
        print("  ! %s has no 'date:' in its frontmatter — it will sort last" % path.name)

    return {
        "slug": slug,
        "title": title,
        "date": date,
        "body_html": md_to_html(body),
    }


def load_posts():
    posts = [parse_post(p) for p in sorted(POSTS_DIR.glob("*.md"))]
    posts.sort(key=lambda p: p["date"], reverse=True)
    seen = {}
    for p in posts:
        if p["slug"] in seen:
            print("  ! two posts share the slug '%s' — one will overwrite the other" % p["slug"])
        seen[p["slug"]] = True
    return posts


# ---------------------------------------------------------------- nav


def render_nav(nav_html, current_path):
    def mark(m):
        href = m.group(1)
        if href == "/":
            is_current = current_path == "/"
        elif href.endswith("/"):
            is_current = current_path.startswith(href)
        else:
            is_current = current_path == href
        if is_current:
            return '<a href="%s" class="current">' % href
        return m.group(0)

    return re.sub(r'<a href="([^"]+)">', mark, nav_html)


def fill(template, values, template_name):
    """Substitute {{TOKEN}} placeholders. Fails loudly if any are left over."""
    out = template
    for key, value in values.items():
        out = out.replace("{{%s}}" % key, value)
    leftover = re.findall(r"\{\{([A-Z_]+)\}\}", out)
    if leftover:
        raise SystemExit(
            "BUILD FAILED: %s has unfilled placeholder(s): %s"
            % (template_name, ", ".join(sorted(set(leftover))))
        )
    return out


# ---------------------------------------------------------------- rss


def rfc822_date(date_str=None):
    if date_str:
        try:
            dt = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError:
            dt = datetime.now(timezone.utc)
    else:
        dt = datetime.now(timezone.utc)
    return dt.strftime("%a, %d %b %Y %H:%M:%S +0000")


def plain_excerpt(body_html, max_chars=200):
    """Strip tags to make a short plain-text summary for <description>."""
    text = re.sub(r"<[^>]+>", " ", body_html)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= max_chars:
        return text
    cut = text[:max_chars].rsplit(" ", 1)[0]
    return cut + "…"


def cdata(html_content):
    # "]]>" can't appear literally inside a CDATA block — split it if it does.
    safe = html_content.replace("]]>", "]]]]><![CDATA[>")
    return "<![CDATA[%s]]>" % safe


def post_url(slug):
    """The permanent public URL for a post. Locked 2026-08-06 — see README."""
    return "%s/log/%s/" % (SITE_URL, slug)


def build_sitemap(posts):
    urls = [
        ("%s/" % SITE_URL, None),
        ("%s/about.html" % SITE_URL, None),
        ("%s/log/" % SITE_URL, None),
    ]
    for p in posts:
        urls.append((post_url(p["slug"]), p["date"]))

    entries = []
    for loc, lastmod in urls:
        if lastmod:
            entries.append(
                "  <url>\n    <loc>%s</loc>\n    <lastmod>%s</lastmod>\n  </url>" % (loc, lastmod)
            )
        else:
            entries.append("  <url>\n    <loc>%s</loc>\n  </url>" % loc)

    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        "%s\n"
        "</urlset>\n" % "\n".join(entries)
    )


def build_rss(posts):
    items = []
    for p in posts:
        link = post_url(p["slug"])
        items.append(
            "  <item>\n"
            "    <title>%s</title>\n"
            "    <link>%s</link>\n"
            "    <guid>%s</guid>\n"
            "    <pubDate>%s</pubDate>\n"
            "    <description>%s</description>\n"
            "    <content:encoded>%s</content:encoded>\n"
            "  </item>"
            % (
                escape(p["title"]),
                link,
                link,
                rfc822_date(p["date"]),
                escape(plain_excerpt(p["body_html"])),
                cdata(p["body_html"]),
            )
        )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/">\n'
        "<channel>\n"
        "  <title>Junwoo — Log</title>\n"
        "  <link>%s/log/</link>\n"
        "  <description>Every immersion session, published as it happens.</description>\n"
        "  <language>en</language>\n"
        "  <lastBuildDate>%s</lastBuildDate>\n"
        "%s\n"
        "</channel>\n"
        "</rss>\n" % (SITE_URL, rfc822_date(), "\n".join(items))
    )


# ---------------------------------------------------------------- main


def clean_generated():
    """Delete previously generated output so stale files can never linger."""
    if LOG_DIR.exists():
        shutil.rmtree(LOG_DIR)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    for name in ("index.html", "about.html", "rss.xml", "sitemap.xml", "feed.xml"):
        target = ROOT / name
        if target.exists():
            target.unlink()


def main():
    nav_raw = (PARTIALS_DIR / "nav.html").read_text(encoding="utf-8").strip()
    post_tpl = (PARTIALS_DIR / "post-template.html").read_text(encoding="utf-8")
    list_tpl = (PARTIALS_DIR / "list-template.html").read_text(encoding="utf-8")
    home_tpl = (PARTIALS_DIR / "home-template.html").read_text(encoding="utf-8")
    about_tpl = (PARTIALS_DIR / "about-template.html").read_text(encoding="utf-8")

    posts = load_posts()
    print("Found %d post(s) in posts/" % len(posts))

    clean_generated()

    # ---- log/<slug>/index.html, one directory per post ----
    for post in posts:
        slug = post["slug"]
        page = fill(
            post_tpl,
            {
                "NAV": render_nav(nav_raw, "/log/%s/" % slug),
                "TITLE": escape(post["title"]),
                "DATE": escape(post["date"]),
                "BODY": post["body_html"],
                "DESCRIPTION": escape(plain_excerpt(post["body_html"])),
                "URL": post_url(slug),
            },
            "post-template.html",
        )
        out_dir = LOG_DIR / slug
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "index.html").write_text(page, encoding="utf-8")
        print("  wrote log/%s/index.html" % slug)

    # ---- log/index.html ----
    if posts:
        items = "\n".join(
            '    <li><a href="/log/%s/"><span class="log-list-date">%s</span>'
            '<span class="log-list-title">%s</span></a></li>'
            % (p["slug"], escape(p["date"]), escape(p["title"]))
            for p in posts
        )
    else:
        items = (
            '    <li><span class="log-list-date">—</span>'
            '<span class="log-list-title">No logs yet.</span></li>'
        )
    (LOG_DIR / "index.html").write_text(
        fill(
            list_tpl,
            {"NAV": render_nav(nav_raw, "/log/"), "ITEMS": items},
            "list-template.html",
        ),
        encoding="utf-8",
    )
    print("  wrote log/index.html")

    # ---- rss.xml ----
    (ROOT / "rss.xml").write_text(build_rss(posts), encoding="utf-8")
    print("  wrote rss.xml (%d item%s)" % (len(posts), "" if len(posts) == 1 else "s"))

    # ---- sitemap.xml ----
    (ROOT / "sitemap.xml").write_text(build_sitemap(posts), encoding="utf-8")
    print("  wrote sitemap.xml")

    # ---- index.html ----
    if posts:
        latest = posts[0]
        latest_html = (
            '  <p><a href="/log/%s/">%s</a></p>\n'
            '  <p class="status">%s — <a href="/log/">See all logs →</a></p>'
            % (latest["slug"], escape(latest["title"]), escape(latest["date"]))
        )
    else:
        latest_html = '  <p><a href="/log/">See all logs →</a></p>'
    (ROOT / "index.html").write_text(
        fill(
            home_tpl,
            {"NAV": render_nav(nav_raw, "/"), "LATEST": latest_html},
            "home-template.html",
        ),
        encoding="utf-8",
    )
    print("  wrote index.html")

    # ---- about.html ----
    (ROOT / "about.html").write_text(
        fill(about_tpl, {"NAV": render_nav(nav_raw, "/about.html")}, "about-template.html"),
        encoding="utf-8",
    )
    print("  wrote about.html")

    print("Done.")


if __name__ == "__main__":
    sys.exit(main())
