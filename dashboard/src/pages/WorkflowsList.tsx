import React, { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  Search,
  RotateCcw,
  XCircle,
  PlusCircle,
  ChevronLeft,
  ChevronRight,
  Filter,
} from "lucide-react";
import { workflowService } from "../services/api";
import { WorkflowStateBadge } from "../components/WorkflowStateBadge";
import type { Workflow, WorkflowState } from "../types";

const FILTER_STATES: (WorkflowState | "ALL")[] = [
  "ALL",
  "PENDING",
  "EXTRACTING",
  "TRANSFORMING",
  "LOADING",
  "VERIFYING",
  "COMPLETED",
  "FAILED",
];

export const WorkflowsList: React.FC = () => {
  const [workflows, setWorkflows] = useState<Workflow[]>([]);
  const [selectedState, setSelectedState] = useState<string>("ALL");
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const [totalPages, setTotalPages] = useState(1);
  const [totalItems, setTotalItems] = useState(0);
  const [loading, setLoading] = useState(true);
  const [actionLoading, setActionLoading] = useState<string | null>(null);

  const formatDate = (val?: string | null) => {
    if (!val) return "—";
    try {
      const d = new Date(val);
      return isNaN(d.getTime()) ? "—" : `${d.toLocaleDateString()} ${d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}`;
    } catch {
      return "—";
    }
  };

  const fetchWorkflows = async () => {
    setLoading(true);
    try {
      const res = await workflowService.listWorkflows({
        state: selectedState === "ALL" ? undefined : selectedState,
        search: search.trim() || undefined,
        page,
        page_size: 10,
      });
      setWorkflows(Array.isArray(res?.items) ? res.items : []);
      setTotalPages(res?.total_pages ?? 1);
      setTotalItems(res?.total_items ?? 0);
    } catch {
      // Ignore
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchWorkflows();
  }, [selectedState, page]);

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault();
    setPage(1);
    fetchWorkflows();
  };

  const handleRetry = async (jobId: string) => {
    setActionLoading(jobId);
    try {
      await workflowService.retryWorkflow(jobId, "Manual retry from dashboard");
      await fetchWorkflows();
    } finally {
      setActionLoading(null);
    }
  };

  const handleCancel = async (jobId: string) => {
    if (!window.confirm("Are you sure you want to cancel this in-progress migration?")) return;
    setActionLoading(jobId);
    try {
      await workflowService.cancelWorkflow(jobId);
      await fetchWorkflows();
    } finally {
      setActionLoading(null);
    }
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-white tracking-tight">Workflows Ledger</h1>
          <p className="text-sm text-slate-400 mt-1">
            Complete audit trail of all orchestrated migration pipelines ({totalItems} records)
          </p>
        </div>

        <Link
          to="/workflows/new"
          className="flex items-center gap-2 py-2 px-3.5 rounded-lg bg-sky-600 hover:bg-sky-500 text-white font-medium text-sm transition-colors shadow-lg shadow-sky-600/20 w-fit"
        >
          <PlusCircle className="w-4 h-4" />
          <span>Launch Migration</span>
        </Link>
      </div>

      {/* Search & Filters */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 bg-slate-900/40 p-4 rounded-xl border border-slate-800">
        <form onSubmit={handleSearch} className="relative w-full md:w-80">
          <Search className="w-4 h-4 text-slate-500 absolute left-3 top-2.5" />
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search by workflow name..."
            className="w-full bg-slate-950/80 border border-slate-800 rounded-lg pl-9 pr-3 py-1.5 text-xs text-slate-200 placeholder-slate-600 focus:outline-none focus:border-sky-500"
          />
        </form>

        <div className="flex items-center gap-1.5 overflow-x-auto pb-1 md:pb-0">
          <Filter className="w-3.5 h-3.5 text-slate-500 mr-1 flex-shrink-0" />
          {FILTER_STATES.map((st) => (
            <button
              key={st}
              onClick={() => {
                setSelectedState(st);
                setPage(1);
              }}
              className={`px-2.5 py-1 rounded-md text-xs font-mono font-medium whitespace-nowrap transition-colors ${
                selectedState === st
                  ? "bg-sky-500 text-white shadow-sm"
                  : "bg-slate-950/60 text-slate-400 hover:text-slate-200 hover:bg-slate-900 border border-slate-800/80"
              }`}
            >
              {st}
            </button>
          ))}
        </div>
      </div>

      {/* Main Table */}
      <div className="rounded-xl border border-slate-800 bg-slate-900/40 overflow-hidden">
        {loading ? (
          <div className="text-center py-16 text-slate-500 text-sm">Loading workflow ledger...</div>
        ) : workflows.length === 0 ? (
          <div className="text-center py-16 text-slate-500 text-sm">
            No workflows found matching the specified criteria.
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm text-slate-300">
              <thead className="text-xs text-slate-400 uppercase bg-slate-950/60 border-b border-slate-800">
                <tr>
                  <th className="py-3 px-4">Workflow & Job ID</th>
                  <th className="py-3 px-4">Source / Target</th>
                  <th className="py-3 px-4">State</th>
                  <th className="py-3 px-4">Progress</th>
                  <th className="py-3 px-4">Created</th>
                  <th className="py-3 px-4 text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/60">
                {workflows.map((wf) => (
                  <tr key={wf.id} className="hover:bg-slate-900/60 transition-colors">
                    <td className="py-3 px-4">
                      <Link
                        to={`/workflows/${wf.id}`}
                        className="font-medium text-white hover:text-sky-400 transition-colors flex items-center gap-1.5"
                      >
                        {wf.workflow_name}
                      </Link>
                      <span className="text-[11px] font-mono text-slate-500 block">
                        {wf.id}
                      </span>
                    </td>
                    <td className="py-3 px-4 text-xs font-mono text-slate-400">
                      <div>{wf.source_type}</div>
                      <div className="text-sky-400">→ {wf.target_dynamodb_table}</div>
                    </td>
                    <td className="py-3 px-4">
                      <WorkflowStateBadge state={wf.current_state} size="sm" />
                    </td>
                    <td className="py-3 px-4 w-44">
                      <div className="flex items-center gap-2">
                        <div className="w-full bg-slate-800 rounded-full h-2 overflow-hidden">
                          <div
                            className={`h-2 rounded-full ${
                              wf.current_state === "COMPLETED"
                                ? "bg-emerald-500"
                                : wf.current_state === "FAILED"
                                ? "bg-rose-500"
                                : "bg-sky-500 animate-pulse"
                            }`}
                            style={{ width: `${wf.progress_percentage}%` }}
                          ></div>
                        </div>
                        <span className="text-xs font-mono text-slate-400 w-10 text-right">
                          {wf.progress_percentage}%
                        </span>
                      </div>
                      <div className="text-[10px] text-slate-500 font-mono mt-0.5">
                        {wf.records_processed} / {wf.records_total} records
                      </div>
                    </td>
                    <td className="py-3 px-4 text-xs text-slate-400 font-mono">
                      {formatDate(wf.created_at)}
                    </td>
                    <td className="py-3 px-4 text-right space-x-2">
                      {wf.current_state === "FAILED" && (
                        <button
                          onClick={() => handleRetry(wf.id)}
                          disabled={actionLoading === wf.id}
                          className="px-2 py-1 rounded bg-amber-500/10 hover:bg-amber-500/20 text-amber-400 border border-amber-500/30 text-xs font-medium inline-flex items-center gap-1 transition-colors"
                          title="Retry workflow"
                        >
                          <RotateCcw className="w-3 h-3" />
                          <span>Retry</span>
                        </button>
                      )}

                      {wf.current_state !== "COMPLETED" && wf.current_state !== "FAILED" && (
                        <button
                          onClick={() => handleCancel(wf.id)}
                          disabled={actionLoading === wf.id}
                          className="px-2 py-1 rounded bg-rose-500/10 hover:bg-rose-500/20 text-rose-400 border border-rose-500/30 text-xs font-medium inline-flex items-center gap-1 transition-colors"
                          title="Abort workflow"
                        >
                          <XCircle className="w-3 h-3" />
                          <span>Cancel</span>
                        </button>
                      )}

                      <Link
                        to={`/workflows/${wf.id}`}
                        className="px-2.5 py-1 rounded bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs font-medium inline-block transition-colors"
                      >
                        Inspect
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {/* Pagination Footer */}
        {totalPages > 1 && (
          <div className="p-4 border-t border-slate-800 flex items-center justify-between text-xs text-slate-400">
            <div>
              Page {page} of {totalPages} ({totalItems} total workflows)
            </div>
            <div className="flex items-center gap-2">
              <button
                onClick={() => setPage((p) => Math.max(1, p - 1))}
                disabled={page <= 1}
                className="p-1 rounded bg-slate-800 hover:bg-slate-700 text-slate-300 disabled:opacity-40"
              >
                <ChevronLeft className="w-4 h-4" />
              </button>
              <button
                onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                disabled={page >= totalPages}
                className="p-1 rounded bg-slate-800 hover:bg-slate-700 text-slate-300 disabled:opacity-40"
              >
                <ChevronRight className="w-4 h-4" />
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};
