"""Unit tests for database models, relationships, and metadata definitions."""

import importlib.util
import unittest
import uuid

HAS_SQLALCHEMY = importlib.util.find_spec("sqlalchemy") is not None
if HAS_SQLALCHEMY:
    import inspect

    from src.database import (
        Base,
        check_db_health,
        drop_models,
        get_db_session,
        get_engine,
        init_models,
    )
    from src.models import (
        ApiKey,
        AuditLog,
        StepStatus,
        User,
        UserRole,
        Workflow,
        WorkflowStep,
    )


@unittest.skipUnless(HAS_SQLALCHEMY, "SQLAlchemy is required for database ORM tests")
class TestDatabaseModels(unittest.TestCase):
    """Verifies that ORM entity attributes, relationships, and calculations behave correctly."""

    def test_registered_tables_in_metadata(self):
        tables = Base.metadata.tables.keys()
        self.assertIn("users", tables)
        self.assertIn("workflows", tables)
        self.assertIn("workflow_steps", tables)
        self.assertIn("audit_logs", tables)
        self.assertIn("api_keys", tables)

    def test_user_model_defaults(self):
        user = User(
            email="developer@example.com",
            hashed_password="hashed_pw_test",
            full_name="Test Developer",
        )
        self.assertTrue(user.id)
        self.assertEqual(user.role, UserRole.OPERATOR.value)
        self.assertTrue(user.is_active)
        self.assertFalse(user.is_superuser)
        self.assertIn("developer@example.com", repr(user))

    def test_workflow_model_progress_calculation(self):
        workflow = Workflow(
            workflow_name="pg-users-to-dynamodb",
            source_type="POSTGRES_SQL_DUMP",
            target_dynamodb_table="Users_V2",
            records_total=1000,
            records_processed=250,
        )
        self.assertEqual(workflow.progress_percentage, 25.0)

        workflow.records_processed = 750
        self.assertEqual(workflow.progress_percentage, 75.0)

        workflow.records_processed = 1000
        self.assertEqual(workflow.progress_percentage, 100.0)

    def test_workflow_progress_zero_records(self):
        empty_wf = Workflow(
            workflow_name="empty-job",
            source_type="EMPTY",
            target_dynamodb_table="Target",
            records_total=0,
            records_processed=0,
            current_state="COMPLETED",
        )
        self.assertEqual(empty_wf.progress_percentage, 100.0)

        pending_wf = Workflow(
            workflow_name="pending-job",
            source_type="EMPTY",
            target_dynamodb_table="Target",
            records_total=0,
            records_processed=0,
            current_state="PENDING",
        )
        self.assertEqual(pending_wf.progress_percentage, 0.0)

    def test_workflow_step_model(self):
        step = WorkflowStep(
            workflow_id=str(uuid.uuid4()),
            from_state="PENDING",
            to_state="EXTRACTING",
            status=StepStatus.SUCCESS.value,
            execution_duration_ms=145.2,
        )
        self.assertEqual(step.from_state, "PENDING")
        self.assertEqual(step.to_state, "EXTRACTING")
        self.assertEqual(step.status, "SUCCESS")
        self.assertEqual(step.execution_duration_ms, 145.2)
        self.assertIn("PENDING -> EXTRACTING", repr(step))

    def test_audit_log_model(self):
        log_entry = AuditLog(
            entity_type="workflow",
            entity_id="wf-123",
            action="RETRY",
            details={"retry_attempt": 2},
            ip_address="127.0.0.1",
        )
        self.assertEqual(log_entry.entity_type, "workflow")
        self.assertEqual(log_entry.entity_id, "wf-123")
        self.assertEqual(log_entry.action, "RETRY")
        self.assertEqual(log_entry.details["retry_attempt"], 2)
        self.assertEqual(log_entry.ip_address, "127.0.0.1")
        self.assertIn("RETRY on workflow:wf-123", repr(log_entry))

    def test_api_key_model(self):
        key = ApiKey(
            name="CI/CD Runner",
            key_hash="hash_abc123",
            prefix="ak_live_7x",
            user_id="usr_001",
        )
        self.assertEqual(key.name, "CI/CD Runner")
        self.assertEqual(key.key_hash, "hash_abc123")
        self.assertEqual(key.prefix, "ak_live_7x")
        self.assertTrue(key.is_active)
        self.assertIn("ak_live_7x", repr(key))

    def test_get_engine_sqlite_configuration(self):
        eng = get_engine("sqlite+aiosqlite:///:memory:")
        self.assertIn("sqlite", str(eng.url))

    def test_get_engine_postgres_configuration(self):
        eng = get_engine("postgresql+asyncpg://postgres:postgres@localhost:5432/test_db")
        self.assertIn("postgresql", str(eng.url))

    def test_database_functions_are_async(self):
        self.assertTrue(inspect.isasyncgenfunction(get_db_session))
        self.assertTrue(inspect.iscoroutinefunction(check_db_health))
        self.assertTrue(inspect.iscoroutinefunction(init_models))
        self.assertTrue(inspect.iscoroutinefunction(drop_models))


if __name__ == "__main__":
    unittest.main()
