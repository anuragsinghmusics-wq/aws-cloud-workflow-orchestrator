"""Validation test suite for Locust load testing configuration and syntax."""

from __future__ import annotations

import ast
import unittest
from pathlib import Path


class TestLocustLoadTestDefinition(unittest.TestCase):
    """Verifies Locust test script syntax, structure, task definitions, and configuration."""

    def setUp(self):
        self.locustfile_path = Path(__file__).resolve().parent.parent / "locustfile.py"
        self.assertTrue(self.locustfile_path.exists(), "locustfile.py must exist at project root")
        self.source = self.locustfile_path.read_text(encoding="utf-8")
        self.tree = ast.parse(self.source)

    def test_locustfile_ast_structure(self):
        self.assertIsInstance(self.tree, ast.Module)

        # Verify imports from locust
        imported_names = set()
        for node in ast.walk(self.tree):
            if isinstance(node, ast.ImportFrom) and node.module == "locust":
                for alias in node.names:
                    imported_names.add(alias.name)

        self.assertIn("HttpUser", imported_names)
        self.assertIn("task", imported_names)
        self.assertIn("between", imported_names)
        self.assertIn("events", imported_names)

    def test_user_class_and_methods(self):
        user_classes = [
            node
            for node in ast.walk(self.tree)
            if isinstance(node, ast.ClassDef) and node.name == "WorkflowOrchestratorUser"
        ]
        self.assertEqual(len(user_classes), 1, "WorkflowOrchestratorUser class must be defined")
        user_class = user_classes[0]

        # Verify base class includes HttpUser
        base_names = [b.id for b in user_class.bases if isinstance(b, ast.Name)]
        self.assertIn("HttpUser", base_names)

        # Verify task methods within WorkflowOrchestratorUser
        method_names = [node.name for node in user_class.body if isinstance(node, ast.FunctionDef)]
        self.assertIn("on_start", method_names)
        self.assertIn("create_and_monitor_workflow", method_names)
        self.assertIn("list_workflows_paginated", method_names)
        self.assertIn("check_health_and_metrics", method_names)
        self.assertIn("inspect_quarantined_dlq", method_names)

    def test_global_event_listeners(self):
        func_names = [node.name for node in self.tree.body if isinstance(node, ast.FunctionDef)]
        self.assertIn("on_test_stop", func_names)


if __name__ == "__main__":
    unittest.main()
