"""Tests for top-level ``apm add`` and ``apm remove`` commands.

These commands alias the legacy ``apm marketplace add`` /
``apm marketplace remove`` surface (issue #1075). Behavior:

  * ``apm add OWNER/REPO [OWNER/REPO ...]`` - register one or more sources.
  * ``apm remove NAME`` - unregister a registered source.
  * Multi-source: continue-on-error for non-security failures, fail-closed
    for security-class failures (path traversal, signature errors).
  * Bare-name typo (no ``/``) emits a smart error suggesting ``apm install``.
  * ``--name`` is mutually exclusive with multiple positional sources.
  * Legacy commands keep working but emit a one-line stderr tip on success.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from click.testing import CliRunner

from apm_cli.marketplace.models import (
    MarketplaceManifest,
    MarketplacePlugin,
)
from apm_cli.utils.path_security import PathTraversalError


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture(autouse=True)
def _isolate_config(tmp_path, monkeypatch):
    """Isolate filesystem writes (mirrors marketplace test conftest)."""
    config_dir = str(tmp_path / ".apm")
    monkeypatch.setattr("apm_cli.config.CONFIG_DIR", config_dir)
    monkeypatch.setattr("apm_cli.config.CONFIG_FILE", str(tmp_path / ".apm" / "config.json"))
    monkeypatch.setattr("apm_cli.config._config_cache", None)
    monkeypatch.setattr("apm_cli.marketplace.registry._registry_cache", None)


def _manifest(plugin_count: int = 1, name: str = "test-marketplace") -> MarketplaceManifest:
    plugins = tuple(MarketplacePlugin(name=f"p{i}") for i in range(plugin_count))
    return MarketplaceManifest(name=name, plugins=plugins)


# ---------------------------------------------------------------------------
# apm add - top-level command
# ---------------------------------------------------------------------------


class TestApmAddSingleSource:
    """``apm add OWNER/REPO`` - single-source happy path."""

    @patch("apm_cli.marketplace.registry.add_marketplace")
    @patch("apm_cli.marketplace.client.fetch_marketplace")
    @patch("apm_cli.marketplace.client._auto_detect_path")
    def test_single_source_registers(self, mock_detect, mock_fetch, mock_add, runner):
        from apm_cli.cli import cli

        mock_detect.return_value = "marketplace.json"
        mock_fetch.return_value = _manifest()

        result = runner.invoke(cli, ["add", "acme/plugins"])

        assert result.exit_code == 0, result.output
        assert mock_add.call_count == 1
        registered = mock_add.call_args[0][0]
        assert registered.owner == "acme"
        assert registered.repo == "plugins"

    @patch("apm_cli.marketplace.registry.add_marketplace")
    @patch("apm_cli.marketplace.client.fetch_marketplace")
    @patch("apm_cli.marketplace.client._auto_detect_path")
    def test_single_source_no_deprecation_tip(self, mock_detect, mock_fetch, mock_add, runner):
        """Top-level ``apm add`` MUST NOT print the legacy deprecation tip."""
        from apm_cli.cli import cli

        mock_detect.return_value = "marketplace.json"
        mock_fetch.return_value = _manifest()

        result = runner.invoke(cli, ["add", "acme/plugins"])

        assert result.exit_code == 0, result.output
        # No tip in either stream.
        assert "now available as a top-level command" not in result.output
        assert "now available as a top-level command" not in (result.stderr or "")


class TestApmAddBareName:
    """``apm add cool-plugin`` (no slash) - smart error path."""

    def test_bare_name_errors(self, runner):
        from apm_cli.cli import cli

        result = runner.invoke(cli, ["add", "cool-plugin"])

        assert result.exit_code != 0
        # Error must mention OWNER/REPO format AND suggest apm install.
        out = result.output
        assert "OWNER/REPO" in out
        assert "apm install" in out

    def test_bare_name_does_not_call_registry(self, runner):
        from apm_cli.cli import cli

        with patch("apm_cli.marketplace.registry.add_marketplace") as mock_add:
            result = runner.invoke(cli, ["add", "cool-plugin"])
        assert result.exit_code != 0
        mock_add.assert_not_called()


class TestApmAddMultiSource:
    """``apm add A/B C/D`` - multi-source semantics."""

    @patch("apm_cli.marketplace.registry.add_marketplace")
    @patch("apm_cli.marketplace.client.fetch_marketplace")
    @patch("apm_cli.marketplace.client._auto_detect_path")
    def test_multi_source_all_succeed(self, mock_detect, mock_fetch, mock_add, runner):
        from apm_cli.cli import cli

        mock_detect.return_value = "marketplace.json"
        mock_fetch.return_value = _manifest()

        result = runner.invoke(cli, ["add", "acme/plugins", "contoso/security"])

        assert result.exit_code == 0, result.output
        assert mock_add.call_count == 2
        # Summary line after two registrations.
        assert "2 registered" in result.output

    @patch("apm_cli.marketplace.registry.add_marketplace")
    @patch("apm_cli.marketplace.client.fetch_marketplace")
    @patch("apm_cli.marketplace.client._auto_detect_path")
    def test_multi_source_partial_non_security_failure(
        self, mock_detect, mock_fetch, mock_add, runner
    ):
        """Non-security failure on one source must not abort the batch."""
        from apm_cli.cli import cli

        mock_detect.side_effect = [None, "marketplace.json"]
        mock_fetch.return_value = _manifest()

        result = runner.invoke(cli, ["add", "bad/repo", "good/repo"])

        # Exit code non-zero because one failed.
        assert result.exit_code != 0
        # Second source still attempted.
        assert mock_add.call_count == 1
        # Summary indicates 1 success, 1 failure.
        assert "1 registered" in result.output
        assert "1 failed" in result.output

    @patch("apm_cli.marketplace.registry.add_marketplace")
    @patch("apm_cli.marketplace.client.fetch_marketplace")
    @patch("apm_cli.marketplace.client._auto_detect_path")
    def test_multi_source_security_failure_aborts_batch(
        self, mock_detect, mock_fetch, mock_add, runner
    ):
        """Security-class failure must fail-closed and skip remaining sources."""
        from apm_cli.cli import cli

        mock_detect.side_effect = PathTraversalError("traversal in 'evil/../repo'")

        result = runner.invoke(cli, ["add", "evil/repo", "good/repo"])

        assert result.exit_code != 0
        # Second source must NOT be processed.
        assert mock_add.call_count == 0

    @patch("apm_cli.marketplace.registry.add_marketplace")
    @patch("apm_cli.marketplace.client.fetch_marketplace")
    @patch("apm_cli.marketplace.client._auto_detect_path")
    def test_name_flag_with_multi_source_errors(self, mock_detect, mock_fetch, mock_add, runner):
        """``--name`` requires exactly one positional source."""
        from apm_cli.cli import cli

        result = runner.invoke(cli, ["add", "--name", "alias", "a/b", "c/d"])

        assert result.exit_code != 0
        assert "--name" in result.output
        # No registration should have been attempted.
        mock_add.assert_not_called()


class TestApmAddHelp:
    """``apm add --help`` - help-text contract."""

    def test_help_shows_usage(self, runner):
        from apm_cli.cli import cli

        result = runner.invoke(cli, ["add", "--help"])
        assert result.exit_code == 0
        # Multi-source signature visible.
        assert "OWNER/REPO" in result.output


# ---------------------------------------------------------------------------
# apm remove - top-level command
# ---------------------------------------------------------------------------


class TestApmRemove:
    """``apm remove NAME``."""

    @patch("apm_cli.marketplace.client.clear_marketplace_cache")
    @patch("apm_cli.marketplace.registry.remove_marketplace")
    @patch("apm_cli.marketplace.registry.get_marketplace_by_name")
    def test_remove_with_yes_flag(self, mock_get, mock_remove, mock_clear, runner):
        from apm_cli.cli import cli
        from apm_cli.marketplace.models import MarketplaceSource

        mock_get.return_value = MarketplaceSource(
            name="my-source", owner="acme", repo="plugins", branch="main", host="github.com"
        )

        result = runner.invoke(cli, ["remove", "my-source", "--yes"])

        assert result.exit_code == 0, result.output
        mock_remove.assert_called_once_with("my-source")

    @patch("apm_cli.marketplace.client.clear_marketplace_cache")
    @patch("apm_cli.marketplace.registry.remove_marketplace")
    @patch("apm_cli.marketplace.registry.get_marketplace_by_name")
    def test_remove_no_deprecation_tip(self, mock_get, mock_remove, mock_clear, runner):
        from apm_cli.cli import cli
        from apm_cli.marketplace.models import MarketplaceSource

        mock_get.return_value = MarketplaceSource(
            name="my-source", owner="acme", repo="plugins", branch="main", host="github.com"
        )

        result = runner.invoke(cli, ["remove", "my-source", "--yes"])

        assert result.exit_code == 0, result.output
        assert "now available as a top-level command" not in result.output
        assert "now available as a top-level command" not in (result.stderr or "")


# ---------------------------------------------------------------------------
# Legacy aliases - apm marketplace add/remove keep working with stderr tip
# ---------------------------------------------------------------------------


class TestLegacyDeprecationTip:
    """Legacy ``apm marketplace add/remove`` MUST emit a single stderr tip on success."""

    @patch("apm_cli.marketplace.registry.add_marketplace")
    @patch("apm_cli.marketplace.client.fetch_marketplace")
    @patch("apm_cli.marketplace.client._auto_detect_path")
    def test_marketplace_add_emits_tip_on_success(self, mock_detect, mock_fetch, mock_add, runner):
        from apm_cli.commands.marketplace import marketplace

        mock_detect.return_value = "marketplace.json"
        mock_fetch.return_value = _manifest()

        result = runner.invoke(marketplace, ["add", "acme/plugins"])

        assert result.exit_code == 0, result.output
        # Tip is on stderr only.
        assert "apm add" in (result.stderr or "")

    def test_marketplace_add_no_tip_on_error(self, runner):
        from apm_cli.commands.marketplace import marketplace

        result = runner.invoke(marketplace, ["add", "just-a-name"])
        assert result.exit_code != 0
        assert "apm add" not in (result.stderr or "")

    @patch("apm_cli.marketplace.client.clear_marketplace_cache")
    @patch("apm_cli.marketplace.registry.remove_marketplace")
    @patch("apm_cli.marketplace.registry.get_marketplace_by_name")
    def test_marketplace_remove_emits_tip_on_success(
        self, mock_get, mock_remove, mock_clear, runner
    ):
        from apm_cli.commands.marketplace import marketplace
        from apm_cli.marketplace.models import MarketplaceSource

        mock_get.return_value = MarketplaceSource(
            name="my-source", owner="acme", repo="plugins", branch="main", host="github.com"
        )

        result = runner.invoke(marketplace, ["remove", "my-source", "--yes"])
        assert result.exit_code == 0, result.output
        assert "apm remove" in (result.stderr or "")


class TestLegacyHelpText:
    """Legacy commands' ``--help`` output advertises the alias."""

    def test_marketplace_add_help_mentions_alias(self, runner):
        from apm_cli.commands.marketplace import marketplace

        result = runner.invoke(marketplace, ["add", "--help"])
        assert result.exit_code == 0
        assert "alias" in result.output.lower()
        assert "apm add" in result.output

    def test_marketplace_remove_help_mentions_alias(self, runner):
        from apm_cli.commands.marketplace import marketplace

        result = runner.invoke(marketplace, ["remove", "--help"])
        assert result.exit_code == 0
        assert "alias" in result.output.lower()
        assert "apm remove" in result.output
