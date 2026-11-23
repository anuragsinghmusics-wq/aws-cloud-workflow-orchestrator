import React from "react";
import type { WorkflowState } from "../types";

interface Props {
  state: WorkflowState | string;
  size?: "sm" | "md" | "lg";
}

export const WorkflowStateBadge: React.FC<Props> = ({ state, size = "md" }) => {
  const getColors = () => {
    switch (state) {
      case "COMPLETED":
        return "bg-emerald-500/10 text-emerald-400 border-emerald-500/30";
      case "FAILED":
        return "bg-rose-500/10 text-rose-400 border-rose-500/30";
      case "PENDING":
        return "bg-amber-500/10 text-amber-400 border-amber-500/30";
      case "EXTRACTING":
        return "bg-sky-500/10 text-sky-400 border-sky-500/30 animate-pulse";
      case "TRANSFORMING":
        return "bg-indigo-500/10 text-indigo-400 border-indigo-500/30 animate-pulse";
      case "LOADING":
        return "bg-purple-500/10 text-purple-400 border-purple-500/30 animate-pulse";
      case "VERIFYING":
        return "bg-teal-500/10 text-teal-400 border-teal-500/30 animate-pulse";
      default:
        return "bg-slate-500/10 text-slate-400 border-slate-500/30";
    }
  };

  const sizeClasses = {
    sm: "px-2 py-0.5 text-xs",
    md: "px-2.5 py-1 text-xs",
    lg: "px-3 py-1.5 text-sm",
  }[size];

  return (
    <span
      className={`inline-flex items-center font-medium rounded-full border ${getColors()} ${sizeClasses}`}
    >
      <span className="w-1.5 h-1.5 mr-1.5 rounded-full bg-current"></span>
      {state}
    </span>
  );
};
