export type UserRole = "ADMIN" | "OPERATOR" | "VIEWER";

export type WorkflowState =
  | "PENDING"
  | "EXTRACTING"
  | "TRANSFORMING"
  | "LOADING"
  | "VERIFYING"
  | "COMPLETED"
  | "FAILED";

export interface User {
  id: string;
  email: string;
  full_name: string | null;
  role: UserRole;
  is_active: boolean;
  is_superuser: boolean;
  created_at: string;
}

export interface AuthTokens {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in: number;
}

export interface WorkflowStep {
  id: string;
  workflow_id: string;
  from_state: string;
  to_state: string;
  status: "PENDING" | "IN_PROGRESS" | "SUCCESS" | "FAILED" | "RETRYING" | "SKIPPED";
  execution_duration_ms: number | null;
  started_at: string;
  completed_at: string | null;
  error_message: string | null;
}

export interface Workflow {
  id: string;
  workflow_name: string;
  source_type: string;
  target_dynamodb_table: string;
  current_state: WorkflowState;
  records_total: number;
  records_processed: number;
  records_failed: number;
  progress_percentage: number;
  s3_staging_uri: string | null;
  s3_checksum: string | null;
  configuration: Record<string, unknown>;
  error_details: Record<string, unknown> | null;
  user_id: string | null;
  created_at: string;
  updated_at: string;
  completed_at: string | null;
  steps?: WorkflowStep[];
}

export interface WorkflowListResponse {
  items: Workflow[];
  total_items: number;
  page: number;
  page_size: number;
  total_pages: number;
}

export interface ComponentHealth {
  status: "HEALTHY" | "DEGRADED" | "UNHEALTHY";
  latency_ms?: number;
  details?: Record<string, unknown>;
}

export interface SystemHealth {
  status: string;
  version: string;
  environment: string;
  timestamp?: string;
  components: Record<string, ComponentHealth>;
}

export interface SystemMetrics {
  workflows: {
    total: number;
    by_state: Record<string, number>;
    success_rate_percent: number;
  };
  records: {
    total_submitted: number;
    total_processed: number;
    total_failed: number;
  };
  system: {
    cpu_percent: number;
    memory_used_mb: number;
    memory_percent: number;
    concurrency_limit: number;
  };
}

export interface ApiKey {
  id: string;
  name: string;
  prefix: string;
  is_active: boolean;
  created_at: string;
  last_used_at?: string | null;
  raw_key?: string; // Only present when newly created
}
