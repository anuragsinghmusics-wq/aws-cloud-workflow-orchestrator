import React, { useEffect, useState } from "react";
import { Plus, Trash2, Copy, Check, AlertTriangle } from "lucide-react";
import { apiKeyService } from "../services/api";
import type { ApiKey } from "../types";

export const ApiKeys: React.FC = () => {
  const [keys, setKeys] = useState<ApiKey[]>([]);
  const [loading, setLoading] = useState(true);
  const [keyName, setKeyName] = useState("");
  const [createdKey, setCreatedKey] = useState<ApiKey | null>(null);
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchKeys = async () => {
    setLoading(true);
    try {
      const data = await apiKeyService.listApiKeys();
      setKeys(data);
    } catch {
      // Ignore
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchKeys();
  }, []);

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    if (!keyName.trim()) return;

    try {
      const newKey = await apiKeyService.createApiKey(keyName.trim());
      setCreatedKey(newKey);
      setKeyName("");
      await fetchKeys();
    } catch (err: unknown) {
      setError("Failed to generate API key.");
    }
  };

  const handleRevoke = async (id: string) => {
    if (!window.confirm("Revoking this API key is irreversible. Continue?")) return;
    try {
      await apiKeyService.revokeApiKey(id);
      await fetchKeys();
    } catch {
      // Ignore
    }
  };

  const handleCopy = () => {
    if (createdKey?.raw_key) {
      navigator.clipboard.writeText(createdKey.raw_key);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  };

  return (
    <div className="space-y-6 max-w-4xl mx-auto">
      <div>
        <h1 className="text-2xl font-bold text-white tracking-tight">Programmatic API Keys</h1>
        <p className="text-sm text-slate-400 mt-1">
          Machine-to-machine authentication tokens for CI/CD pipelines and external services
        </p>
      </div>

      {/* Newly Created Secret Banner */}
      {createdKey?.raw_key && (
        <div className="p-4 rounded-xl border border-amber-500/30 bg-amber-500/10 text-amber-200">
          <div className="flex items-center gap-2 font-semibold text-xs text-amber-300 uppercase tracking-wider mb-2">
            <AlertTriangle className="w-4 h-4 text-amber-400" />
            <span>Save Your Secret API Key Now</span>
          </div>
          <p className="text-xs text-amber-300/80 mb-3">
            This secret key will <strong>never be displayed again</strong>. Store it securely in your secret manager.
          </p>
          <div className="flex items-center gap-2 bg-slate-950 p-2.5 rounded-lg border border-amber-500/20 font-mono text-xs">
            <span className="flex-1 select-all break-all text-white font-medium">
              {createdKey.raw_key}
            </span>
            <button
              onClick={handleCopy}
              className="px-2.5 py-1 rounded bg-amber-500/20 hover:bg-amber-500/30 text-amber-300 text-xs font-medium flex items-center gap-1 transition-colors flex-shrink-0"
            >
              {copied ? <Check className="w-3.5 h-3.5" /> : <Copy className="w-3.5 h-3.5" />}
              <span>{copied ? "Copied" : "Copy"}</span>
            </button>
          </div>
        </div>
      )}

      {/* Generate API Key Form */}
      <form onSubmit={handleCreate} className="p-5 rounded-xl border border-slate-800 bg-slate-900/40">
        <h2 className="text-sm font-semibold text-white mb-1">Generate New API Key</h2>
        <p className="text-xs text-slate-400 mb-4">
          Assign a descriptive name identifying the consuming application or runner
        </p>

        {error && <div className="text-xs text-rose-400 mb-3">{error}</div>}

        <div className="flex gap-3">
          <input
            type="text"
            required
            value={keyName}
            onChange={(e) => setKeyName(e.target.value)}
            placeholder="e.g. GitHub Actions CI/CD Deployment"
            className="flex-1 bg-slate-950/80 border border-slate-800 rounded-lg px-3 py-2 text-sm text-slate-200 placeholder-slate-600 focus:outline-none focus:border-sky-500"
          />
          <button
            type="submit"
            className="flex items-center gap-1.5 py-2 px-4 rounded-lg bg-sky-600 hover:bg-sky-500 text-white font-medium text-sm transition-colors shadow-lg shadow-sky-600/20 flex-shrink-0"
          >
            <Plus className="w-4 h-4" />
            <span>Generate Key</span>
          </button>
        </div>
      </form>

      {/* Active API Keys Table */}
      <div className="rounded-xl border border-slate-800 bg-slate-900/40 overflow-hidden">
        <div className="p-4 border-b border-slate-800">
          <h2 className="text-sm font-semibold text-white">Active API Keys</h2>
        </div>

        {loading ? (
          <div className="text-center py-12 text-slate-500 text-xs">Loading keys...</div>
        ) : keys.length === 0 ? (
          <div className="text-center py-12 text-slate-500 text-xs">
            No active API keys found. Generate a key above to enable machine authentication.
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs text-slate-300">
              <thead className="uppercase text-[11px] text-slate-500 bg-slate-950/60 border-b border-slate-800">
                <tr>
                  <th className="py-2.5 px-4">Name</th>
                  <th className="py-2.5 px-4">Prefix</th>
                  <th className="py-2.5 px-4">Created</th>
                  <th className="py-2.5 px-4">Last Used</th>
                  <th className="py-2.5 px-4 text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/60">
                {Array.isArray(keys) && keys.map((k) => (
                  <tr key={k.id} className="hover:bg-slate-900/40">
                    <td className="py-3 px-4 font-medium text-white">{k.name}</td>
                    <td className="py-3 px-4 font-mono text-slate-400">{k.prefix}...</td>
                    <td className="py-3 px-4 font-mono text-slate-400">
                      {k.created_at ? (() => {
                        try {
                          const d = new Date(k.created_at);
                          return isNaN(d.getTime()) ? "—" : d.toLocaleDateString();
                        } catch {
                          return "—";
                        }
                      })() : "—"}
                    </td>
                    <td className="py-3 px-4 font-mono text-slate-400">
                      {k.last_used_at ? (() => {
                        try {
                          const d = new Date(k.last_used_at);
                          return isNaN(d.getTime()) ? "Never" : d.toLocaleDateString();
                        } catch {
                          return "Never";
                        }
                      })() : "Never"}
                    </td>
                    <td className="py-3 px-4 text-right">
                      <button
                        onClick={() => handleRevoke(k.id)}
                        className="p-1 rounded text-slate-500 hover:text-rose-400 hover:bg-slate-800 transition-colors"
                        title="Revoke key"
                      >
                        <Trash2 className="w-4 h-4" />
                      </button>
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
