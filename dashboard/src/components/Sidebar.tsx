import React from "react";
import { NavLink } from "react-router-dom";
import { LayoutDashboard, GitMerge, PlusCircle, KeyRound, Activity } from "lucide-react";

export const Sidebar: React.FC = () => {
  const links = [
    { to: "/", label: "Dashboard Overview", icon: LayoutDashboard },
    { to: "/workflows", label: "Workflows Ledger", icon: GitMerge },
    { to: "/workflows/new", label: "Initiate Migration", icon: PlusCircle },
    { to: "/api-keys", label: "Programmatic API Keys", icon: KeyRound },
    { to: "/health", label: "System Health Probes", icon: Activity },
  ];

  return (
    <aside className="w-64 flex-shrink-0 border-r border-slate-800 bg-slate-950/60 p-4 flex flex-col justify-between">
      <nav className="space-y-1.5">
        <div className="text-[11px] font-semibold tracking-wider text-slate-500 uppercase px-3 py-2">
          Migration Orchestrator
        </div>
        {links.map((link) => {
          const Icon = link.icon;
          return (
            <NavLink
              key={link.to}
              to={link.to}
              end={link.to === "/"}
              className={({ isActive }) =>
                `flex items-center space-x-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-colors ${
                  isActive
                    ? "bg-sky-500/10 text-sky-400 border border-sky-500/30"
                    : "text-slate-400 hover:text-slate-200 hover:bg-slate-900"
                }`
              }
            >
              <Icon className="w-4 h-4" />
              <span>{link.label}</span>
            </NavLink>
          );
        })}
      </nav>

      <div className="p-3 rounded-lg border border-slate-800/80 bg-slate-900/40 text-xs text-slate-400">
        <div className="font-semibold text-slate-300 mb-1">LocalStack AWS Sandbox</div>
        <p className="text-[11px] leading-relaxed text-slate-400">
          S3 payload staging & DynamoDB target table live simulation.
        </p>
      </div>
    </aside>
  );
};
