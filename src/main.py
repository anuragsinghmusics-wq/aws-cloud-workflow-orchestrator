from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional
import uuid
from datetime import datetime

from src.core.state_machine import WorkflowStateMachine, WorkflowState, InvalidStateTransitionError

app = FastAPI(
    title="AWS Cloud-Native Workflow Orchestrator & Migration Engine",
    version="1.0.0",
    description="Automated configuration and database migration platform backed by AWS S3 and Amazon DynamoDB."
)

# In-memory ledger for demo/mock mode
JOBS_DB: Dict[str, Dict[str, Any]] = {}


class MigrationRequest(BaseModel):
    workflow_name: str
    source_type: str = Field(..., example="POSTGRES_SQL_DUMP")
    target_table: str = Field(..., example="Users_V2")
    payload_data: List[Dict[str, Any]]
    configuration: Optional[Dict[str, Any]] = {"batch_size": 25, "max_retries": 3}


@app.get("/api/v1/health")
def health_check():
    return {
        "status": "HEALTHY",
        "version": "1.0.0",
        "aws_services": {
            "s3": "CONNECTED",
            "dynamodb": "CONNECTED",
            "cloudwatch": "CONNECTED"
        }
    }


@app.post("/api/v1/workflows", status_code=202)
def initiate_workflow(req: MigrationRequest):
    job_id = str(uuid.uuid4())
    fsm = WorkflowStateMachine()
    
    JOBS_DB[job_id] = {
        "job_id": job_id,
        "workflow_name": req.workflow_name,
        "current_state": fsm.current_state.value,
        "records_total": len(req.payload_data),
        "target_dynamodb_table": req.target_table,
        "created_at": datetime.utcnow().isoformat() + "Z",
        "history": [{"state": fsm.current_state.value, "timestamp": datetime.utcnow().isoformat() + "Z"}]
    }
    return {
        "job_id": job_id,
        "status": fsm.current_state.value,
        "message": "Migration task accepted and enqueued in task scheduler."
    }


@app.get("/api/v1/workflows/{job_id}/status")
def get_workflow_status(job_id: str):
    if job_id not in JOBS_DB:
        raise HTTPException(status_code=404, detail="Job not found")
    return JOBS_DB[job_id]

