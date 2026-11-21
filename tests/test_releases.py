"""Verify release eligibility and immutable revision selection without live GitHub requests.

Depends on GitHub DTOs; protects the published-release-only update requirement.
"""
import pytest

from manager.releases import GitHub, select_release, version_tuple
from manager.commands import CommandRunner


def release(tag="v1.2.3", **changes):
    return {"id": 1, "tag_name": tag, "draft": False, "prerelease": False,
            "published_at": "2026-11-21T12:00:00Z", "html_url": "https://github.com/example/releases/1", **changes}


@pytest.mark.parametrize("item", [release(draft=True), release(prerelease=True), release(published_at=None),
                                  release("v2.0.0-beta.1"), release("latest"), release("v01.2.3")])
def test_unpublished_and_prerelease_versions_are_not_updates(item):
    with pytest.raises(ValueError, match="No published stable"):
        select_release([item])


def test_highest_semantic_version_wins_over_publication_order():
    assert select_release([release("v1.9.9"), release("v1.10.0"), release("v2.0.0", draft=True)])["tag_name"] == "v1.10.0"


def test_resolves_commit_from_published_release_tag():
    calls = []
    class Client(GitHub):
        def request(self, path):
            calls.append(path)
            return [release()] if "/releases?" in path else {"sha": "a" * 40}
    result = Client(CommandRunner()).latest("owner/repository")
    assert result["sha"] == "a" * 40
    assert calls == ["repos/owner/repository/releases?per_page=100&page=1", "repos/owner/repository/commits/v1.2.3"]


def test_version_comparison_is_numeric():
    assert version_tuple("v1.10.0") > version_tuple("v1.9.0")
