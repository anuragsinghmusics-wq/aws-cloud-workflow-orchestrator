import React, { useState } from "react";
import { useNavigate, Link } from "react-router-dom";
import { PlusCircle, ArrowLeft, AlertCircle, Database, Sparkles } from "lucide-react";
import { workflowService } from "../services/api";

export const NewWorkflow: React.FC = () => {
  const navigate = useNavigate();
  const [workflowName, setWorkflowName] = useState("");
  const [sourceType, setSourceType] = useState("POSTGRES_SQL_DUMP");
  const [targetTable, setTargetTable] = useState("Production_Users_V2");
  const [batchSize, setBatchSize] = useState(25);
  const [payloadJson, setPayloadJson] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  // Sample presets for convenient testing
  const loadPresetUsers = () => {
    setWorkflowName(`users-migration-${Date.now().toString().slice(-4)}`);
    setSourceType("POSTGRES_SQL_DUMP");
    setTargetTable("Production_Users_V2");
    const sample = Array.from({ length: 15 }, (_, i) => ({
      user_id: `usr_${1000 + i}`,
      email: `engineer_${i + 1}@enterprise.io`,
      role: i === 0 ? "ADMIN" : "DEVELOPER",
      status: "ACTIVE",
      created_at: new Date().toISOString(),
    }));
    setPayloadJson(JSON.stringify(sample, null, 2));
  };

  const loadPresetOrders = () => {
    setWorkflowName(`orders-sync-${Date.now().toString().slice(-4)}`);
    setSourceType("JSON_STREAM");
    setTargetTable("Orders_Ledger");
    const sample = Array.from({ length: 25 }, (_, i) => ({
      order_id: `ord_${5000 + i}`,
      customer_id: `cust_${100 + (i % 5)}`,
      amount_cents: Math.floor(Math.random() * 50000) + 1000,
      currency: "USD",
      status: "SETTLED",
    }));
    setPayloadJson(JSON.stringify(sample, null, 2));
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);

    let parsedPayload: Record<string, unknown>[];
    try {
      const parsed = JSON.parse(payloadJson);
      if (!Array.isArray(parsed)) {
        throw new Error("Payload data must be a JSON array of objects.");
      }
      if (parsed.length === 0) {
        throw new Error("Payload cannot be empty.");
      }
      parsedPayload = parsed;
    } catch (parseErr: unknown) {
      setError(
        parseErr instanceof Error
          ? parseErr.message
          : "Invalid JSON format. Please provide a valid array of objects."
      );
      return;
    }

    setLoading(true);
    try {
      const wf = await workflowService.createWorkflow({
        workflow_name: workflowName,
        source_type: sourceType,
        target_dynamodb_table: targetTable,
        payload_data: parsedPayload,
        configuration: { batch_size: batchSize, max_retries: 3 },
      });
      navigate(`/workflows/${wf.id}`);
    } catch (err: unknown) {
      if (err && typeof err === "object" && "response" in err) {
        const axErr = err as { response?: { data?: { message?: string } } };
        setError(axErr.response?.data?.message || "Failed to initiate migration.");
      } else {
        setError("Network error while submitting workflow.");
      }
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="space-y-6 max-w-4xl mx-auto">
      {/* Top Breadcrumb */}
      <div>
        <Link
          to="/workflows"
          className="inline-flex items-center gap-1.5 text-xs font-medium text-slate-400 hover:text-white transition-colors mb-3"
        >
          <ArrowLeft className="w-3.5 h-3.5" />
          <span>Back to Workflows</span>
        </Link>
        <h1 className="text-2xl font-bold text-white tracking-tight">Initiate Migration Job</h1>
        <p className="text-sm text-slate-400 mt-1">
          Configure source payload staging to S3 and automated target loading to Amazon DynamoDB
        </p>
      </div>

      {error && (
        <div className="p-3.5 rounded-lg bg-rose-500/10 border border-rose-500/30 text-rose-300 text-xs flex items-center gap-2">
          <AlertCircle className="w-4 h-4 flex-shrink-0" />
          <span>{error}</span>
        </div>
      )}

      {/* Preset Buttons */}
      <div className="p-4 rounded-xl border border-sky-500/20 bg-sky-950/20 flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div className="flex items-center gap-2 text-xs text-sky-300 font-medium">
          <Sparkles className="w-4 h-4 text-sky-400" />
          <span>Need sample migration data?</span>
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={loadPresetUsers}
            className="px-2.5 py-1 rounded bg-sky-500/10 hover:bg-sky-500/20 border border-sky-500/30 text-xs font-mono text-sky-300 transition-colors"
          >
            ⚡ Load 15 Users
          </button>
          <button
            type="button"
            onClick={loadPresetOrders}
            className="px-2.5 py-1 rounded bg-purple-500/10 hover:bg-purple-500/20 border border-purple-500/30 text-xs font-mono text-purple-300 transition-colors"
          >
            ⚡ Load 25 Orders
          </button>
        </div>
      </div>

      <form onSubmit={handleSubmit} className="p-6 rounded-xl border border-slate-800 bg-slate-900/40 space-y-5">
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <div>
            <label className="block text-xs font-medium text-slate-300 mb-1.5">Workflow Name</label>
            <input
              type="text"
              required
              value={workflowName}
              onChange={(e) => setWorkflowName(e.target.value)}
              placeholder="e.g. pg-users-to-dynamodb"
              className="w-full bg-slate-950/80 border border-slate-800 rounded-lg px-3 py-2 text-sm text-slate-200 placeholder-slate-600 focus:outline-none focus:border-sky-500"
            />
          </div>

          <div>
            <label className="block text-xs font-medium text-slate-300 mb-1.5">Source Type</label>
            <select
              value={sourceType}
              onChange={(e) => setSourceType(e.target.value)}
              className="w-full bg-slate-950/80 border border-slate-800 rounded-lg px-3 py-2 text-sm text-slate-200 focus:outline-none focus:border-sky-500"
            >
              <option value="POSTGRES_SQL_DUMP">POSTGRES_SQL_DUMP</option>
              <option value="CSV">CSV</option>
              <option value="JSON_STREAM">JSON_STREAM</option>
              <option value="MYSQL_DUMP">MYSQL_DUMP</option>
            </select>
          </div>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <div>
            <label className="block text-xs font-medium text-slate-300 mb-1.5">
              Target DynamoDB Table Name
            </label>
            <div className="relative">
              <Database className="w-4 h-4 text-slate-500 absolute left-3 top-2.5" />
              <input
                type="text"
                required
                value={targetTable}
                onChange={(e) => setTargetTable(e.target.value)}
                placeholder="Production_Users_V2"
                className="w-full bg-slate-950/80 border border-slate-800 rounded-lg pl-9 pr-3 py-2 text-sm text-slate-200 placeholder-slate-600 focus:outline-none focus:border-sky-500 font-mono text-xs"
              />
            </div>
          </div>

          <div>
            <label className="block text-xs font-medium text-slate-300 mb-1.5">
              Batch Write Chunk Size (1 - 25)
            </label>
            <input
              type="number"
              min={1}
              max={25}
              value={batchSize}
              onChange={(e) => setBatchSize(Number(e.target.value))}
              className="w-full bg-slate-950/80 border border-slate-800 rounded-lg px-3 py-2 text-sm text-slate-200 focus:outline-none focus:border-sky-500 font-mono text-xs"
            />
          </div>
        </div>

        <div>
          <label className="block text-xs font-medium text-slate-300 mb-1.5">
            Payload Records (JSON Array of Objects)
          </label>
          <textarea
            required
            rows={10}
            value={payloadJson}
            onChange={(e) => setPayloadJson(e.target.value)}
            placeholder='[\n  {\n    "id": "101",\n    "name": "Alice"\n  }\n]'
            className="w-full bg-slate-950 border border-slate-800 rounded-lg p-3 font-mono text-xs text-slate-200 placeholder-slate-700 focus:outline-none focus:border-sky-500"
          ></textarea>
        </div>

        <div className="pt-2 flex items-center justify-end gap-3">
          <Link
            to="/workflows"
            className="px-4 py-2 rounded-lg border border-slate-800 hover:bg-slate-900 text-sm font-medium text-slate-300 transition-colors"
          >
            Cancel
          </Link>
          <button
            type="submit"
            disabled={loading}
            className="flex items-center gap-2 py-2 px-4 rounded-lg bg-sky-600 hover:bg-sky-500 text-white font-medium text-sm transition-colors shadow-lg shadow-sky-600/20 disabled:opacity-50"
          >
            <PlusCircle className="w-4 h-4" />
            <span>{loading ? "Enqueuing Pipeline..." : "Launch Migration"}</span>
          </button>
        </div>
      </form>
    </div>
  );
};
