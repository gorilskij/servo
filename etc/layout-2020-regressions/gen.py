#!/usr/bin/env python

import json
import os
import re
import subprocess
import sys
import urllib.request
from html import escape as html_escape


TASKCLUSTER_ROOT_URL = "https://community-tc.services.mozilla.com"


def fetch(url):
    url = TASKCLUSTER_ROOT_URL + "/api/" + url
    print("Fetching " + url)
    response = urllib.request.urlopen(url)
    assert response.getcode() == 200
    return response


def fetch_json(url):
    with fetch(url) as response:
        return json.load(response)


def task(platform, chunk, key):
    return "index/v1/task/project.servo.%s_wpt_%s.%s" % (platform, chunk, key)


def failing_reftests(platform, key):
    chunk_1_task_id = fetch_json(task(platform, 1, key))["taskId"]
    name = fetch_json("queue/v1/task/" + chunk_1_task_id)["metadata"]["name"]
    match = re.search("WPT chunk (\d+) / (\d+)", name)
    assert match.group(1) == "1"
    total_chunks = int(match.group(2))

    for chunk in range(1, total_chunks + 1):
        with fetch(task(platform, chunk, key) + "/artifacts/public/test-wpt.log") as response:
            for line in response:
                message = json.loads(line)
                if message.get("status") not in {None, "OK", "PASS"}:
                    screenshots = message.get("extra", {}).get("reftest_screenshots")
                    if screenshots:
                        yield message["test"], screenshots


def main(index_key, commit_sha):
    failures_2013 = {url for url, _ in failing_reftests("linux_x64", index_key)}
    failures_2020 = Directory()
    for url, screenshots in failing_reftests("linux_x64_2020", index_key):
        if url not in failures_2013:
            assert url.startswith("/")
            failures_2020.add(url[1:], screenshots)

    here = os.path.dirname(__file__)
    with open(os.path.join(here, "prism.js")) as f:
        prism_js = f.read()
    with open(os.path.join(here, "prism.css")) as f:
        prism_css = f.read()
    with open(os.path.join(here, "regressions.html"), "w", encoding="utf-8") as html:
        os.chdir(os.path.join(here, "../../tests/wpt"))
        html.write("""
            <!doctype html>
            <meta charset=utf-8>
            <title>Layout 2020 regressions</title>
            <link rel=stylesheet href=prism.css>
            <style>
                ul { padding-left: 1em }
                li { list-style: "⯈ " }
                li.expanded { list-style: "⯆ " }
                li:not(.expanded) > ul, li:not(.expanded) > div { display: none }
                li > div { display: grid; grid-gap: 1em; grid-template-columns: 1fr 1fr }
                li > div > p { grid-column: span 2 }
                li > div > img { grid-row: 2; width: 300px; box-shadow: 0 0 10px }
                li > div > img:hover { transform: scale(3); transform-origin: 0 0 }
                li > div > pre { grid-row: 3; font-size: 12px !important }
                pre code { white-space: pre-wrap !important }
                %s
            </style>
            <h1>Layout 2020 regressions in tree <code>%s</code></h1>
        """ % (prism_css, commit_sha))
        failures_2020.write(html)
        html.write("""
            <script>
                for (let li of document.getElementsByTagName("li")) {
                    li.addEventListener('click', event => {
                        li.classList.toggle("expanded")
                        event.stopPropagation()
                    })
                }
                %s
            </script>
        """ % prism_js)


class Directory:
    def __init__(self):
        self.count = 0
        self.contents = {}

    def add(self, path, screenshots):
        self.count += 1
        first, _, rest = path.partition("/")
        if rest:
            self.contents.setdefault(first, Directory()).add(rest, screenshots)
        else:
            assert path not in self.contents
            self.contents[path] = screenshots

    def write(self, html):
        html.write("<ul>\n")
        for k, v in self.contents.items():
            html.write("<li><code>%s</code>\n" % k)
            if isinstance(v, Directory):
                html.write("<strong>%s</strong>\n" % v.count)
                v.write(html)
            else:
                a, rel, b = v
                html.write("<div>\n<p><code>%s</code> %s <code>%s</code></p>\n"
                           % (a["url"], rel, b["url"]))
                for side in [a, b]:
                    html.write("<img src='data:image/png;base64,%s'>\n" % side["screenshot"])
                    url = side["url"]
                    prefix = "/_mozilla/"
                    if url.startswith(prefix):
                        filename = "mozilla/tests/" + url[len(prefix):]
                    else:
                        filename = "web-platform-tests" + url
                    with open(filename, encoding="utf-8") as f:
                        src = html_escape(f.read())
                        html.write("<pre><code class=language-html>%s</code></pre>\n" % src)
            html.write("</li>\n")
        html.write("</ul>\n")


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:]))
