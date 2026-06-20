"use client";

import React, { useState } from "react";
import { useStore } from "@/store/useStore";
import { Activity, RefreshCw, Zap, Server, ChevronDown, Check, ShieldAlert } from "lucide-react";
import NotificationCenter from "./NotificationCenter";

interface DashboardHeaderProps {
  wsStatus: "connected" | "connecting" | "disconnected";
}

export default function DashboardHeader({ wsStatus }: DashboardHeaderProps) {
  const { 
    user,
    systemHealth,
    sheetsStatus,
    syncSheets,
    refreshJobs,
    addLogLine
  } = useStore();

  const [isSyncing, setIsSyncing] = useState(false);
  const [isCrawling, setIsCrawling] = useState(false);
  const [showDropdown, setShowDropdown] = useState(false);

  const handleSyncSheets = async () => {
    setIsSyncing(true);
    addLogLine("[User] Sheets sync manually triggered from header...");
    await syncSheets();
    setIsSyncing(false);
  };

  const handleRefreshJobs = async () => {
    setIsCrawling(true);
    addLogLine("[User] Crawler manual scan triggered from header...");
    await refreshJobs();
    setIsCrawling(false);
  };

  // Safe checks for health
  const pgStatus = systemHealth?.services?.postgres === "healthy";
  const redisStatus = systemHealth?.services?.redis === "healthy";
  const celeryStatus = systemHealth?.services?.celery === "healthy";
  const qdrantStatus = systemHealth?.services?.qdrant === "healthy" || systemHealth?.services?.qdrant === "disabled";

  return (
    <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 p-5 bg-[#0b0b0f]/80 ring-1 ring-zinc-800/50 backdrop-blur-md rounded-2xl mb-6 shadow-xl">
      <div>
        <h2 className="text-xl font-bold tracking-tight text-zinc-100 font-mono flex items-center gap-2">
          Control Center Dashboard
          <span className="relative flex h-2.5 w-2.5">
            <span className={`animate-ping absolute inline-flex h-full w-full rounded-full opacity-75 ${
              wsStatus === "connected" ? "bg-emerald-400" : wsStatus === "connecting" ? "bg-amber-400" : "bg-red-400"
            }`}></span>
            <span className={`relative inline-flex rounded-full h-2.5 w-2.5 ${
              wsStatus === "connected" ? "bg-emerald-500" : wsStatus === "connecting" ? "bg-amber-500" : "bg-red-500"
            }`}></span>
          </span>
        </h2>
        <p className="text-[10px] text-zinc-400 mt-1 uppercase tracking-wider font-mono">
          Autonomous orchestration panel for crawler bots and browser subagents
        </p>
      </div>

      <div className="flex flex-wrap items-center gap-3">
        {/* System Health Badges */}
        <div className="flex items-center gap-2 bg-[#060609]/60 px-3 py-1.5 rounded-xl border border-zinc-850">
          <Server className="w-3.5 h-3.5 text-zinc-500" />
          <div className="flex items-center gap-1.5 text-[9px] font-mono font-bold">
            <span className="text-zinc-500">DB:</span>
            <span className={pgStatus ? "text-emerald-400" : "text-red-400"}>{pgStatus ? "ON" : "OFF"}</span>
            <span className="text-zinc-700">|</span>
            <span className="text-zinc-500">REDIS:</span>
            <span className={redisStatus ? "text-emerald-400" : "text-red-400"}>{redisStatus ? "ON" : "OFF"}</span>
            <span className="text-zinc-700">|</span>
            <span className="text-zinc-500">CELERY:</span>
            <span className={celeryStatus ? "text-emerald-400" : "text-amber-400"}>
              {celeryStatus ? `ON` : "OFF"}
            </span>
          </div>
        </div>

        {/* Notifications Bell */}
        <NotificationCenter />

        {/* Quick Actions Dropdown */}
        <div className="relative">
          <button 
            onClick={() => setShowDropdown(!showDropdown)}
            className="flex items-center gap-1.5 px-3.5 py-1.5 rounded-xl bg-zinc-900 border border-zinc-800 text-zinc-300 hover:text-zinc-100 hover:bg-zinc-800 transition-all font-mono font-bold text-[10px]"
          >
            Actions
            <ChevronDown className="w-3.5 h-3.5 text-zinc-400" />
          </button>
          
          {showDropdown && (
            <>
              <div 
                className="fixed inset-0 z-10" 
                onClick={() => setShowDropdown(false)}
              />
              <div className="absolute right-0 mt-2 w-48 bg-[#0d0d11] border border-zinc-800 rounded-xl shadow-2xl p-1 z-20 animate-fade-in font-mono text-[10px]">
                <button
                  onClick={() => {
                    handleSyncSheets();
                    setShowDropdown(false);
                  }}
                  disabled={isSyncing}
                  className="w-full flex items-center gap-2 px-3 py-2 rounded-lg text-zinc-300 hover:bg-zinc-900 hover:text-white transition-all text-left"
                >
                  <RefreshCw className={`w-3.5 h-3.5 ${isSyncing ? "animate-spin text-emerald-400" : "text-zinc-500"}`} />
                  Sync Google Sheets
                </button>
                <button
                  onClick={() => {
                    handleRefreshJobs();
                    setShowDropdown(false);
                  }}
                  disabled={isCrawling}
                  className="w-full flex items-center gap-2 px-3 py-2 rounded-lg text-zinc-300 hover:bg-zinc-900 hover:text-white transition-all text-left"
                >
                  <Zap className={`w-3.5 h-3.5 ${isCrawling ? "animate-pulse text-emerald-400" : "text-zinc-500"}`} />
                  Crawl Discovered Jobs
                </button>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
