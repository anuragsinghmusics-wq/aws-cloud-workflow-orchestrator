"""Integration tests for workflow creation, idempotency, listing, details, retries, and cancellation."""

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from src.core.security import get_current_active_user, require_role
from src.core.state_machine import WorkflowState
from src.database import get_db_session
from src.main import app
from src.models.user import User, UserRole
from src.models.workflow import StepStatus, Workflow, WorkflowStep


class TestWorkflowsAPI(unittest.TestCase):
    """Verifies that workflow initiation, state querying, lifecycle control, and RBAC operate deterministically."""

    def setUp(self):
        self.client = TestClient(app)
        self.mock_session = AsyncMock()
        self.mock_session.add = MagicMock()

        async def override_db():
            yield self.mock_session

        self.operator_user = User(
            id="user-op-123",
            email="operator@company.com",
            hashed_password="hash",
            role=UserRole.OPERATOR.value,
            is_active=True,
        )

        app.dependency_overrides[get_db_session] = override_db
        app.dependency_overrides[get_current_active_user] = lambda: self.operator_user
        app.dependency_overrides[require_role(UserRole.OPERATOR, UserRole.ADMIN)] = lambda: (
            self.operator_user
        )

    def tearDown(self):
        app.dependency_overrides.clear()

    @patch("src.api.v1.workflows.execute_migration_task")
    def test_initiate_workflow_success(self, mock_celery_task):
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None  # No existing duplicate
        self.mock_session.execute.return_value = mock_result

        # After commit, second select retrieves the created workflow with steps
        created_wf = Workflow(
            workflow_name="pg-to-dynamodb-users",
            source_type="POSTGRES_SQL_DUMP",
            target_dynamodb_table="Users_V2",
            records_total=2,
            user_id=self.operator_user.id,
        )
        mock_result.scalar_one.return_value = created_wf

        payload = {
            "workflow_name": "pg-to-dynamodb-users",
            "source_type": "POSTGRES_SQL_DUMP",
            "target_dynamodb_table": "Users_V2",
            "payload_data": [
                {"id": 1, "username": "alice"},
                {"id": 2, "username": "bob"},
            ],
            "configuration": {"batch_size": 25},
        }

        response = self.client.post("/api/v1/workflows", json=payload)
        self.assertEqual(response.status_code, 202)
        data = response.json()
        self.assertEqual(data["workflow_name"], "pg-to-dynamodb-users")
        self.assertEqual(data["current_state"], WorkflowState.PENDING.value)
        self.assertEqual(data["records_total"], 2)
        mock_celery_task.delay.assert_called_once()

    def test_initiate_workflow_idempotency_returns_existing(self):
        existing_wf = Workflow(
            id="job-dedup-123",
            workflow_name="pg-to-dynamodb-users",
            source_type="POSTGRES_SQL_DUMP",
            target_dynamodb_table="Users_V2",
            records_total=2,
            current_state=WorkflowState.EXTRACTING.value,
        )
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = existing_wf
        self.mock_session.execute.return_value = mock_result

        payload = {
            "workflow_name": "pg-to-dynamodb-users",
            "source_type": "POSTGRES_SQL_DUMP",
            "target_dynamodb_table": "Users_V2",
            "payload_data": [
                {"id": 1, "username": "alice"},
                {"id": 2, "username": "bob"},
            ],
        }

        response = self.client.post("/api/v1/workflows", json=payload)
        self.assertEqual(response.status_code, 202)
        data = response.json()
        self.assertEqual(data["id"], "job-dedup-123")
        self.assertEqual(data["current_state"], WorkflowState.EXTRACTING.value)

    def test_list_workflows_with_pagination(self):
        wf1 = Workflow(
            id="wf-1",
            workflow_name="job-1",
            source_type="CSV",
            target_dynamodb_table="T1",
            records_total=10,
        )
        wf2 = Workflow(
            id="wf-2",
            workflow_name="job-2",
            source_type="CSV",
            target_dynamodb_table="T2",
            records_total=20,
        )

        mock_count = MagicMock()
        mock_count.scalar_one.return_value = 2

        mock_items = MagicMock()
        mock_items.scalars.return_value.all.return_value = [wf1, wf2]

        self.mock_session.execute.side_effect = [mock_count, mock_items]

        response = self.client.get("/api/v1/workflows?page=1&page_size=10")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["total_items"], 2)
        self.assertEqual(len(data["items"]), 2)
        self.assertEqual(data["page"], 1)

    def test_get_workflow_detail_success(self):
        wf = Workflow(
            id="wf-detail-101",
            workflow_name="job-detail",
            source_type="CSV",
            target_dynamodb_table="T1",
            records_total=100,
            records_processed=50,
            user_id=self.operator_user.id,
        )
        step = WorkflowStep(
            workflow_id=wf.id,
            from_state="PENDING",
            to_state="EXTRACTING",
            status=StepStatus.SUCCESS.value,
        )
        wf.steps = [step]

        mock_res = MagicMock()
        mock_res.scalar_one_or_none.return_value = wf
        self.mock_session.execute.return_value = mock_res

        response = self.client.get(f"/api/v1/workflows/{wf.id}")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["id"], "wf-detail-101")
        self.assertEqual(data["progress_percentage"], 50.0)
        self.assertEqual(len(data["steps"]), 1)
        self.assertEqual(data["steps"][0]["to_state"], "EXTRACTING")

    def test_get_workflow_detail_not_found_raises_404(self):
        mock_res = MagicMock()
        mock_res.scalar_one_or_none.return_value = None
        self.mock_session.execute.return_value = mock_res

        response = self.client.get("/api/v1/workflows/non-existent-uuid")
        self.assertEqual(response.status_code, 404)
        data = response.json()
        self.assertEqual(data["error"], "ERR_WORKFLOW_NOT_FOUND")

    def test_retry_workflow_success(self):
        wf = Workflow(
            id="wf-failed-101",
            workflow_name="job-retry",
            source_type="CSV",
            target_dynamodb_table="T1",
            current_state=WorkflowState.FAILED.value,
            user_id=self.operator_user.id,
        )
        mock_res = MagicMock()
        mock_res.scalar_one_or_none.return_value = wf
        self.mock_session.execute.return_value = mock_res

        response = self.client.post(
            f"/api/v1/workflows/{wf.id}/retry",
            json={"reason": "Network blip recovered"},
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["current_state"], WorkflowState.PENDING.value)
        self.mock_session.commit.assert_awaited()

    def test_retry_completed_workflow_raises_terminal_state_error(self):
        wf = Workflow(
            id="wf-completed-101",
            workflow_name="job-completed",
            source_type="CSV",
            target_dynamodb_table="T1",
            current_state=WorkflowState.COMPLETED.value,
            user_id=self.operator_user.id,
        )
        mock_res = MagicMock()
        mock_res.scalar_one_or_none.return_value = wf
        self.mock_session.execute.return_value = mock_res

        response = self.client.post(
            f"/api/v1/workflows/{wf.id}/retry",
            json={"reason": "Attempt retry"},
        )
        self.assertEqual(response.status_code, 409)
        data = response.json()
        self.assertEqual(data["error"], "ERR_STATE_TERMINAL")

    def test_cancel_workflow_success(self):
        wf = Workflow(
            id="wf-cancel-101",
            workflow_name="job-cancel",
            source_type="CSV",
            target_dynamodb_table="T1",
            current_state=WorkflowState.EXTRACTING.value,
            user_id=self.operator_user.id,
        )
        mock_res = MagicMock()
        mock_res.scalar_one_or_none.return_value = wf
        self.mock_session.execute.return_value = mock_res

        response = self.client.post(f"/api/v1/workflows/{wf.id}/cancel")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["current_state"], WorkflowState.FAILED.value)
        self.mock_session.commit.assert_awaited()

    def test_cancel_already_failed_workflow_raises(self):
        wf = Workflow(
            id="wf-failed-102",
            workflow_name="job-already-failed",
            source_type="CSV",
            target_dynamodb_table="T1",
            current_state=WorkflowState.FAILED.value,
            user_id=self.operator_user.id,
        )
        mock_res = MagicMock()
        mock_res.scalar_one_or_none.return_value = wf
        self.mock_session.execute.return_value = mock_res

        response = self.client.post(f"/api/v1/workflows/{wf.id}/cancel")
        self.assertEqual(response.status_code, 409)
        data = response.json()
        self.assertEqual(data["error"], "ERR_STATE_TERMINAL")

    def test_websocket_workflow_streaming(self):
        job_id = "test-ws-stream-101"
        with self.client.websocket_connect(f"/api/v1/ws/workflows/{job_id}") as ws:
            event = ws.receive_json()
            self.assertEqual(event["event"], "SUBSCRIBED")
            self.assertEqual(event["job_id"], job_id)

            ws.send_text("ping")
            reply = ws.receive_text()
            self.assertEqual(reply, "pong")


if __name__ == "__main__":
    unittest.main()
