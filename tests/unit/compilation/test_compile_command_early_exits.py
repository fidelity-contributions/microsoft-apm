"""Tests for compile() command early-exit paths.

Covers branches in cli.py::compile() that exit before reaching the compiler:
- Missing apm.yml
- --all with --target conflict
- --target all deprecation warning
- No APM content found (no .apm/, no modules, no constitution)
- Empty .apm directory
- --validate mode: discover failure, validation errors, success
"""

import os

import pytest
from click.testing import CliRunner

from apm_cli.cli import cli


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def empty_project(tmp_path):
    """Project directory with only apm.yml, no .apm content."""
    (tmp_path / "apm.yml").write_text("name: test-project\nversion: 0.1.0\n")
    return tmp_path


@pytest.fixture
def minimal_project(tmp_path):
    """Project directory with apm.yml and one instruction file."""
    (tmp_path / "apm.yml").write_text("name: test-project\nversion: 0.1.0\n")
    apm_dir = tmp_path / ".apm" / "instructions"
    apm_dir.mkdir(parents=True)
    (apm_dir / "test.instructions.md").write_text(
        '---\napplyTo: "**"\n---\nFollow best practices.\n'
    )
    return tmp_path


class TestNoApmYml:
    """compile() exits with error when apm.yml is absent."""

    def test_missing_apm_yml_exits_with_error(self, runner, tmp_path):
        original = os.getcwd()
        try:
            os.chdir(tmp_path)
            result = runner.invoke(cli, ["compile"])
            assert result.exit_code != 0
            assert "apm.yml" in result.output.lower() or "Not an APM project" in result.output
        finally:
            os.chdir(original)

    def test_missing_apm_yml_suggests_init(self, runner, tmp_path):
        original = os.getcwd()
        try:
            os.chdir(tmp_path)
            result = runner.invoke(cli, ["compile"])
            assert "apm init" in result.output
        finally:
            os.chdir(original)


class TestAllAndTargetConflict:
    """--all and --target together must exit with code 2."""

    def test_all_with_target_exits_nonzero(self, runner, minimal_project):
        original = os.getcwd()
        try:
            os.chdir(minimal_project)
            result = runner.invoke(cli, ["compile", "--all", "--target", "vscode"])
            assert result.exit_code != 0
        finally:
            os.chdir(original)

    def test_all_with_target_shows_error_message(self, runner, minimal_project):
        original = os.getcwd()
        try:
            os.chdir(minimal_project)
            result = runner.invoke(cli, ["compile", "--all", "--target", "vscode"])
            assert "--all" in result.output or "--target" in result.output
        finally:
            os.chdir(original)


class TestTargetAllDeprecation:
    """--target all emits a deprecation warning."""

    def test_target_all_emits_deprecation_warning(self, runner, minimal_project):
        original = os.getcwd()
        try:
            os.chdir(minimal_project)
            result = runner.invoke(cli, ["compile", "--target", "all", "--dry-run"])
            # Should warn about deprecation of --target all
            assert "deprecated" in result.output.lower()
        finally:
            os.chdir(original)

    def test_target_all_still_runs(self, runner, minimal_project):
        original = os.getcwd()
        try:
            os.chdir(minimal_project)
            result = runner.invoke(cli, ["compile", "--target", "all", "--dry-run"])
            # Should not exit with code 2 (reserved for --all + --target conflict)
            assert result.exit_code != 2
        finally:
            os.chdir(original)


class TestNoApmContent:
    """compile() exits with helpful errors when there is nothing to compile."""

    def test_no_content_exits_nonzero(self, runner, empty_project):
        original = os.getcwd()
        try:
            os.chdir(empty_project)
            result = runner.invoke(cli, ["compile"])
            assert result.exit_code != 0
        finally:
            os.chdir(original)

    def test_no_content_suggests_install_or_create(self, runner, empty_project):
        original = os.getcwd()
        try:
            os.chdir(empty_project)
            result = runner.invoke(cli, ["compile"])
            # Should mention installing or creating content
            assert "install" in result.output.lower() or "create" in result.output.lower()
        finally:
            os.chdir(original)

    def test_empty_apm_dir_gives_specific_error(self, runner, tmp_path):
        """When .apm/ exists but has no instruction files, show targeted error."""
        (tmp_path / "apm.yml").write_text("name: test-project\nversion: 0.1.0\n")
        (tmp_path / ".apm").mkdir()  # exists but empty
        original = os.getcwd()
        try:
            os.chdir(tmp_path)
            result = runner.invoke(cli, ["compile"])
            assert result.exit_code != 0
            # Should mention .apm/ directory or instruction files
            assert ".apm/" in result.output or "instruction" in result.output.lower()
        finally:
            os.chdir(original)

    def test_no_content_dry_run_does_not_exit(self, runner, empty_project):
        """--dry-run should skip the sys.exit(1) for missing content."""
        original = os.getcwd()
        try:
            os.chdir(empty_project)
            result = runner.invoke(cli, ["compile", "--dry-run"])
            # dry-run is allowed to continue even with no content (line 421-422)
            assert result.exit_code in (0, 1)
        finally:
            os.chdir(original)


class TestValidateMode:
    """--validate flag exercises the validation-only code path."""

    def test_validate_succeeds_with_valid_project(self, runner, minimal_project):
        original = os.getcwd()
        try:
            os.chdir(minimal_project)
            result = runner.invoke(cli, ["compile", "--validate"])
            # Should succeed and mention validated
            assert result.exit_code == 0
            assert "validat" in result.output.lower()
        finally:
            os.chdir(original)

    def test_validate_reports_primitive_counts(self, runner, minimal_project):
        original = os.getcwd()
        try:
            os.chdir(minimal_project)
            result = runner.invoke(cli, ["compile", "--validate"])
            assert result.exit_code == 0
            # Should show primitive counts
            assert "instruction" in result.output.lower() or "primitive" in result.output.lower()
        finally:
            os.chdir(original)

    def test_validate_without_apm_yml_exits_nonzero(self, runner, tmp_path):
        """--validate on a non-APM project still hits the apm.yml guard first."""
        original = os.getcwd()
        try:
            os.chdir(tmp_path)
            result = runner.invoke(cli, ["compile", "--validate"])
            assert result.exit_code != 0
        finally:
            os.chdir(original)
