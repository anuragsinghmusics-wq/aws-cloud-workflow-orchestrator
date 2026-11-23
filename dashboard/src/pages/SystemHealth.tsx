import React, { useEffect, useState } from "react";
import { Activity, Database, HardDrive, RefreshCw, CheckCircle2, AlertCircle } from "lucide-react";
import { metricsService } from "../services/api";
import type { SystemHealth as HealthType } from "../types";

export const SystemHealth: React.FC = () => {
  const [health, setHealth] = useState<HealthType | null>(null);
  const [loading, setLoading] = useState(true);

  const fetchHealth = async () => {
    setLoading(true);
    try {
      const data = await metricsService.getHealth();
      setHealth(data);
    } catch (err: unknown) {
      if (err && typeof err === "object" && "response" in err) {
        const axErr = err as { response?: { data?: HealthType } };
        if (axErr.response?.data) {
          setHealth(axErr.response.data);
        }
      }
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchHealth();
  }, []);

  const getServiceIcon = (key: string) => {
    switch (key) {
      case "database":
        return <Database className="w-5 h-5 text-indigo-400" />;
      case "s3":
        return <HardDrive className="w-5 h-5 text-sky-400" />;
      case "dynamodb":
        return <Database className="w-5 h-5 text-purple-400" />;
      case "cloudwatch":
        return <Activity className="w-5 h-5 text-emerald-400" />;
      default:
        return <Activity className="w-5 h-5 text-slate-400" />;
    }
  };

  return (
    <div className="space-y-6 max-w-4xl mx-auto">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white tracking-tight">System Health & Probes</h1>
          <p className="text-sm text-slate-400 mt-1">
            Real-time diagnostic probes testing database, S3, DynamoDB, and CloudWatch connectivity
          </p>
        </div>

        <button
          onClick={fetchHealth}
          disabled={loading}
          className="flex items-center gap-1.5 py-2 px-3.5 rounded-lg border border-slate-800 bg-slate-900/60 hover:bg-slate-900 text-xs font-medium text-slate-300 hover:text-white transition-colors"
        >
          <RefreshCw className={`w-3.5 h-3.5 ${loading ? "animate-spin" : ""}`} />
          <span>Probe Now</span>
        </button>
      </div>

      {/* Overall Status Banner */}
      <div
        className={`p-5 rounded-xl border flex items-center justify-between ${
          health?.status === "HEALTHY"
            ? "bg-emerald-950/20 border-emerald-500/30 text-emerald-300"
            : "bg-amber-950/20 border-amber-500/30 text-amber-300"
        }`}
      >
        <div className="flex items-center gap-3">
          {health?.status === "HEALTHY" ? (
            <CheckCircle2 className="w-6 h-6 text-emerald-400 flex-shrink-0" />
          ) : (
            <AlertCircle className="w-6 h-6 text-amber-400 flex-shrink-0" />
          )}
          <div>
            <div className="font-semibold text-sm">Cluster Status: {health?.status || "UNKNOWN"}</div>
            <div className="text-xs opacity-80">
              API Version: {health?.version || "1.0.0"} | Mode: {health?.environment || "LocalStack"}
            </div>
          </div>
        </div>

        <span className="text-xs font-mono opacity-60">
          {health?.timestamp ? (() => {
            try {
              const d = new Date(health.timestamp);
              return isNaN(d.getTime()) ? "" : d.toLocaleTimeString();
            } catch {
              return "";
            }
          })() : ""}
        </span>
      </div>

      {/* Subsystem Component Probes Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {health?.components && typeof health.components === "object" &&
          Object.entries(health.components).map(([name, comp]) => (
            <div
              key={name}
              className="p-5 rounded-xl border border-slate-800 bg-slate-900/40 space-y-3"
            >
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2.5">
                  <div className="p-2 rounded-lg bg-slate-950 border border-slate-800">
                    {getServiceIcon(name)}
                  </div>
                  <div>
                    <span className="font-semibold text-sm text-white capitalize">{name}</span>
                    <span className="text-xs text-slate-500 block font-mono">
                      Subsystem Component
                    </span>
                  </div>
                </div>

                <span
                  className={`px-2 py-0.5 rounded text-[11px] font-mono font-semibold ${
                    comp?.status === "HEALTHY"
                      ? "bg-emerald-500/10 text-emerald-400 border border-emerald-500/20"
                      : "bg-amber-500/10 text-amber-400 border border-amber-500/20"
                  }`}
                >
                  {comp?.status || "UNKNOWN"}
                </span>
              </div>

              <div className="pt-2 border-t border-slate-800/60 flex items-center justify-between text-xs font-mono text-slate-400">
                <span>Round-Trip Latency:</span>
                <span className="text-white font-semibold">
                  {comp?.latency_ms != null ? `${comp.latency_ms} ms` : "—"}
                </span>
              </div>

              {comp?.details && typeof comp.details === "object" && Object.keys(comp.details).length > 0 && (
                <div className="p-2 rounded bg-slate-950 text-[11px] font-mono text-slate-400 overflow-x-auto">
                  {Object.entries(comp.details).map(([k, v]) => (
                    <div key={k}>
                      <span className="text-slate-500">{k}:</span> {String(v)}
                    </div>
                  ))}
                </div>
              )}
            </div>
          ))}
      </div>
    </div>
  );
};
