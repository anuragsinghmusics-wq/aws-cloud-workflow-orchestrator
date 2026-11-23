import React, { useEffect, useState } from "react";
import { Cloud, LogOut, ShieldCheck, Activity } from "lucide-react";
import { authService, metricsService } from "../services/api";
import type { SystemHealth, User } from "../types";

export const Navbar: React.FC = () => {
  const [user, setUser] = useState<User | null>(null);
  const [health, setHealth] = useState<SystemHealth | null>(null);

  useEffect(() => {
    setUser(authService.getCurrentUser());
    metricsService
      .getHealth()
      .then(setHealth)
      .catch(() => setHealth(null));
  }, []);

  return (
    <header className="sticky top-0 z-40 w-full border-b border-slate-800 bg-slate-950/90 backdrop-blur px-6 py-3 flex items-center justify-between">
      <div className="flex items-center space-x-3">
        <div className="flex items-center justify-center w-9 h-9 rounded-lg bg-sky-500/10 border border-sky-500/30 text-sky-400">
          <Cloud className="w-5 h-5" />
        </div>
        <div>
          <span className="font-bold text-base tracking-tight text-white flex items-center gap-2">
            Cloud Workflow Orchestrator
            <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-sky-950 text-sky-400 border border-sky-800/60 uppercase">
              v1.0.0
            </span>
          </span>
          <span className="text-xs text-slate-400 block">
            AWS S3 & DynamoDB Migration Engine
          </span>
        </div>
      </div>

      <div className="flex items-center space-x-4">
        {/* Environment / Health Pill */}
        <div className="hidden sm:flex items-center space-x-2 text-xs px-2.5 py-1 rounded-full bg-slate-900 border border-slate-800">
          <Activity
            className={`w-3.5 h-3.5 ${
              health?.status === "HEALTHY" ? "text-emerald-400" : "text-amber-400 animate-pulse"
            }`}
          />
          <span className="text-slate-300 font-mono">
            {health?.status || "CONNECTING..."}
          </span>
          <span className="text-slate-600">|</span>
          <span className="text-slate-400 uppercase text-[10px]">
            {health?.environment || "LocalStack"}
          </span>
        </div>

        {/* User Profile */}
        {user && (
          <div className="flex items-center space-x-3 pl-3 border-l border-slate-800">
            <div className="text-right">
              <div className="text-xs font-medium text-slate-200">
                {user.full_name || (user.email ? user.email.split("@")[0] : "Admin")}
              </div>
              <div className="text-[10px] text-slate-400 font-mono flex items-center gap-1 justify-end">
                <ShieldCheck className="w-3 h-3 text-sky-400" />
                {user.role || "ADMIN"}
              </div>
            </div>

            <button
              onClick={() => authService.logout()}
              title="Sign Out"
              className="p-1.5 rounded-lg text-slate-400 hover:text-rose-400 hover:bg-slate-900 transition-colors"
            >
              <LogOut className="w-4 h-4" />
            </button>
          </div>
        )}
      </div>
    </header>
  );
};
