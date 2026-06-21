"use client";

import React, { useMemo, useState } from "react";
import { useStore } from "@/store/useStore";
import { 
  ArrowRight, 
  HelpCircle, 
  ExternalLink,
  ChevronRight,
  MapPin,
  ClipboardList
} from "lucide-react";

interface ApplicationPipelineProps {
  onSelectApplication: (app: any) => void;
}

const COLUMNS = [
  { 
    id: "SHORTLISTED", 
    title: "Shortlisted", 
    statuses: ["SHORTLISTED", "READY"], 
    dotColor: "bg-emerald-400", 
    badgeClass: "bg-emerald-950/30 text-emerald-400 border border-emerald-900/30"
  },
  { 
    id: "APPLYING", 
    title: "Applying", 
    statuses: ["APPLYING", "RETRY_PENDING"], 
    dotColor: "bg-blue-400", 
    badgeClass: "bg-blue-950/30 text-blue-400 border border-blue-900/30" 
  },
  { 
    id: "SUBMITTED", 
    title: "Submitted", 
    statuses: ["SUBMITTED", "LIMIT_EXCEEDED"], 
    dotColor: "bg-teal-400", 
    badgeClass: "bg-teal-950/30 text-teal-400 border border-teal-900/30"
  },
  { 
    id: "INTERVIEW", 
    title: "Interviewing", 
    statuses: ["INTERVIEW", "INTERVIEWING", "INTERVIEW_SCHEDULED", "OA_RECEIVED"], 
    dotColor: "bg-purple-400", 
    badgeClass: "bg-purple-950/30 text-purple-400 border border-purple-900/30"
  },
  { 
    id: "OFFER", 
    title: "Offers", 
    statuses: ["OFFER", "OFFER_ACCEPTED", "OFFER_DECLINED"], 
    dotColor: "bg-amber-400", 
    badgeClass: "bg-amber-950/30 text-amber-400 border border-amber-900/30"
  }
];

export default function ApplicationPipeline({ onSelectApplication }: ApplicationPipelineProps) {
  const { applications, updateApplicationStatus, addLogLine } = useStore();
  const [draggedAppId, setDraggedAppId] = useState<string | null>(null);

  // Group applications by Kanban column ID
  const groupedApps = useMemo(() => {
    const groups: Record<string, any[]> = {
      SHORTLISTED: [],
      APPLYING: [],
      SUBMITTED: [],
      INTERVIEW: [],
      OFFER: []
    };

    applications.forEach(app => {
      const status = (app.status || "").toUpperCase();
      // Find matching column
      const col = COLUMNS.find(c => c.statuses.includes(status));
      if (col) {
        groups[col.id].push(app);
      }
    });

    return groups;
  }, [applications]);

  // Handle Drag Start
  const handleDragStart = (id: string, e: React.DragEvent) => {
    setDraggedAppId(id);
    e.dataTransfer.setData("text/plain", id);
    e.dataTransfer.effectAllowed = "move";
  };

  // Handle Drag Over (must prevent default to allow drop)
  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
  };

  // Handle Drop
  const handleDrop = async (columnId: string, e: React.DragEvent) => {
    e.preventDefault();
    const id = e.dataTransfer.getData("text/plain") || draggedAppId;
    if (!id) return;
    
    setDraggedAppId(null);
    const app = applications.find(a => a.id === id);
    if (!app) return;

    // Resolve corresponding status to set
    let targetStatus = columnId;
    if (columnId === "SHORTLISTED") targetStatus = "SHORTLISTED";
    if (columnId === "APPLYING") targetStatus = "APPLYING";
    if (columnId === "SUBMITTED") targetStatus = "SUBMITTED";
    if (columnId === "INTERVIEW") targetStatus = "INTERVIEW";
    if (columnId === "OFFER") targetStatus = "OFFER";

    // Skip if status didn't change
    if (app.status === targetStatus) return;

    addLogLine(`[Kanban] Dragged ${app.job_posting?.company_name} to ${columnId}`);
    await updateApplicationStatus(id, targetStatus);
  };

  // Quick move status via button click
  const handleQuickMove = async (id: string, nextStatus: string, company: string) => {
    addLogLine(`[Kanban] Moving ${company} to ${nextStatus}...`);
    await updateApplicationStatus(id, nextStatus);
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h3 className="font-semibold text-xs text-zinc-300 uppercase tracking-wider flex items-center gap-1.5">
            <ClipboardList className="w-4 h-4 text-emerald-500" />
            Application Execution Pipeline
          </h3>
          <p className="text-[10px] text-zinc-500 font-sans mt-0.5">
            Drag cards to manually advance them or click on card details to view submission logs
          </p>
        </div>
      </div>

      {/* Columns Grid */}
      <div className="grid grid-cols-1 md:grid-cols-5 gap-4 overflow-x-auto pb-4">
        {COLUMNS.map((col) => {
          const apps = groupedApps[col.id] || [];
          return (
            <div
              key={col.id}
              onDragOver={handleDragOver}
              onDrop={(e) => handleDrop(col.id, e)}
              className="flex flex-col bg-zinc-950/20 border border-zinc-900/60 rounded-xl min-h-[450px] max-h-[520px] w-full"
            >
              {/* Column Header */}
              <div className="px-4 py-3.5 border-b border-zinc-900/60 flex items-center justify-between">
                <span className="font-semibold text-xs text-zinc-300 tracking-wide flex items-center gap-2">
                  <span className={`h-1.5 w-1.5 rounded-full ${col.dotColor}`} />
                  {col.title}
                </span>
                <span className={`px-2 py-0.5 rounded-full text-[9px] font-mono ${col.badgeClass}`}>
                  {apps.length}
                </span>
              </div>

              {/* Cards list */}
              <div className="flex-1 p-2.5 overflow-y-auto space-y-2.5 scrollbar-thin">
                {apps.length === 0 ? (
                  <div className="h-full flex items-center justify-center border border-dashed border-zinc-900/30 rounded-xl py-12 text-center text-zinc-650 italic text-[10px] font-mono">
                    Drop items here
                  </div>
                ) : (
                  apps.map((app) => (
                    <div
                      key={app.id}
                      draggable
                      onDragStart={(e) => handleDragStart(app.id, e)}
                      onClick={() => onSelectApplication(app)}
                      className="group p-4 bg-zinc-900/25 border border-zinc-900 hover:border-zinc-800 hover:bg-zinc-900/40 rounded-lg cursor-grab active:cursor-grabbing transition-all duration-200 relative shadow-sm"
                    >
                      <div className="space-y-2">
                        {/* Company & Rating */}
                        <div className="flex items-start justify-between gap-2">
                          <span className="font-medium text-[12px] text-zinc-200 group-hover:text-white truncate flex-1 leading-tight">
                            {app.job_posting?.company_name || "Company"}
                          </span>
                          <span className={`px-1.5 py-0.2 rounded font-mono text-[9px] font-semibold border ${
                            app.match_score >= 75 
                              ? "text-emerald-450 bg-emerald-950/20 border-emerald-900/20" 
                              : "text-amber-450 bg-amber-950/20 border-amber-900/20"
                          }`}>
                            {app.match_score ? Math.round(app.match_score) : 0}%
                          </span>
                        </div>

                        {/* Title */}
                        <div className="text-[10.5px] text-zinc-400 font-sans truncate">
                          {app.job_posting?.role_title || "Developer Position"}
                        </div>

                        {/* Details line */}
                        <div className="flex items-center justify-between text-[9px] text-zinc-500 font-mono">
                          <span className="flex items-center gap-0.5 truncate max-w-[90px]">
                            <MapPin className="w-2.5 h-2.5 shrink-0" />
                            {app.job_posting?.location || "Remote"}
                          </span>
                          <span>
                            {app.attempts > 0 && `Attempts: ${app.attempts}`}
                          </span>
                        </div>

                        {/* Specific fail/retry notice */}
                        {app.status === "RETRY_PENDING" && (
                          <div className="text-[9px] font-mono text-amber-500/80 bg-amber-950/10 border border-amber-900/20 p-1.5 rounded-lg leading-normal">
                            Wait retry: {app.last_error ? app.last_error.slice(0, 45) + "..." : "Unknown error"}
                          </div>
                        )}
                        {app.status === "LIMIT_EXCEEDED" && (
                          <div className="text-[9px] font-mono text-red-400/80 bg-red-950/10 border border-red-900/20 p-1.5 rounded-lg leading-normal">
                            Rate limit reached today
                          </div>
                        )}

                        {/* Hover Footer Controls */}
                        <div className="pt-2 border-t border-zinc-900/40 flex items-center justify-between gap-2 text-[9px] font-mono opacity-0 group-hover:opacity-100 transition-opacity duration-200">
                          <button
                            onClick={(e) => {
                              e.stopPropagation();
                              onSelectApplication(app);
                            }}
                            className="text-zinc-500 hover:text-zinc-300 transition-colors flex items-center gap-0.5 cursor-pointer font-bold"
                          >
                            Details
                            <ChevronRight className="w-3 h-3" />
                          </button>

                          {/* Quick Advance Button */}
                          {col.id === "SHORTLISTED" && (
                            <button
                              onClick={(e) => {
                                  e.stopPropagation();
                                  handleQuickMove(app.id, "APPLYING", app.job_posting?.company_name);
                              }}
                              className="px-2 py-0.5 bg-zinc-900 hover:bg-zinc-800 text-emerald-400 rounded border border-zinc-800 hover:border-zinc-700 transition-colors flex items-center gap-0.5 cursor-pointer font-bold"
                              title="Start applying"
                            >
                              Apply
                              <ArrowRight className="w-2.5 h-2.5" />
                            </button>
                          )}
                          {col.id === "APPLYING" && (
                            <button
                              onClick={(e) => {
                                  e.stopPropagation();
                                  handleQuickMove(app.id, "SUBMITTED", app.job_posting?.company_name);
                              }}
                              className="px-2 py-0.5 bg-zinc-900 hover:bg-zinc-800 text-teal-400 rounded border border-zinc-800 hover:border-zinc-700 transition-colors flex items-center gap-0.5 cursor-pointer font-bold"
                              title="Mark submitted"
                            >
                              Submit
                              <ArrowRight className="w-2.5 h-2.5" />
                            </button>
                          )}
                          {col.id === "SUBMITTED" && (
                            <button
                              onClick={(e) => {
                                  e.stopPropagation();
                                  handleQuickMove(app.id, "INTERVIEW", app.job_posting?.company_name);
                              }}
                              className="px-2 py-0.5 bg-zinc-900 hover:bg-zinc-800 text-purple-400 rounded border border-zinc-800 hover:border-zinc-700 transition-colors flex items-center gap-0.5 cursor-pointer font-bold"
                              title="Mark interviewing"
                            >
                              Interview
                              <ArrowRight className="w-2.5 h-2.5" />
                            </button>
                          )}
                        </div>
                      </div>
                    </div>
                  ))
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
