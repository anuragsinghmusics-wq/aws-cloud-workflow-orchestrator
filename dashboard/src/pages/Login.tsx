import React, { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Cloud, Lock, Mail, AlertCircle, ArrowRight } from "lucide-react";
import { authService } from "../services/api";

export const Login: React.FC = () => {
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setLoading(true);

    try {
      await authService.login(email, password);
      navigate("/");
    } catch (err: unknown) {
      if (err && typeof err === "object" && "response" in err) {
        const axErr = err as { response?: { data?: { message?: string } } };
        setError(axErr.response?.data?.message || "Invalid email or password.");
      } else {
        setError("Failed to connect to authentication service.");
      }
    } finally {
      setLoading(false);
    }
  };

  const handleQuickDemo = async (demoEmail: string) => {
    setEmail(demoEmail);
    setPassword("DemoPassword123!");
    try {
      // Auto-register demo account if needed
      await authService.register(demoEmail, "DemoPassword123!", "Cloud Administrator", "ADMIN").catch(() => {});
      await authService.login(demoEmail, "DemoPassword123!");
      navigate("/");
    } catch {
      setError("Failed to initialize demo session.");
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center p-4 bg-gradient-to-br from-slate-950 via-slate-900 to-slate-950">
      <div className="w-full max-w-md bg-slate-900/90 border border-slate-800 rounded-2xl p-8 shadow-2xl backdrop-blur">
        <div className="flex flex-col items-center text-center mb-8">
          <div className="w-12 h-12 rounded-xl bg-sky-500/10 border border-sky-500/30 flex items-center justify-center text-sky-400 mb-3 shadow-lg shadow-sky-500/5">
            <Cloud className="w-6 h-6" />
          </div>
          <h1 className="text-xl font-bold text-white tracking-tight">Cloud Workflow Orchestrator</h1>
          <p className="text-sm text-slate-400 mt-1">AWS S3 & DynamoDB Migration Engine</p>
        </div>

        {error && (
          <div className="mb-6 p-3 rounded-lg bg-rose-500/10 border border-rose-500/30 text-rose-300 text-xs flex items-center gap-2">
            <AlertCircle className="w-4 h-4 flex-shrink-0" />
            <span>{error}</span>
          </div>
        )}

        <form onSubmit={handleLogin} className="space-y-4">
          <div>
            <label className="block text-xs font-medium text-slate-300 mb-1.5">Email Address</label>
            <div className="relative">
              <Mail className="w-4 h-4 text-slate-500 absolute left-3 top-3" />
              <input
                type="email"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="developer@company.com"
                className="w-full bg-slate-950/80 border border-slate-800 rounded-lg pl-9 pr-3 py-2 text-sm text-slate-200 placeholder-slate-600 focus:outline-none focus:border-sky-500 focus:ring-1 focus:ring-sky-500"
              />
            </div>
          </div>

          <div>
            <label className="block text-xs font-medium text-slate-300 mb-1.5">Password</label>
            <div className="relative">
              <Lock className="w-4 h-4 text-slate-500 absolute left-3 top-3" />
              <input
                type="password"
                required
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="••••••••••••"
                className="w-full bg-slate-950/80 border border-slate-800 rounded-lg pl-9 pr-3 py-2 text-sm text-slate-200 placeholder-slate-600 focus:outline-none focus:border-sky-500 focus:ring-1 focus:ring-sky-500"
              />
            </div>
          </div>

          <button
            type="submit"
            disabled={loading}
            className="w-full mt-2 py-2.5 px-4 rounded-lg bg-sky-600 hover:bg-sky-500 text-white font-medium text-sm transition-colors flex items-center justify-center gap-2 shadow-lg shadow-sky-600/20 disabled:opacity-50"
          >
            {loading ? "Authenticating..." : "Sign In to Dashboard"}
            <ArrowRight className="w-4 h-4" />
          </button>
        </form>

        <div className="mt-6 pt-6 border-t border-slate-800/80">
          <div className="text-xs text-slate-400 text-center mb-3">Quick Demo Authentication:</div>
          <button
            onClick={() => handleQuickDemo("admin@company.com")}
            className="w-full py-1.5 px-3 rounded-lg border border-slate-800 hover:border-slate-700 bg-slate-950/60 text-xs font-mono text-slate-300 hover:text-white transition-colors text-center"
          >
            ⚡ Auto-Login as Admin (admin@company.com)
          </button>
        </div>

        <div className="mt-6 text-center text-xs text-slate-500">
          Need an account?{" "}
          <Link to="/register" className="text-sky-400 hover:underline">
            Register new profile
          </Link>
        </div>
      </div>
    </div>
  );
};
