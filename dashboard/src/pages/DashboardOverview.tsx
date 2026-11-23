import React, { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  GitMerge,
  CheckCircle2,
  AlertTriangle,
  Cpu,
  Layers,
  ArrowRight,
  RefreshCw,
  PlusCircle,
  Database,
} from "lucide-react";
import { metricsService, workflowService } from "../services/api";
import { WorkflowStateBadge } from "../components/WorkflowStateBadge";
import type { SystemMetrics, Workflow } from "../types";

export const DashboardOverview: React.FC = () => {
  const [metrics, setMetrics] = useState<SystemMetrics | null>(null);
  const [recentWorkflows, setRecentWorkflows] = useState<Workflow[]>([]);
  const [loading, setLoading] = useState(true);

  const fetchData = async () => {
    setLoading(true);
    try {
      const [m, w] = await Promise.all([
        metricsService.getMetrics().catch(() => null),
        workflowService.listWorkflows({ page: 1, page_size: 5 }).catch(() => null),
      ]);
      if (m) setMetrics(m);
      if (w && Array.isArray(w.items)) {
        setRecentWorkflows(w.items);
      }
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, 10000); // 10s auto-refresh
    return () => clearInterval(interval);
  }, []);

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-white tracking-tight">Dashboard Overview</h1>
          <p className="text-sm text-slate-400 mt-1">
            Real-time telemetry, migration job metrics, and cluster health
          </p>
        </div>

        <div className="flex items-center gap-3">
          <button
            onClick={fetchData}
            disabled={loading}
            className="p-2 rounded-lg border border-slate-800 bg-slate-900/60 hover:bg-slate-900 text-slate-400 hover:text-white transition-colors"
            title="Refresh Metrics"
          >
            <RefreshCw className={`w-4 h-4 ${loading ? "animate-spin" : ""}`} />
          </button>
          <Link
            to="/workflows/new"
            className="flex items-center gap-2 py-2 px-3.5 rounded-lg bg-sky-600 hover:bg-sky-500 text-white font-medium text-sm transition-colors shadow-lg shadow-sky-600/20"
          >
            <PlusCircle className="w-4 h-4" />
            <span>New Migration</span>
          </Link>
        </div>
      </div>

      {/* 4 Top KPI Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        {/* Card 1: Workflows Total & Success Rate */}
        <div className="p-5 rounded-xl border border-slate-800 bg-slate-900/40 backdrop-blur">
          <div className="flex items-center justify-between text-slate-400 mb-3">
            <span className="text-xs font-medium uppercase tracking-wider">Migration Jobs</span>
            <GitMerge className="w-4 h-4 text-sky-400" />
          </div>
          <div className="flex items-baseline gap-2">
            <span className="text-3xl font-bold text-white font-mono">
              {metrics?.workflows?.total ?? 0}
            </span>
            <span className="text-xs text-slate-400">total registered</span>
          </div>
          <div className="mt-3 flex items-center gap-2 text-xs text-emerald-400">
            <CheckCircle2 className="w-3.5 h-3.5" />
            <span>{metrics?.workflows?.success_rate_percent ?? 100}% Success Rate</span>
          </div>
        </div>

        {/* Card 2: Records Volume */}
        <div className="p-5 rounded-xl border border-slate-800 bg-slate-900/40 backdrop-blur">
          <div className="flex items-center justify-between text-slate-400 mb-3">
            <span className="text-xs font-medium uppercase tracking-wider">Records Migrated</span>
            <Database className="w-4 h-4 text-purple-400" />
          </div>
          <div className="flex items-baseline gap-2">
            <span className="text-3xl font-bold text-white font-mono">
              {metrics?.records?.total_processed?.toLocaleString() ?? 0}
            </span>
            <span className="text-xs text-slate-400">
              / {metrics?.records?.total_submitted?.toLocaleString() ?? 0}
            </span>
          </div>
          <div className="mt-3 flex items-center gap-2 text-xs text-rose-400">
            <AlertTriangle className="w-3.5 h-3.5" />
            <span>{metrics?.records?.total_failed ?? 0} Failed Records</span>
          </div>
        </div>

        {/* Card 3: Worker Concurrency */}
        <div className="p-5 rounded-xl border border-slate-800 bg-slate-900/40 backdrop-blur">
          <div className="flex items-center justify-between text-slate-400 mb-3">
            <span className="text-xs font-medium uppercase tracking-wider">Celery Workers</span>
            <Layers className="w-4 h-4 text-indigo-400" />
          </div>
          <div className="flex items-baseline gap-2">
            <span className="text-3xl font-bold text-white font-mono">
              {metrics?.system?.concurrency_limit ?? 4}
            </span>
            <span className="text-xs text-slate-400">parallel threads</span>
          </div>
          <div className="mt-3 text-xs text-slate-400">
            Redis task queue broker connected
          </div>
        </div>

        {/* Card 4: System Host CPU/Memory */}
        <div className="p-5 rounded-xl border border-slate-800 bg-slate-900/40 backdrop-blur">
          <div className="flex items-center justify-between text-slate-400 mb-3">
            <span className="text-xs font-medium uppercase tracking-wider">Host Resources</span>
            <Cpu className="w-4 h-4 text-emerald-400" />
          </div>
          <div className="flex items-baseline gap-2">
            <span className="text-3xl font-bold text-white font-mono">
              {metrics?.system?.cpu_percent ?? 0}%
            </span>
            <span className="text-xs text-slate-400">CPU Load</span>
          </div>
          <div className="mt-3 text-xs text-slate-400 font-mono">
            Mem: {metrics?.system?.memory_used_mb ?? 0} MB ({metrics?.system?.memory_percent ?? 0}%)
          </div>
        </div>
      </div>

      {/* State Machine Distribution Grid */}
      <div className="p-6 rounded-xl border border-slate-800 bg-slate-900/40">
        <h2 className="text-sm font-semibold text-slate-200 uppercase tracking-wider mb-4">
          Pipeline State Distribution
        </h2>
        <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-7 gap-3">
          {[
            { state: "PENDING", label: "Pending" },
            { state: "EXTRACTING", label: "Extracting" },
            { state: "TRANSFORMING", label: "Transforming" },
            { state: "LOADING", label: "Loading" },
            { state: "VERIFYING", label: "Verifying" },
            { state: "COMPLETED", label: "Completed" },
            { state: "FAILED", label: "Failed" },
          ].map((item) => {
            const count = metrics?.workflows?.by_state?.[item.state] ?? 0;
            return (
              <div
                key={item.state}
                className="p-3 rounded-lg border border-slate-800/80 bg-slate-950/40 flex flex-col items-center justify-center text-center"
              >
                <span className="text-2xl font-bold font-mono text-white mb-1">{count}</span>
                <WorkflowStateBadge state={item.state} size="sm" />
              </div>
            );
          })}
        </div>
      </div>

      {/* Recent Workflows Table */}
      <div className="p-6 rounded-xl border border-slate-800 bg-slate-900/40">
        <div className="flex items-center justify-between mb-4">
          <div>
            <h2 className="text-base font-semibold text-white">Recent Migration Workflows</h2>
            <p className="text-xs text-slate-400">Latest active and completed data transfer jobs</p>
          </div>
          <Link
            to="/workflows"
            className="text-xs font-medium text-sky-400 hover:text-sky-300 flex items-center gap-1"
          >
            <span>View All Ledger</span>
            <ArrowRight className="w-3.5 h-3.5" />
          </Link>
        </div>

        {(!recentWorkflows || recentWorkflows.length === 0) ? (
          <div className="text-center py-12 text-slate-500 text-sm">
            No workflows recorded yet. Click "New Migration" to launch your first job.
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm text-slate-300">
              <thead className="text-xs text-slate-400 uppercase bg-slate-950/60 border-b border-slate-800">
                <tr>
                  <th className="py-3 px-4">Workflow Name</th>
                  <th className="py-3 px-4">Target Table</th>
                  <th className="py-3 px-4">Status</th>
                  <th className="py-3 px-4">Progress</th>
                  <th className="py-3 px-4">Records</th>
                  <th className="py-3 px-4 text-right">Action</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/60">
                {Array.isArray(recentWorkflows) && recentWorkflows.map((wf) => (
                  <tr key={wf.id} className="hover:bg-slate-900/60 transition-colors">
                    <td className="py-3 px-4">
                      <Link
                        to={`/workflows/${wf.id}`}
                        className="font-medium text-white hover:text-sky-400 transition-colors flex items-center gap-2"
                      >
                        {wf.workflow_name}
                      </Link>
                      <span className="text-[11px] font-mono text-slate-500 block truncate max-w-[200px]">
                        {wf.id}
                      </span>
                    </td>
                    <td className="py-3 px-4 font-mono text-xs text-slate-400">
                      {wf.target_dynamodb_table}
                    </td>
                    <td className="py-3 px-4">
                      <WorkflowStateBadge state={wf.current_state} size="sm" />
                    </td>
                    <td className="py-3 px-4 w-44">
                      <div className="flex items-center gap-2">
                        <div className="w-full bg-slate-800 rounded-full h-2 overflow-hidden">
                          <div
                            className={`h-2 rounded-full transition-all duration-500 ${
                              wf.current_state === "COMPLETED"
                                ? "bg-emerald-500"
                                : wf.current_state === "FAILED"
                                ? "bg-rose-500"
                                : "bg-sky-500 animate-pulse"
                            }`}
                            style={{ width: `${wf.progress_percentage ?? 0}%` }}
                          ></div>
                        </div>
                        <span className="text-xs font-mono text-slate-400 w-10 text-right">
                          {wf.progress_percentage ?? 0}%
                        </span>
                      </div>
                    </td>
                    <td className="py-3 px-4 font-mono text-xs">
                      {wf.records_processed ?? 0} / {wf.records_total ?? 0}
                    </td>
                    <td className="py-3 px-4 text-right">
                      <Link
                        to={`/workflows/${wf.id}`}
                        className="text-xs font-medium text-sky-400 hover:text-sky-300"
                      >
                        Inspect →
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
};
