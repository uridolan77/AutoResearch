"""CommandEvaluator — runs an arbitrary shell command inside a Docker sandbox.

Config schema:
    {
        "image": "python:3.11-slim",          # required: container image
        "command": "pytest --tb=short -q",    # required: shell command to run
        "metric_path": "$.passed_count",      # optional jsonpath for metric extraction
        "metric_regex": "passed: (\\d+)",     # optional regex (group 1) — used if no metric_path
        "metric_source": "stdout",            # "stdout" (default) or "file:<relative_path>"
        "workdir": "/workspace"               # in-container workdir (default /workspace)
    }

Network policy comes from EvaluatorRow.network_mode (Phase 1: none/bridge).
Secrets are injected as --env at container spawn; never written to disk.
The container is stopped + removed on every invocation, success or failure.
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from app.evaluators.base import Evaluator, EvaluatorError, EvaluatorResult
from app.models.enums import NetworkMode

logger = logging.getLogger(__name__)

DEFAULT_WORKDIR = "/workspace"


class CommandEvaluator(Evaluator):
    def evaluate(self, worktree_path: Path) -> EvaluatorResult:
        try:
            import docker  # type: ignore
            from docker.errors import APIError, ContainerError, ImageNotFound, NotFound  # type: ignore
        except ModuleNotFoundError as e:
            raise EvaluatorError(
                "docker SDK is not installed; CommandEvaluator requires the 'docker' package"
            ) from e

        cfg = self.config
        image = cfg.get("image")
        command = cfg.get("command")
        if not image or not command:
            raise EvaluatorError("CommandEvaluator config requires 'image' and 'command'")
        workdir = cfg.get("workdir", DEFAULT_WORKDIR)
        timeout = int(self.row.timeout_s)

        network = self._network_for_mode(self.row.network_mode)

        client = docker.from_env()
        container = None
        stdout = ""
        stderr = ""
        exit_code = -1

        try:
            container = client.containers.run(
                image=image,
                command=["sh", "-c", command],
                working_dir=workdir,
                volumes={
                    str(worktree_path.absolute()): {"bind": workdir, "mode": "rw"},
                },
                environment=self.secrets,
                network_mode=network,
                detach=True,
                stdout=True,
                stderr=True,
                # No host network, no privileged, no capabilities beyond default.
            )
            try:
                result = container.wait(timeout=timeout)
                exit_code = int(result.get("StatusCode", -1))
            except Exception as e:
                # Timeout or daemon error — kill and report.
                try:
                    container.kill()
                except Exception:
                    pass
                raise EvaluatorError(f"container wait failed: {e}") from e

            stdout = container.logs(stdout=True, stderr=False).decode("utf-8", errors="replace")
            stderr = container.logs(stdout=False, stderr=True).decode("utf-8", errors="replace")
        except (ImageNotFound, APIError, ContainerError) as e:
            raise EvaluatorError(f"docker error: {e}") from e
        finally:
            if container is not None:
                try:
                    container.remove(force=True)
                except (NotFound, APIError):
                    pass

        score, payload = self._extract_metric(stdout, worktree_path)
        return EvaluatorResult(
            score=score,
            metric_payload=payload,
            stdout=stdout,
            stderr=stderr,
            exit_code=exit_code,
        )

    # ------------------------------------------------------------ helpers

    @staticmethod
    def _network_for_mode(mode: NetworkMode) -> str:
        # Phase 1: only on/off. Phase 2 will route egress_proxy through Squid.
        if mode == NetworkMode.none:
            return "none"
        if mode == NetworkMode.bridge:
            return "bridge"
        raise EvaluatorError(
            f"network_mode {mode.value!r} is not supported in Phase 1 (expected 'none' or 'bridge')"
        )

    def _extract_metric(self, stdout: str, worktree_path: Path) -> tuple[float, dict]:
        cfg = self.config
        source = cfg.get("metric_source", "stdout")

        if source.startswith("file:"):
            rel = source[len("file:"):]
            text = (worktree_path / rel).read_text(encoding="utf-8", errors="replace")
        else:
            text = stdout

        if "metric_path" in cfg:
            try:
                from jsonpath_ng import parse as jsonpath_parse  # type: ignore
            except ModuleNotFoundError as e:
                raise EvaluatorError(
                    "jsonpath-ng is not installed; CommandEvaluator metric_path requires 'jsonpath-ng'"
                ) from e
            try:
                obj: Any = json.loads(text)
            except json.JSONDecodeError as e:
                raise EvaluatorError(
                    f"metric_path requires JSON in {source}; failed to parse: {e}"
                ) from e
            matches = jsonpath_parse(cfg["metric_path"]).find(obj)
            if not matches:
                raise EvaluatorError(
                    f"metric_path {cfg['metric_path']!r} matched nothing"
                )
            value = matches[0].value
            return float(value), obj if isinstance(obj, dict) else {"value": obj}

        if "metric_regex" in cfg:
            m = re.search(cfg["metric_regex"], text)
            if not m:
                raise EvaluatorError(
                    f"metric_regex {cfg['metric_regex']!r} did not match"
                )
            return float(m.group(1)), {"matched": m.group(0)}

        raise EvaluatorError(
            "CommandEvaluator config must include metric_path or metric_regex"
        )
