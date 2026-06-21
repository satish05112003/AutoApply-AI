"use client";

import React, { useState, useMemo, useRef, useEffect } from "react";
import { useStore } from "@/store/useStore";
import { Terminal, Trash2, Search, Filter, ShieldAlert, Cpu, UserCheck, ShieldCheck } from "lucide-react";

export default function ActivityLog() {
  const { logs, clearLogs } = useStore();
  const [searchQuery, setSearchQuery] = useState("");
  const [levelFilter, setLevelFilter] = useState("ALL");
  
  const scrollContainerRef = useRef<HTMLDivElement>(null);

  // Auto-scroll logs terminal internally
  useEffect(() => {
    if (scrollContainerRef.current) {
      scrollContainerRef.current.scrollTop = scrollContainerRef.current.scrollHeight;
    }
  }, [logs]);

  const filteredLogs = useMemo(() => {
    let result = [...logs];

    // 1. Search Query
    if (searchQuery.trim()) {
      const query = searchQuery.toLowerCase();
      result = result.filter(log => log.toLowerCase().includes(query));
    }

    // 2. Log Category/Level Filter
    if (levelFilter !== "ALL") {
      result = result.filter(log => {
        if (levelFilter === "SYSTEM") return log.includes("[System]");
        if (levelFilter === "AGENT") return log.includes("[MatchingAgent]") || log.includes("[ApplicationAgent]") || log.includes("[ResumeAgent]") || log.includes("[EmailMonitoringAgent]");
        if (levelFilter === "USER") return log.includes("[User]");
        if (levelFilter === "ERROR") return log.includes("[Error]") || log.includes("[Failure]") || log.includes("failed") || log.includes("Error");
        return true;
      });
    }

    return result;
  }, [logs, searchQuery, levelFilter]);

  const getLogStyle = (log: string) => {
    if (log.includes("[Error]") || log.includes("[Failure]") || log.toLowerCase().includes("failed")) {
      return {
        textClass: "text-red-400 font-bold",
        icon: <ShieldAlert className="w-3.5 h-3.5 text-red-500 shrink-0 mt-0.5" />
      };
    }
    if (log.includes("[MatchingAgent]")) {
      return {
        textClass: "text-amber-400",
        icon: <Cpu className="w-3.5 h-3.5 text-amber-500 shrink-0 mt-0.5" />
      };
    }
    if (log.includes("[ApplicationAgent]") || log.includes("[System] WebSocket connection established.")) {
      return {
        textClass: "text-emerald-400",
        icon: <ShieldCheck className="w-3.5 h-3.5 text-emerald-500 shrink-0 mt-0.5" />
      };
    }
    if (log.includes("[User]")) {
      return {
        textClass: "text-blue-400 font-medium",
        icon: <UserCheck className="w-3.5 h-3.5 text-blue-400 shrink-0 mt-0.5" />
      };
    }
    return {
      textClass: "text-emerald-400/90",
      icon: <span className="text-emerald-800 font-bold select-none shrink-0 mt-0.5">&gt;&gt;</span>
    };
  };

  return (
    <div className="premium-card overflow-hidden flex flex-col h-[320px] font-mono text-[11px]">
      
      {/* Header bar */}
      <div className="px-5 py-3 border-b border-zinc-900/60 flex flex-col sm:flex-row sm:items-center justify-between gap-3 shrink-0">
        <div className="flex items-center gap-2">
          <Terminal className="w-4 h-4 text-emerald-500" />
          <span className="tracking-wider text-zinc-350 uppercase font-bold text-[9.5px]">
            Agent Event Logger Stream
          </span>
          <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse" />
        </div>

        {/* Filter controls */}
        <div className="flex items-center gap-2 flex-wrap">
          {/* Search bar */}
          <div className="relative flex items-center">
            <Search className="absolute left-2.5 w-3 h-3 text-zinc-650" />
            <input
              type="text"
              placeholder="Search stream..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="premium-input bg-zinc-950/40 text-[9.5px] pl-7 pr-2.5 py-1 w-32 sm:w-40 placeholder-zinc-600 focus:outline-none"
            />
          </div>

          {/* Filter dropdown */}
          <div className="flex items-center gap-1">
            <Filter className="w-3 h-3 text-zinc-550" />
            <select
              value={levelFilter}
              onChange={(e) => setLevelFilter(e.target.value)}
              className="premium-input bg-zinc-950/40 text-[9.5px] px-2 py-1 focus:outline-none"
            >
              <option value="ALL">All Levels</option>
              <option value="SYSTEM">System Logs</option>
              <option value="AGENT">Agents (AI)</option>
              <option value="USER">User Actions</option>
              <option value="ERROR">Errors/Fails</option>
            </select>
          </div>

          {/* Clear logs */}
          <button
            onClick={clearLogs}
            className="p-1 rounded-lg bg-zinc-950/40 hover:bg-zinc-900 border border-zinc-900 hover:border-zinc-800 text-zinc-500 hover:text-red-400 transition-colors cursor-pointer"
            title="Clear Stream logs"
          >
            <Trash2 className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>

      {/* Log body */}
      <div 
        ref={scrollContainerRef}
        className="flex-1 overflow-y-auto p-4 bg-zinc-950/20 scan-line scrollbar-thin select-text space-y-1.5"
      >
        {filteredLogs.length === 0 ? (
          <div className="text-zinc-600 italic py-16 text-center select-none">
            // Event log stream is empty
          </div>
        ) : (
          filteredLogs.map((log, i) => {
            const style = getLogStyle(log);
            return (
              <div key={i} className={`flex items-start gap-2.5 leading-relaxed opacity-95 ${style.textClass}`}>
                {style.icon}
                <div className="flex-1 select-text selection:bg-emerald-900 selection:text-white break-words">
                  {log}
                </div>
              </div>
            );
          })
        )}
      </div>

    </div>
  );
}
