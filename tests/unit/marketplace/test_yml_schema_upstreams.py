"""Schema tests for the marketplace ``upstreams:`` block and the
upstream-sourced ``packages[]`` shape (issue #1136).

These tests cover the type-level discriminated union introduced for
upstream marketplace pass-through: parsing both shapes side-by-side,
strict per-shape key validation, alias/host/repo validation, and
cross-validation between ``packages`` and ``upstreams`` blocks.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from apm_cli.marketplace.errors import MarketplaceYmlError
from apm_cli.marketplace.yml_schema import (
    MarketplacePackage,  # noqa: F401  -- re-exported public alias
    PackageEntry,
    Upstream,
    UpstreamPackageEntry,
    load_marketplace_yml,
)


def _write_yml(tmp_path: Path, content: str) -> Path:
    p = tmp_path / "marketplace.yml"
    p.write_text(textwrap.dedent(content), encoding="utf-8")
    return p


_BASE = """\
name: acme-tools
description: Acme marketplace
version: 1.0.0
owner:
  name: Acme Corp
"""


class TestUpstreamRegistration:
    def test_minimal_with_ref(self, tmp_path: Path):
        yml = _write_yml(
            tmp_path,
            _BASE
            + """\
upstreams:
  - alias: gitnexus
    repo: abhigyanpatwari/GitNexus
    ref: 0123456789abcdef0123456789abcdef01234567
packages:
  - name: tool-a
    source: acme/tool-a
    version: ">=1.0.0"
""",
        )
        result = load_marketplace_yml(yml)
        assert len(result.upstreams) == 1
        u = result.upstreams[0]
        assert u.alias == "gitnexus"
        assert u.repo == "abhigyanpatwari/GitNexus"
        assert u.path == ".claude-plugin/marketplace.json"
        assert u.branch == "main"
        assert u.host == "github.com"
        assert u.allow_head is False
        assert u.ref is not None

    def test_allow_head_without_ref_is_permitted(self, tmp_path: Path):
        yml = _write_yml(
            tmp_path,
            _BASE
            + """\
upstreams:
  - alias: dev
    repo: org/dev-marketplace
    allow_head: true
    branch: develop
packages:
  - name: tool-a
    source: acme/tool-a
    version: ">=1.0.0"
""",
        )
        result = load_marketplace_yml(yml)
        u = result.upstreams[0]
        assert u.allow_head is True
        assert u.branch == "develop"
        assert u.ref is None

    def test_missing_ref_without_allow_head_rejected(self, tmp_path: Path):
        yml = _write_yml(
            tmp_path,
            _BASE
            + """\
upstreams:
  - alias: floats
    repo: org/floats
packages: []
""",
        )
        with pytest.raises(MarketplaceYmlError, match=r"'ref' is required"):
            load_marketplace_yml(yml)

    def test_invalid_alias_rejected(self, tmp_path: Path):
        yml = _write_yml(
            tmp_path,
            _BASE
            + """\
upstreams:
  - alias: "bad alias!"
    repo: org/repo
    ref: abc123
packages: []
""",
        )
        with pytest.raises(MarketplaceYmlError, match="not a valid alias"):
            load_marketplace_yml(yml)

    def test_invalid_repo_shape_rejected(self, tmp_path: Path):
        yml = _write_yml(
            tmp_path,
            _BASE
            + """\
upstreams:
  - alias: u
    repo: "./local"
    ref: abc
packages: []
""",
        )
        with pytest.raises(MarketplaceYmlError, match="<owner>/<repo>"):
            load_marketplace_yml(yml)

    def test_path_traversal_rejected(self, tmp_path: Path):
        yml = _write_yml(
            tmp_path,
            _BASE
            + """\
upstreams:
  - alias: u
    repo: org/repo
    ref: abc
    path: "../escape/marketplace.json"
packages: []
""",
        )
        with pytest.raises(MarketplaceYmlError):
            load_marketplace_yml(yml)

    def test_invalid_host_rejected(self, tmp_path: Path):
        yml = _write_yml(
            tmp_path,
            _BASE
            + """\
upstreams:
  - alias: u
    repo: org/repo
    ref: abc
    host: "not a host"
packages: []
""",
        )
        with pytest.raises(MarketplaceYmlError, match="not a valid hostname"):
            load_marketplace_yml(yml)

    def test_unknown_key_rejected(self, tmp_path: Path):
        yml = _write_yml(
            tmp_path,
            _BASE
            + """\
upstreams:
  - alias: u
    repo: org/repo
    ref: abc
    typo_key: value
packages: []
""",
        )
        with pytest.raises(MarketplaceYmlError, match="Unknown key"):
            load_marketplace_yml(yml)

    def test_duplicate_alias_rejected(self, tmp_path: Path):
        yml = _write_yml(
            tmp_path,
            _BASE
            + """\
upstreams:
  - alias: u
    repo: org/a
    ref: abc
  - alias: u
    repo: org/b
    ref: def
packages: []
""",
        )
        with pytest.raises(MarketplaceYmlError, match="Duplicate upstream alias"):
            load_marketplace_yml(yml)


class TestUpstreamPackageEntry:
    def test_minimal_upstream_package(self, tmp_path: Path):
        yml = _write_yml(
            tmp_path,
            _BASE
            + """\
upstreams:
  - alias: gitnexus
    repo: abhigyanpatwari/GitNexus
    ref: abc123
packages:
  - name: gitnexus
    upstream: gitnexus
    version: ">=1.0.0"
""",
        )
        result = load_marketplace_yml(yml)
        assert len(result.packages) == 1
        e = result.packages[0]
        assert isinstance(e, UpstreamPackageEntry)
        assert e.name == "gitnexus"
        assert e.upstream_alias == "gitnexus"
        assert e.plugin is None
        assert e.allow_head is False

    def test_upstream_package_with_overrides(self, tmp_path: Path):
        yml = _write_yml(
            tmp_path,
            _BASE
            + """\
upstreams:
  - alias: gitnexus
    repo: abhigyanpatwari/GitNexus
    ref: abc123
packages:
  - name: my-renamed
    upstream: gitnexus
    plugin: original
    ref: feedface
    description: "ACME-curated"
    tags: [acme, approved]
""",
        )
        result = load_marketplace_yml(yml)
        e = result.packages[0]
        assert isinstance(e, UpstreamPackageEntry)
        assert e.name == "my-renamed"
        assert e.plugin == "original"
        assert e.ref == "feedface"
        assert e.description == "ACME-curated"
        assert e.tags == ("acme", "approved")

    def test_source_and_upstream_mutex(self, tmp_path: Path):
        yml = _write_yml(
            tmp_path,
            _BASE
            + """\
upstreams:
  - alias: u
    repo: org/repo
    ref: abc
packages:
  - name: confused
    source: acme/x
    upstream: u
""",
        )
        with pytest.raises(MarketplaceYmlError, match="mutually exclusive"):
            load_marketplace_yml(yml)

    def test_neither_source_nor_upstream_rejected(self, tmp_path: Path):
        yml = _write_yml(
            tmp_path,
            _BASE
            + """\
packages:
  - name: orphan
    version: ">=1.0.0"
""",
        )
        with pytest.raises(MarketplaceYmlError, match="exactly one of"):
            load_marketplace_yml(yml)

    def test_subdir_on_upstream_rejected(self, tmp_path: Path):
        yml = _write_yml(
            tmp_path,
            _BASE
            + """\
upstreams:
  - alias: u
    repo: org/repo
    ref: abc
packages:
  - name: bad
    upstream: u
    subdir: nested
""",
        )
        with pytest.raises(MarketplaceYmlError, match="Unknown key"):
            load_marketplace_yml(yml)

    def test_version_and_ref_mutex(self, tmp_path: Path):
        yml = _write_yml(
            tmp_path,
            _BASE
            + """\
upstreams:
  - alias: u
    repo: org/repo
    ref: abc
packages:
  - name: bad
    upstream: u
    version: ">=1.0.0"
    ref: feedface
""",
        )
        with pytest.raises(MarketplaceYmlError, match="mutually exclusive"):
            load_marketplace_yml(yml)

    def test_unknown_alias_rejected(self, tmp_path: Path):
        yml = _write_yml(
            tmp_path,
            _BASE
            + """\
upstreams:
  - alias: known
    repo: org/repo
    ref: abc
packages:
  - name: x
    upstream: undeclared
    version: ">=1.0.0"
""",
        )
        with pytest.raises(MarketplaceYmlError, match="not declared"):
            load_marketplace_yml(yml)

    def test_invalid_alias_in_package_rejected(self, tmp_path: Path):
        yml = _write_yml(
            tmp_path,
            _BASE
            + """\
upstreams:
  - alias: u
    repo: org/repo
    ref: abc
packages:
  - name: x
    upstream: "bad alias!"
    version: ">=1.0.0"
""",
        )
        with pytest.raises(MarketplaceYmlError, match="not a valid alias"):
            load_marketplace_yml(yml)


class TestMixedPackages:
    def test_direct_and_upstream_coexist(self, tmp_path: Path):
        yml = _write_yml(
            tmp_path,
            _BASE
            + """\
upstreams:
  - alias: gitnexus
    repo: abhigyanpatwari/GitNexus
    ref: abc123
packages:
  - name: direct-tool
    source: acme/direct-tool
    version: ">=1.0.0"
  - name: upstream-tool
    upstream: gitnexus
    plugin: gitnexus
    version: ">=2.0.0"
""",
        )
        result = load_marketplace_yml(yml)
        assert len(result.packages) == 2
        direct, upstream = result.packages
        assert isinstance(direct, PackageEntry)
        assert direct.source == "acme/direct-tool"
        assert isinstance(upstream, UpstreamPackageEntry)
        assert upstream.plugin == "gitnexus"

    def test_cross_shape_name_uniqueness(self, tmp_path: Path):
        """Direct and upstream entries cannot share a name (panel:
        prevents dependency-confusion / shadowing)."""
        yml = _write_yml(
            tmp_path,
            _BASE
            + """\
upstreams:
  - alias: u
    repo: org/repo
    ref: abc
packages:
  - name: shared
    source: acme/local
    version: ">=1.0.0"
  - name: shared
    upstream: u
    version: ">=1.0.0"
""",
        )
        with pytest.raises(MarketplaceYmlError, match="Duplicate package name"):
            load_marketplace_yml(yml)

    def test_duplicate_upstream_pair_rejected(self, tmp_path: Path):
        yml = _write_yml(
            tmp_path,
            _BASE
            + """\
upstreams:
  - alias: u
    repo: org/repo
    ref: abc
packages:
  - name: alpha
    upstream: u
    plugin: shared
    version: ">=1.0.0"
  - name: beta
    upstream: u
    plugin: shared
    version: ">=1.0.0"
""",
        )
        with pytest.raises(MarketplaceYmlError, match="Duplicate upstream package"):
            load_marketplace_yml(yml)

    def test_no_upstreams_no_breakage(self, tmp_path: Path):
        """A marketplace.yml without ``upstreams:`` and without any
        upstream-shape package still parses unchanged -- proves the
        feature is purely additive for existing curators."""
        yml = _write_yml(
            tmp_path,
            _BASE
            + """\
packages:
  - name: tool-a
    source: acme/tool-a
    version: ">=1.0.0"
""",
        )
        result = load_marketplace_yml(yml)
        assert result.upstreams == ()
        assert len(result.packages) == 1
        assert isinstance(result.packages[0], PackageEntry)


class TestUpstreamDataclassDefaults:
    def test_upstream_defaults(self):
        u = Upstream(alias="x", repo="o/r", ref="abc")
        assert u.path == ".claude-plugin/marketplace.json"
        assert u.branch == "main"
        assert u.host == "github.com"
        assert u.allow_head is False

    def test_upstream_package_defaults(self):
        e = UpstreamPackageEntry(name="x", upstream_alias="y")
        assert e.plugin is None
        assert e.allow_head is False
        assert e.tags == ()
        assert e.include_prerelease is False
