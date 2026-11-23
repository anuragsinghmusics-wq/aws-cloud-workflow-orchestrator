import React, { useEffect, useState } from "react";
import { useParams, Link } from "react-router-dom";
import {
  ArrowLeft,
  RotateCcw,
  XCircle,
  HardDrive,
  Hash,
  Database,
  Radio,
  Code,
  Copy,
  Check,
} from "lucide-react";
import { workflowService } from "../services/api";
import { useWorkflowStream } from "../hooks/useWorkflowStream";
import { WorkflowStateBadge } from "../components/WorkflowStateBadge";
import { FSMStepIndicator } from "../components/FSMStepIndicator";
import type { Workflow } from "../types";

export const WorkflowDetail: React.FC = () => {
  const { jobId } = useParams<{ jobId: string }>();
  const [workflow, setWorkflow] = useState<Workflow | null>(null);
  const [loading, setLoading] = useState(true);
  const [actionLoading, setActionLoading] = useState(false);
  const [copied, setCopied] = useState(false);

  // Real-time WebSocket live updates
  const { isConnected, lastEvent } = useWorkflowStream(jobId);

  const fetchWorkflow = async () => {
    if (!jobId) return;
    try {
      const data = await workflowService.getWorkflow(jobId);
      setWorkflow(data);
    } catch {
      // Ignore
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchWorkflow();
    const interval = setInterval(fetchWorkflow, 5000);
    return () => clearInterval(interval);
  }, [jobId]);

  // When a WebSocket event arrives, update the workflow state immediately
  useEffect(() => {
    if (lastEvent && workflow) {
      if (lastEvent.state) {
        setWorkflow((prev) =>
          prev
            ? {
                ...prev,
                current_state: lastEvent.state!,
                progress_percentage: lastEvent.progress_percentage ?? prev.progress_percentage,
              }
            : null
        );
      }
    }
  }, [lastEvent]);

  const handleCopyJobId = () => {
    if (jobId) {
      navigator.clipboard.writeText(jobId);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  };

  const handleRetry = async () => {
    if (!jobId) return;
    setActionLoading(true);
    try {
      const updated = await workflowService.retryWorkflow(jobId, "Operator triggered retry from UI");
      setWorkflow(updated);
    } finally {
      setActionLoading(false);
    }
  };

  const handleCancel = async () => {
    if (!jobId || !window.confirm("Abort this running migration?")) return;
    setActionLoading(true);
    try {
      const updated = await workflowService.cancelWorkflow(jobId);
      setWorkflow(updated);
    } finally {
      setActionLoading(false);
    }
  };

  if (loading) {
    return (
      <div className="py-24 text-center text-slate-500 text-sm">
        Retrieving workflow details and step ledger...
      </div>
    );
  }

  if (!workflow) {
    return (
      <div className="py-24 text-center">
        <h2 className="text-xl font-bold text-white mb-2">Workflow Not Found</h2>
        <p className="text-sm text-slate-400 mb-6">
          The requested job ID could not be located in the database ledger.
        </p>
        <Link
          to="/workflows"
          className="px-4 py-2 rounded-lg bg-sky-600 hover:bg-sky-500 text-white text-sm font-medium"
        >
          Return to Workflows
        </Link>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Top Breadcrumb & Live Socket Pill */}
      <div className="flex items-center justify-between">
        <Link
          to="/workflows"
          className="inline-flex items-center gap-1.5 text-xs font-medium text-slate-400 hover:text-white transition-colors"
        >
          <ArrowLeft className="w-3.5 h-3.5" />
          <span>Back to Workflows Ledger</span>
        </Link>

        <div className="flex items-center gap-2">
          <div
            className={`flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-mono border ${
              isConnected
                ? "bg-emerald-500/10 border-emerald-500/30 text-emerald-400"
                : "bg-slate-900 border-slate-800 text-slate-500"
            }`}
          >
            <Radio className={`w-3.5 h-3.5 ${isConnected ? "animate-pulse" : ""}`} />
            <span>{isConnected ? "Live WebSocket Connected" : "Polling Mode (5s)"}</span>
          </div>
        </div>
      </div>

      {/* Main Workflow Header Card */}
      <div className="p-6 rounded-xl border border-slate-800 bg-slate-900/40">
        <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-4">
          <div>
            <div className="flex items-center gap-3 mb-1">
              <h1 className="text-2xl font-bold text-white tracking-tight">
                {workflow.workflow_name}
              </h1>
              <WorkflowStateBadge state={workflow.current_state} size="md" />
            </div>

            <div className="flex items-center gap-2 text-xs font-mono text-slate-400">
              <span>Job ID: {workflow.id}</span>
              <button
                onClick={handleCopyJobId}
                className="text-slate-500 hover:text-slate-300 p-0.5"
                title="Copy Job ID"
              >
                {copied ? <Check className="w-3.5 h-3.5 text-emerald-400" /> : <Copy className="w-3.5 h-3.5" />}
              </button>
            </div>
          </div>

          <div className="flex items-center gap-3">
            {workflow.current_state === "FAILED" && (
              <button
                onClick={handleRetry}
                disabled={actionLoading}
                className="flex items-center gap-1.5 py-2 px-3.5 rounded-lg bg-amber-500/10 hover:bg-amber-500/20 text-amber-300 border border-amber-500/30 text-xs font-medium transition-colors"
              >
                <RotateCcw className="w-3.5 h-3.5" />
                <span>Retry Workflow</span>
              </button>
            )}

            {workflow.current_state !== "COMPLETED" && workflow.current_state !== "FAILED" && (
              <button
                onClick={handleCancel}
                disabled={actionLoading}
                className="flex items-center gap-1.5 py-2 px-3.5 rounded-lg bg-rose-500/10 hover:bg-rose-500/20 text-rose-300 border border-rose-500/30 text-xs font-medium transition-colors"
              >
                <XCircle className="w-3.5 h-3.5" />
                <span>Abort Migration</span>
              </button>
            )}
          </div>
        </div>

        {/* Overall Progress Bar */}
        <div className="mt-6 pt-6 border-t border-slate-800/80">
          <div className="flex justify-between items-center text-xs text-slate-400 mb-2 font-mono">
            <span>Overall Migration Progress</span>
            <span className="font-bold text-white">{workflow.progress_percentage}%</span>
          </div>
          <div className="w-full bg-slate-800 rounded-full h-3 overflow-hidden">
            <div
              className={`h-3 rounded-full transition-all duration-700 ${
                workflow.current_state === "COMPLETED"
                  ? "bg-emerald-500"
                  : workflow.current_state === "FAILED"
                  ? "bg-rose-500"
                  : "bg-gradient-to-r from-sky-500 to-indigo-500 animate-pulse"
              }`}
              style={{ width: `${workflow.progress_percentage}%` }}
            ></div>
          </div>
        </div>
      </div>

      {/* FSM Visual Step Stepper */}
      <div className="p-6 rounded-xl border border-slate-800 bg-slate-900/40">
        <h2 className="text-sm font-semibold text-slate-200 uppercase tracking-wider mb-2">
          State Machine Lifecycle Phases
        </h2>
        <FSMStepIndicator currentState={workflow.current_state} steps={workflow.steps} />
      </div>

      {/* AWS Infrastructure Artifacts Grid */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {/* S3 Snapshot */}
        <div className="p-4 rounded-xl border border-slate-800 bg-slate-900/40">
          <div className="flex items-center gap-2 text-xs font-medium uppercase text-slate-400 mb-2">
            <HardDrive className="w-4 h-4 text-sky-400" />
            <span>S3 Payload Staging</span>
          </div>
          <div className="text-xs font-mono text-slate-300 break-all">
            {workflow.s3_staging_uri || "Pending upload..."}
          </div>
        </div>

        {/* SHA-256 Checksum */}
        <div className="p-4 rounded-xl border border-slate-800 bg-slate-900/40">
          <div className="flex items-center gap-2 text-xs font-medium uppercase text-slate-400 mb-2">
            <Hash className="w-4 h-4 text-emerald-400" />
            <span>SHA-256 Digest</span>
          </div>
          <div className="text-xs font-mono text-slate-300 truncate" title={workflow.s3_checksum || ""}>
            {workflow.s3_checksum || "Calculating..."}
          </div>
        </div>

        {/* DynamoDB Target */}
        <div className="p-4 rounded-xl border border-slate-800 bg-slate-900/40">
          <div className="flex items-center gap-2 text-xs font-medium uppercase text-slate-400 mb-2">
            <Database className="w-4 h-4 text-purple-400" />
            <span>Target DynamoDB Table</span>
          </div>
          <div className="text-xs font-mono text-slate-300">
            {workflow.target_dynamodb_table}
          </div>
        </div>
      </div>

      {/* Ordered Step History Ledger */}
      <div className="p-6 rounded-xl border border-slate-800 bg-slate-900/40">
        <h2 className="text-base font-semibold text-white mb-1">State Transition Audit Ledger</h2>
        <p className="text-xs text-slate-400 mb-4">
          Immutable event log of every state transition executed by the engine
        </p>

        {(!workflow.steps || workflow.steps.length === 0) ? (
          <div className="text-center py-8 text-xs text-slate-500">
            No step records logged yet.
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs text-slate-300">
              <thead className="uppercase text-[11px] text-slate-500 bg-slate-950/60 border-b border-slate-800">
                <tr>
                  <th className="py-2.5 px-4">From State</th>
                  <th className="py-2.5 px-4">To State</th>
                  <th className="py-2.5 px-4">Status</th>
                  <th className="py-2.5 px-4">Duration</th>
                  <th className="py-2.5 px-4">Timestamp</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/60 font-mono">
                {Array.isArray(workflow.steps) && workflow.steps.map((st) => (
                  <tr key={st.id} className="hover:bg-slate-900/40">
                    <td className="py-2.5 px-4 text-slate-400">{st.from_state}</td>
                    <td className="py-2.5 px-4 text-sky-400 font-semibold">{st.to_state}</td>
                    <td className="py-2.5 px-4">
                      <span
                        className={`px-2 py-0.5 rounded text-[10px] font-semibold ${
                          st.status === "SUCCESS"
                            ? "bg-emerald-500/10 text-emerald-400"
                            : st.status === "FAILED"
                            ? "bg-rose-500/10 text-rose-400"
                            : "bg-slate-800 text-slate-300"
                        }`}
                      >
                        {st.status}
                      </span>
                    </td>
                    <td className="py-2.5 px-4 text-slate-400">
                      {st.execution_duration_ms != null ? `${st.execution_duration_ms.toFixed(1)}ms` : "—"}
                    </td>
                    <td className="py-2.5 px-4 text-slate-500">
                      {st.started_at ? (() => {
                        try {
                          const d = new Date(st.started_at);
                          return isNaN(d.getTime()) ? "—" : d.toLocaleTimeString();
                        } catch {
                          return "—";
                        }
                      })() : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Configuration & Diagnostics */}
      <div className="p-6 rounded-xl border border-slate-800 bg-slate-900/40">
        <div className="flex items-center gap-2 text-sm font-semibold text-white mb-3">
          <Code className="w-4 h-4 text-slate-400" />
          <span>Execution Parameters & Configuration</span>
        </div>
        <pre className="p-4 rounded-lg bg-slate-950 border border-slate-800 text-xs font-mono text-slate-300 overflow-x-auto">
          {JSON.stringify(workflow.configuration, null, 2)}
        </pre>
      </div>
    </div>
  );
};
