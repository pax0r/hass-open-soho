#!/usr/bin/env python3
"""Report newer published stable releases without updating dependency pins."""

import json
import os
from pathlib import Path
import re
import sys
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
VERSION = re.compile(r"v?(\d+)\.(\d+)\.(\d+)$")
PROJECTS = {"OPENSOHO": "rubenbe/opensoho", "POCKETBASE": "pocketbase/pocketbase"}


def version(tag):
    match = VERSION.fullmatch(tag)
    return tuple(map(int, match.groups())) if match else None


def latest_stable(releases):
    stable = [
        release for release in releases
        if not release["draft"] and not release["prerelease"]
        and version(release["tag_name"]) is not None
    ]
    if not stable:
        raise ValueError("No published stable semantic version release was found")
    return max(stable, key=lambda release: version(release["tag_name"]))


def fetch_releases(repository):
    releases = []
    page = 1
    while True:
        request = Request(
            f"https://api.github.com/repos/{repository}/releases?per_page=100&page={page}",
            headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": "hass-open-soho-release-monitor",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        if token := os.environ.get("GITHUB_TOKEN"):
            request.add_header("Authorization", "Bearer " + token)
        with urlopen(request, timeout=30) as response:
            batch = json.load(response)
        releases.extend(batch)
        if len(batch) < 100:
            return releases
        page += 1


def main():
    pins = dict(
        line.split("=", 1)
        for line in (ROOT / "opensoho/upstream.env").read_text().splitlines()
        if line.strip() and not line.startswith("#")
    )
    lines = ["# Upstream stable releases", ""]
    newer = False
    for name, repository in PROJECTS.items():
        current = pins[name + "_RELEASE"]
        if version(current) is None:
            raise ValueError(f"Invalid pinned release for {repository}")
        release = latest_stable(fetch_releases(repository))
        tag = release["tag_name"]
        available = version(tag) > version(current)
        newer |= available
        status = "Update available" if available else "Up to date"
        lines.append(
            f"- {repository} — {status}. Pinned {current}, latest stable "
            f"[{tag}](https://github.com/{repository}/releases/tag/{tag})."
        )
    lines.extend(["", "Review release notes, source patches and PocketBase version alignment before updating."])
    report = "\n".join(lines) + "\n"
    print(report, end="")
    if summary := os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(summary, "a") as output:
            output.write(report)
    return 1 if newer else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f"Release check could not complete ({type(error).__name__}).", file=sys.stderr)
        sys.exit(2)
