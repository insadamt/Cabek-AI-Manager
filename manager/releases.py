"""Resolve published stable GitHub releases and download their exact source revision.

Depends on a read-capable GitHub token or an authenticated gh CLI. Ordinary tags,
drafts, and prereleases never become installation candidates.
"""
import json
import re
import shutil
import tarfile
import tempfile
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen


VERSION_PATTERN = re.compile(r"^v?(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")


def version_tuple(tag):
    match = VERSION_PATTERN.fullmatch(tag)
    return tuple(map(int, match.groups())) if match else None


def select_release(releases):
    candidates = [item for item in releases if not item.get("draft") and not item.get("prerelease")
                  and item.get("published_at") and version_tuple(item.get("tag_name", ""))]
    if not candidates:
        raise ValueError("No published stable release is available.")
    return max(candidates, key=lambda item: version_tuple(item["tag_name"]))


class GitHub:
    def __init__(self, runner, token=""):
        self.runner = runner
        self.token = token

    def request(self, path):
        if not self.token:
            return json.loads(self.runner.run(["gh", "api", path], timeout=45, quiet=True))
        request = Request("https://api.github.com/" + path, headers={
            "Authorization": "Bearer " + self.token, "Accept": "application/vnd.github+json",
            "User-Agent": "Cabek-AI-Manager",
        })
        try:
            with urlopen(request, timeout=30) as response:
                return json.load(response)
        except HTTPError as error:
            raise ValueError(f"GitHub request failed with HTTP {error.code}; check repository access.") from None

    def latest(self, repository):
        releases = []
        page = 1
        while True:
            batch = self.request(f"repos/{repository}/releases?per_page=100&page={page}")
            releases.extend(batch)
            if len(batch) < 100:
                break
            page += 1
        release = select_release(releases)
        tag = release["tag_name"]
        commit = self.request(f"repos/{repository}/commits/{tag}")
        return {"tag": tag, "sha": commit["sha"], "url": release["html_url"],
                "release_id": release["id"], "published_at": release["published_at"],
                "notes": release.get("body") or ""}

    def download(self, repository, revision, destination):
        destination = Path(destination)
        if destination.exists():
            raise ValueError("Release destination already exists.")
        destination.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=destination.parent) as temporary:
            archive = Path(temporary) / "source.tar.gz"
            path = f"repos/{repository}/tarball/{revision}"
            if self.token:
                request = Request("https://api.github.com/" + path,
                                  headers={"Authorization": "Bearer " + self.token, "User-Agent": "Cabek-AI-Manager"})
                with urlopen(request, timeout=120) as response, archive.open("wb") as stream:
                    shutil.copyfileobj(response, stream)
            else:
                # gh handles private archive redirects without writing authentication to disk.
                import subprocess
                with archive.open("wb") as stream:
                    result = subprocess.run(["gh", "api", path], stdout=stream, stderr=subprocess.PIPE, timeout=180)
                if result.returncode:
                    raise ValueError("Could not download the published release source.")
            extracted = Path(temporary) / "extracted"
            with tarfile.open(archive) as bundle:
                bundle.extractall(extracted, filter="data")
            roots = list(extracted.iterdir())
            if len(roots) != 1 or not roots[0].is_dir():
                raise ValueError("Unexpected GitHub source archive structure.")
            roots[0].rename(destination)
