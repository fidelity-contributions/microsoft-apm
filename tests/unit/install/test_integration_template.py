"""Tests for src/apm_cli/install/template.py.

Covers the run_integration_template / _integrate_materialization paths:
- acquire() returning None (skip)
- package_info=None (no-op integration)
- empty targets (no-op integration)
- security scan rejecting a package
- successful integration flow
- integrate_package_primitives raising an exception
- verbose diagnostics output (skip/error counters)
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from apm_cli.install.sources import Materialization
from apm_cli.install.template import _integrate_materialization, run_integration_template


def _make_ctx(
    *,
    targets=None,
    force=False,
    verbose=False,
    skill_subset=None,
    skill_subset_from_cli=False,
):
    """Return a minimal InstallContext-like mock."""
    ctx = MagicMock()
    ctx.targets = targets if targets is not None else ["prompt"]
    ctx.force = force
    ctx.project_root = Path("/fake/project")
    ctx.scope = None
    ctx.skill_subset = skill_subset
    ctx.skill_subset_from_cli = skill_subset_from_cli
    ctx.package_deployed_files = {}
    ctx.diagnostics = MagicMock()
    ctx.diagnostics.count_for_package.return_value = 0

    logger_mock = MagicMock()
    logger_mock.verbose = verbose
    ctx.logger = logger_mock

    ctx.integrators = {
        "prompt": MagicMock(),
        "agent": MagicMock(),
        "skill": MagicMock(),
        "instruction": MagicMock(),
        "command": MagicMock(),
        "hook": MagicMock(),
    }
    return ctx


def _make_source(ctx, *, dep_key="pkg@1.0", package_info=None):
    """Return a minimal DependencySource-like mock."""
    source = MagicMock()
    source.ctx = ctx
    source.dep_key = dep_key
    source.dep_ref = MagicMock()
    source.dep_ref.is_local = False
    source.dep_ref.local_path = None
    source.dep_ref.skill_subset = None
    source.INTEGRATE_ERROR_PREFIX = "Failed to integrate primitives"
    source.install_path = Path("/fake/install")
    return source


def _make_materialization(dep_key="pkg@1.0", *, package_info=None):
    return Materialization(
        package_info=package_info,
        install_path=Path("/fake/install"),
        dep_key=dep_key,
    )


class TestRunIntegrationTemplateAcquireNone:
    """When acquire() returns None, run_integration_template returns None."""

    def test_returns_none_when_acquire_returns_none(self):
        ctx = _make_ctx()
        source = _make_source(ctx)
        source.acquire.return_value = None

        result = run_integration_template(source)

        assert result is None

    def test_integration_not_called_when_acquire_returns_none(self):
        ctx = _make_ctx()
        source = _make_source(ctx)
        source.acquire.return_value = None

        with patch("apm_cli.install.template._integrate_materialization") as integrate_mock:
            run_integration_template(source)
            integrate_mock.assert_not_called()


class TestIntegrateNoOp:
    """package_info=None or empty targets -> no-op: returns deltas, records empty deployed list."""

    def test_no_op_when_package_info_is_none(self):
        ctx = _make_ctx(targets=["prompt"])
        source = _make_source(ctx)
        m = _make_materialization(package_info=None)

        result = _integrate_materialization(source, m)

        assert result == m.deltas
        assert ctx.package_deployed_files[m.dep_key] == []

    def test_no_op_when_targets_empty(self):
        ctx = _make_ctx(targets=[])
        source = _make_source(ctx)
        m = _make_materialization(package_info=MagicMock())

        result = _integrate_materialization(source, m)

        assert result == m.deltas
        assert ctx.package_deployed_files[m.dep_key] == []


class TestSecurityScanRejects:
    """When _pre_deploy_security_scan returns False, integration is skipped."""

    def test_security_scan_false_skips_integration(self):
        ctx = _make_ctx()
        source = _make_source(ctx)
        m = _make_materialization(package_info=MagicMock())

        with patch("apm_cli.install.template._pre_deploy_security_scan", return_value=False):
            with patch("apm_cli.install.template.integrate_package_primitives") as integrate_mock:
                result = _integrate_materialization(source, m)

                integrate_mock.assert_not_called()
        assert ctx.package_deployed_files[m.dep_key] == []
        assert result == m.deltas


class TestSuccessfulIntegration:
    """Happy-path: security gate passes, integrate_package_primitives succeeds."""

    def test_deltas_updated_from_integration_result(self):
        ctx = _make_ctx()
        source = _make_source(ctx)
        m = _make_materialization(package_info=MagicMock())

        int_result = {
            "prompts": 2,
            "agents": 1,
            "skills": 0,
            "sub_skills": 0,
            "instructions": 0,
            "commands": 0,
            "hooks": 0,
            "links_resolved": 3,
            "deployed_files": ["file1.md", "file2.md"],
        }

        with patch("apm_cli.install.template._pre_deploy_security_scan", return_value=True):
            with patch(
                "apm_cli.install.template.integrate_package_primitives",
                return_value=int_result,
            ):
                result = _integrate_materialization(source, m)

        assert result["prompts"] == 2
        assert result["agents"] == 1
        assert result["links_resolved"] == 3
        assert ctx.package_deployed_files[m.dep_key] == ["file1.md", "file2.md"]

    def test_skill_subset_from_cli_takes_precedence(self):
        """When skill_subset_from_cli=True, ctx.skill_subset is passed."""
        ctx = _make_ctx(skill_subset=("skill-a",), skill_subset_from_cli=True)
        source = _make_source(ctx)
        m = _make_materialization(package_info=MagicMock())

        int_result = {
            k: 0
            for k in (
                "prompts",
                "agents",
                "skills",
                "sub_skills",
                "instructions",
                "commands",
                "hooks",
                "links_resolved",
            )
        }
        int_result["deployed_files"] = []

        with patch("apm_cli.install.template._pre_deploy_security_scan", return_value=True):
            with patch(
                "apm_cli.install.template.integrate_package_primitives",
                return_value=int_result,
            ) as mock_int:
                _integrate_materialization(source, m)

        _, kwargs = mock_int.call_args
        assert kwargs["skill_subset"] == ("skill-a",)

    def test_skill_subset_from_dep_ref_when_not_from_cli(self):
        """When skill_subset_from_cli=False, dep_ref.skill_subset is used."""
        ctx = _make_ctx(skill_subset=None, skill_subset_from_cli=False)
        source = _make_source(ctx)
        source.dep_ref.skill_subset = ["dep-skill"]
        m = _make_materialization(package_info=MagicMock())

        int_result = {
            k: 0
            for k in (
                "prompts",
                "agents",
                "skills",
                "sub_skills",
                "instructions",
                "commands",
                "hooks",
                "links_resolved",
            )
        }
        int_result["deployed_files"] = []

        with patch("apm_cli.install.template._pre_deploy_security_scan", return_value=True):
            with patch(
                "apm_cli.install.template.integrate_package_primitives",
                return_value=int_result,
            ) as mock_int:
                _integrate_materialization(source, m)

        _, kwargs = mock_int.call_args
        assert kwargs["skill_subset"] == ("dep-skill",)


class TestIntegrationExceptionHandling:
    """integrate_package_primitives raising -> error recorded, deltas returned."""

    def test_exception_recorded_in_diagnostics(self):
        ctx = _make_ctx()
        source = _make_source(ctx)
        m = _make_materialization(package_info=MagicMock())

        with patch("apm_cli.install.template._pre_deploy_security_scan", return_value=True):
            with patch(
                "apm_cli.install.template.integrate_package_primitives",
                side_effect=RuntimeError("boom"),
            ):
                result = _integrate_materialization(source, m)

        ctx.diagnostics.error.assert_called_once()
        call_args = ctx.diagnostics.error.call_args
        assert "boom" in call_args[0][0]
        assert "Failed to integrate primitives" in call_args[0][0]
        assert result == m.deltas

    def test_exception_uses_local_path_as_key_for_local_dep(self):
        """For local deps (is_local=True), diagnostics key is local_path."""
        ctx = _make_ctx()
        source = _make_source(ctx)
        source.dep_ref.is_local = True
        source.dep_ref.local_path = "/some/local/path"
        m = _make_materialization(package_info=MagicMock())

        with patch("apm_cli.install.template._pre_deploy_security_scan", return_value=True):
            with patch(
                "apm_cli.install.template.integrate_package_primitives",
                side_effect=RuntimeError("local error"),
            ):
                _integrate_materialization(source, m)

        call_kwargs = ctx.diagnostics.error.call_args[1]
        assert call_kwargs["package"] == "/some/local/path"


class TestVerboseDiagnostics:
    """Verbose mode logs skip / error counts per package."""

    def test_verbose_skip_count_logged(self):
        ctx = _make_ctx(verbose=True)
        ctx.diagnostics.count_for_package.side_effect = lambda dep_key, kind: (
            2 if kind == "collision" else 0
        )
        source = _make_source(ctx)
        m = _make_materialization(package_info=MagicMock())

        int_result = {
            k: 0
            for k in (
                "prompts",
                "agents",
                "skills",
                "sub_skills",
                "instructions",
                "commands",
                "hooks",
                "links_resolved",
            )
        }
        int_result["deployed_files"] = []

        with patch("apm_cli.install.template._pre_deploy_security_scan", return_value=True):
            with patch(
                "apm_cli.install.template.integrate_package_primitives", return_value=int_result
            ):
                _integrate_materialization(source, m)

        ctx.logger.package_inline_warning.assert_any_call(
            "    [!] 2 files skipped (local files exist)"
        )

    def test_verbose_error_count_logged(self):
        ctx = _make_ctx(verbose=True)
        ctx.diagnostics.count_for_package.side_effect = lambda dep_key, kind: (
            3 if kind == "error" else 0
        )
        source = _make_source(ctx)
        m = _make_materialization(package_info=MagicMock())

        int_result = {
            k: 0
            for k in (
                "prompts",
                "agents",
                "skills",
                "sub_skills",
                "instructions",
                "commands",
                "hooks",
                "links_resolved",
            )
        }
        int_result["deployed_files"] = []

        with patch("apm_cli.install.template._pre_deploy_security_scan", return_value=True):
            with patch(
                "apm_cli.install.template.integrate_package_primitives", return_value=int_result
            ):
                _integrate_materialization(source, m)

        ctx.logger.package_inline_warning.assert_any_call("    [!] 3 integration errors")

    def test_verbose_singular_forms(self):
        """Singular 'file' and 'error' when count is exactly 1."""
        ctx = _make_ctx(verbose=True)
        ctx.diagnostics.count_for_package.side_effect = lambda dep_key, kind: 1
        source = _make_source(ctx)
        m = _make_materialization(package_info=MagicMock())

        int_result = {
            k: 0
            for k in (
                "prompts",
                "agents",
                "skills",
                "sub_skills",
                "instructions",
                "commands",
                "hooks",
                "links_resolved",
            )
        }
        int_result["deployed_files"] = []

        with patch("apm_cli.install.template._pre_deploy_security_scan", return_value=True):
            with patch(
                "apm_cli.install.template.integrate_package_primitives", return_value=int_result
            ):
                _integrate_materialization(source, m)

        calls = [str(c) for c in ctx.logger.package_inline_warning.call_args_list]
        assert any("1 file skipped" in c for c in calls)
        assert any("1 integration error" in c for c in calls)
