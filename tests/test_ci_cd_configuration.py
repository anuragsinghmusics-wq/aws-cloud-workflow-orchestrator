"""Automated test suite validating CI/CD pipelines, pre-commit hooks, and governance configs."""

from __future__ import annotations

import unittest
from pathlib import Path

import yaml


class TestCICDPipelinesAndConfigs(unittest.TestCase):
    """Verifies syntactic and structural correctness of GitHub Actions workflows and Git hooks."""

    def setUp(self):
        self.root_dir = Path(__file__).resolve().parent.parent
        self.ci_workflow_path = self.root_dir / ".github" / "workflows" / "ci.yml"
        self.deploy_workflow_path = self.root_dir / ".github" / "workflows" / "deploy.yml"
        self.pre_commit_path = self.root_dir / ".pre-commit-config.yaml"
        self.branch_protection_path = self.root_dir / "docs" / "branch-protection.md"

    def test_ci_workflow_validity_and_jobs(self):
        self.assertTrue(self.ci_workflow_path.exists(), "ci.yml must exist")
        content = self.ci_workflow_path.read_text(encoding="utf-8")
        data = yaml.safe_load(content)

        self.assertIn("name", data)
        self.assertIn("jobs", data)

        # Verify required CI jobs exist
        jobs = data["jobs"]
        self.assertIn("lint-and-code-style", jobs)
        self.assertIn("security-sast", jobs)
        self.assertIn("backend-tests", jobs)
        self.assertIn("resilience-and-chaos-testing", jobs)
        self.assertIn("docker-image-build", jobs)

        # Verify backend-tests has required services
        backend_job = jobs["backend-tests"]
        self.assertIn("services", backend_job)
        services = backend_job["services"]
        self.assertIn("postgres", services)
        self.assertIn("redis", services)
        self.assertIn("localstack", services)

        # Verify pytest coverage check is enforced
        steps = backend_job["steps"]
        pytest_step = next(
            (s for s in steps if "pytest --cov=src" in s.get("run", "")),
            None,
        )
        self.assertIsNotNone(pytest_step)
        self.assertIn("--cov-fail-under=85", pytest_step["run"])

    def test_deploy_workflow_validity_and_triggers(self):
        self.assertTrue(self.deploy_workflow_path.exists(), "deploy.yml must exist")
        content = self.deploy_workflow_path.read_text(encoding="utf-8")
        data = yaml.safe_load(content)

        self.assertIn("name", data)
        self.assertIn("jobs", data)

        # Verify tag trigger
        # in yaml: on: push: tags: ['v*']
        # Note: 'on' parses to boolean True in PyYAML 1.1 if unquoted, or dict if handled properly
        on_block = data.get("on") or data.get(True)
        self.assertIsNotNone(on_block, "Workflow triggers ('on') must be configured")
        self.assertIn("push", on_block)
        self.assertIn("tags", on_block["push"])
        self.assertIn("v*", on_block["push"]["tags"])

        # Verify jobs
        jobs = data["jobs"]
        self.assertIn("publish-container-images", jobs)
        self.assertIn("create-github-release", jobs)

        # Verify multi-platform build
        publish_job = jobs["publish-container-images"]
        build_step = next(
            (
                s
                for s in publish_job["steps"]
                if s.get("uses", "").startswith("docker/build-push-action")
            ),
            None,
        )
        self.assertIsNotNone(build_step)
        self.assertEqual(build_step["with"]["platforms"], "linux/amd64,linux/arm64")

    def test_pre_commit_config_structure(self):
        self.assertTrue(self.pre_commit_path.exists(), ".pre-commit-config.yaml must exist")
        content = self.pre_commit_path.read_text(encoding="utf-8")
        data = yaml.safe_load(content)

        self.assertIn("repos", data)
        repos = data["repos"]

        hook_ids = []
        for repo in repos:
            for hook in repo.get("hooks", []):
                hook_ids.append(hook["id"])

        self.assertIn("trailing-whitespace", hook_ids)
        self.assertIn("end-of-file-fixer", hook_ids)
        self.assertIn("check-yaml", hook_ids)
        self.assertIn("detect-private-key", hook_ids)
        self.assertIn("ruff", hook_ids)
        self.assertIn("bandit", hook_ids)

    def test_branch_protection_guidelines_exist(self):
        self.assertTrue(
            self.branch_protection_path.exists(), "docs/branch-protection.md must exist"
        )
        content = self.branch_protection_path.read_text(encoding="utf-8")

        self.assertIn("Protected Branch Strategy", content)
        self.assertIn("Pull Request Verification", content)
        self.assertIn("Required Status Checks", content)
        self.assertIn("Require Signed Commits", content)


if __name__ == "__main__":
    unittest.main()
