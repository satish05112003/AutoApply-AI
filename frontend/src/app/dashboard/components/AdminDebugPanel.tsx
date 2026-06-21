"use client";

import React, { useState } from "react";
import { useStore } from "@/store/useStore";
import { 
  Terminal, 
  Trash2, 
  RefreshCw, 
  Database, 
  Cpu, 
  Activity, 
  AlertOctagon,
  Wrench,
  CheckCircle,
  HelpCircle
} from "lucide-react";

export default function AdminDebugPanel() {
  const { 
    systemHealth, 
    purgeQueues, 
    syncSheets, 
    addLogLine,
    fetchSystemHealth 
  } = useStore();

  const [isPurging, setIsPurging] = useState(false);
  const [isSyncing, setIsSyncing] = useState(false);
  const [isRefreshingHealth, setIsRefreshingHealth] = useState(false);

  const handlePurge = async () => {
    if (!window.confirm("Are you sure you want to purge all Celery background task backlogs from Redis? This action is safe for cache metadata but will clear enqueued tasks.")) {
      return;
    }
    setIsPurging(true);
    addLogLine("[Admin] Requesting safe purge of broker task queue keys in Redis...");
    const ok = await purgeQueues();
    setIsPurging(false);
    if (ok) {
      addLogLine("[Admin] Purge completed. Redis queue list keys deleted.");
    }
  };

  const handleForceSync = async () => {
    setIsSyncing(true);
    addLogLine("[Admin] Requesting immediate manual Google Sheets sync cycle pass...");
    await syncSheets();
    setIsSyncing(false);
  };

  const handleRefreshHealth = async () => {
    setIsRefreshingHealth(true);
    await fetchSystemHealth();
    setIsRefreshingHealth(false);
  };

  // Safe checks for data structure
  const queues = systemHealth?.queues || {
    discovery: 0,
    orchestrate: 0,
    applications: 0,
    sheets: 0,
    email: 0
  };

  const workers = systemHealth?.workers || {
    discovery: "OFFLINE",
    orchestrate: "OFFLINE",
    applications: "OFFLINE",
    sheets: "OFFLINE",
    email: "OFFLINE"
  };

  // Find max queue size to scale progress bars
  const maxQueueVal = Math.max(10, ...Object.values(queues));

  return (
    <div className="premium-card p-5 space-y-5">
      
      {/* Header */}
      <div className="flex items-center justify-between border-b border-zinc-900 pb-3">
        <div className="flex items-center gap-2">
          <Wrench className="w-4 h-4 text-emerald-500" />
          <h3 className="font-bold text-xs text-zinc-300 uppercase tracking-widest font-mono">
            Diagnostic & Control Panel
          </h3>
        </div>

        <button
          onClick={handleRefreshHealth}
          disabled={isRefreshingHealth}
          className="p-1.5 rounded-lg bg-zinc-950 hover:bg-zinc-900 border border-zinc-850 hover:border-zinc-800 text-zinc-500 hover:text-zinc-300 transition-colors cursor-pointer"
          title="Refresh diagnostic statistics"
        >
          <RefreshCw className={`w-3.5 h-3.5 ${isRefreshingHealth ? "animate-spin text-emerald-500" : ""}`} />
        </button>
      </div>

      {/* Queues and Workers status grids */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6 font-mono text-[10px]">
        
        {/* Queue depths (progress bars) */}
        <div className="space-y-3.5">
          <h4 className="font-bold text-[9px] uppercase tracking-wider text-zinc-550 flex items-center gap-1.5">
            <Database className="w-3.5 h-3.5 text-zinc-500" />
            Redis Broker Queue Depths
          </h4>
          
          <div className="space-y-2.5">
            {Object.entries(queues).map(([name, size]) => {
              const percentage = Math.round((size / maxQueueVal) * 100);
              return (
                <div key={name} className="space-y-1.5">
                  <div className="flex justify-between items-center text-[9px]">
                    <span className="text-zinc-400 capitalize">{name} queue</span>
                    <span className={`font-bold ${size > 50 ? "text-amber-500 animate-pulse" : "text-zinc-300"}`}>
                      {size} tasks
                    </span>
                  </div>
                  {/* Bar */}
                  <div className="w-full bg-zinc-950 rounded-full h-1.5 border border-zinc-900 overflow-hidden">
                    <div 
                      className={`h-full rounded-full transition-all duration-500 ${
                        size > 50 ? "bg-amber-500" : "bg-emerald-500"
                      }`}
                      style={{ width: `${percentage}%` }}
                    />
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        {/* Celery worker daemon statuses */}
        <div className="space-y-3.5">
          <h4 className="font-bold text-[9px] uppercase tracking-wider text-zinc-550 flex items-center gap-1.5">
            <Cpu className="w-3.5 h-3.5 text-zinc-500" />
            Active Daemon Workers Grid
          </h4>

          <div className="grid grid-cols-1 gap-2">
            {Object.entries(workers).map(([name, state]) => {
              const isOnline = state === "ONLINE";
              return (
                <div 
                  key={name} 
                  className="px-3.5 py-2.5 bg-[#060609]/60 border border-zinc-900 rounded-xl flex items-center justify-between transition-colors hover:border-zinc-800"
                >
                  <span className="text-zinc-300 capitalize font-medium">{name} daemon thread</span>
                  <span className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded-full text-[8.5px] font-bold border font-mono tracking-wider
                    ${isOnline 
                      ? "bg-emerald-950/40 text-emerald-400 border-emerald-800/30" 
                      : "bg-red-950/20 text-red-400 border-red-800/20"
                    }`}
                  >
                    {state}
                  </span>
                </div>
              );
            })}
          </div>
        </div>

      </div>

      {/* Action button controls */}
      <div className="pt-4 border-t border-zinc-900/60 flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-2">
          <button
            onClick={handlePurge}
            disabled={isPurging}
            className="flex items-center gap-1.5 px-3 py-1.5 bg-red-950/10 border border-red-900/30 hover:border-red-900/60 text-red-400 font-bold rounded-lg font-mono text-[9px] transition-all cursor-pointer"
            title="Purge all background queues"
          >
            <Trash2 className="w-3.5 h-3.5" />
            {isPurging ? "Purging..." : "Purge Broker Queues"}
          </button>
          
          <button
            onClick={handleForceSync}
            disabled={isSyncing}
            className="flex items-center gap-1.5 px-3 py-1.5 bg-zinc-900 hover:bg-zinc-800 border border-zinc-850 hover:border-zinc-800 text-zinc-300 hover:text-zinc-100 rounded-lg font-mono text-[9px] transition-all cursor-pointer"
            title="Trigger Sheets synchronization cycle immediately"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${isSyncing ? "animate-spin text-emerald-400" : ""}`} />
            Sync Sheets Now
          </button>
        </div>

        <div className="flex items-center gap-1.5 text-[8.5px] font-mono text-zinc-550">
          <AlertOctagon className="w-3.5 h-3.5 text-zinc-650" />
          <span>Queues with &gt; 50 backpressure tasks trigger automatic self-pausing.</span>
        </div>
      </div>

    </div>
  );
}
