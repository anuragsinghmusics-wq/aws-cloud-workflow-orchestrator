import React from "react";
import { Check, Circle, AlertCircle, Clock } from "lucide-react";
import type { WorkflowState, WorkflowStep } from "../types";

interface Props {
  currentState: WorkflowState;
  steps?: WorkflowStep[];
}

const PHASES: { state: WorkflowState; label: string; desc: string }[] = [
  { state: "PENDING", label: "Queued", desc: "Enqueued in task scheduler" },
  { state: "EXTRACTING", label: "Extraction", desc: "Staging payload snapshot to S3" },
  { state: "TRANSFORMING", label: "Transform", desc: "Validating schema & mapping types" },
  { state: "LOADING", label: "Loading", desc: "Batch writing to DynamoDB target" },
  { state: "VERIFYING", label: "Verification", desc: "Matching checksums & audit record" },
  { state: "COMPLETED", label: "Completed", desc: "Migration finished successfully" },
];

export const FSMStepIndicator: React.FC<Props> = ({ currentState, steps = [] }) => {
  const isFailed = currentState === "FAILED";
  const currentIndex = PHASES.findIndex((p) => p.state === currentState);

  const getStepStatus = (index: number) => {
    if (isFailed) {
      if (index === currentIndex) return "failed";
      if (index < currentIndex) return "completed";
      return "upcoming";
    }
    if (currentState === "COMPLETED") return "completed";
    if (index < currentIndex) return "completed";
    if (index === currentIndex) return "current";
    return "upcoming";
  };

  const getDuration = (state: string) => {
    const step = steps.find((s) => s.to_state === state);
    if (step?.execution_duration_ms != null) {
      return `${step.execution_duration_ms.toFixed(1)}ms`;
    }
    return null;
  };

  return (
    <div className="w-full py-4">
      <div className="grid grid-cols-1 md:grid-cols-6 gap-3">
        {PHASES.map((phase, idx) => {
          const status = getStepStatus(idx);
          const duration = getDuration(phase.state);

          return (
            <div
              key={phase.state}
              className={`relative flex flex-col p-3 rounded-lg border transition-all ${
                status === "completed"
                  ? "bg-slate-900/80 border-emerald-500/40 text-emerald-300"
                  : status === "current"
                  ? "bg-sky-950/60 border-sky-500 text-sky-200 ring-1 ring-sky-500/50 animate-pulse"
                  : status === "failed"
                  ? "bg-rose-950/60 border-rose-500 text-rose-200"
                  : "bg-slate-900/30 border-slate-800 text-slate-500"
              }`}
            >
              <div className="flex items-center justify-between mb-2">
                <span className="text-xs font-mono font-medium tracking-wide uppercase opacity-75">
                  Phase 0{idx + 1}
                </span>
                <div className="flex items-center">
                  {status === "completed" && <Check className="w-4 h-4 text-emerald-400" />}
                  {status === "current" && <Clock className="w-4 h-4 text-sky-400 animate-spin" />}
                  {status === "failed" && <AlertCircle className="w-4 h-4 text-rose-400" />}
                  {status === "upcoming" && <Circle className="w-3.5 h-3.5 text-slate-600" />}
                </div>
              </div>

              <div className="font-semibold text-sm mb-0.5">{phase.label}</div>
              <div className="text-xs text-slate-400 line-clamp-1">{phase.desc}</div>

              {duration && (
                <div className="mt-2 text-[10px] font-mono px-1.5 py-0.5 rounded bg-slate-950/60 text-slate-400 inline-block w-fit">
                  {duration}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
};
