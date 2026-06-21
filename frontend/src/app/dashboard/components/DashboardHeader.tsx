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
    addLogLine,
    platformSessions,
    connectPlatform
  } = useStore();

  const [isSyncing, setIsSyncing] = useState(false);
  const [isCrawling, setIsCrawling] = useState(false);
  const [showDropdown, setShowDropdown] = useState(false);
  const [connectingPlatform, setConnectingPlatform] = useState<string | null>(null);

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
    <div className="flex flex-col md:flex-row md:items-center justify-between gap-6 p-6 premium-card mb-6">
      <div>
        <h2 className="text-lg font-semibold tracking-tight text-white flex items-center gap-2">
          Control Center
          <span className="relative flex h-2 w-2">
            <span className={`animate-ping absolute inline-flex h-full w-full rounded-full opacity-75 ${
              wsStatus === "connected" ? "bg-emerald-400" : wsStatus === "connecting" ? "bg-amber-400" : "bg-red-400"
            }`}></span>
            <span className={`relative inline-flex rounded-full h-2 w-2 ${
              wsStatus === "connected" ? "bg-emerald-500" : wsStatus === "connecting" ? "bg-amber-500" : "bg-red-500"
            }`}></span>
          </span>
        </h2>
        <p className="text-[11px] text-zinc-400 mt-0.5">
          Autonomous orchestration panel for crawler bots and browser subagents
        </p>
      </div>

      <div className="flex flex-wrap items-center gap-4 text-xs font-mono">
        {/* Platform Login Connections */}
        <div className="flex items-center gap-3">
          <span className="text-[10px] text-zinc-500 uppercase tracking-wider font-semibold">Sessions:</span>
          <div className="flex items-center gap-2">
            {["linkedin", "indeed", "naukri", "unstop"].map((plat) => {
              const isConnected = platformSessions?.[plat] || false;
              const isConnecting = connectingPlatform === plat;
              return (
                <button
                  key={plat}
                  disabled={isConnecting}
                  onClick={async () => {
                    setConnectingPlatform(plat);
                    await connectPlatform(plat);
                    setConnectingPlatform(null);
                  }}
                  className={`px-2 py-1 rounded transition-all text-[10px] cursor-pointer flex items-center gap-1.5 border border-zinc-800/50
                    ${isConnected 
                      ? "bg-emerald-950/20 text-emerald-450 border-emerald-900/20 hover:bg-emerald-900/10" 
                      : "bg-transparent text-zinc-400 hover:text-zinc-200 hover:border-zinc-700"
                    } ${isConnecting ? "animate-pulse" : ""}`}
                  title={isConnected ? `Active ${plat} session detected. Click to reconnect.` : `No active ${plat} session. Click to connect.`}
                >
                  <span className={`h-1.5 w-1.5 rounded-full ${isConnected ? "bg-emerald-400 animate-pulse" : "bg-zinc-700"}`} />
                  <span className="capitalize">{plat}</span>
                  {isConnecting && <RefreshCw className="w-2.5 h-2.5 animate-spin ml-0.5 text-zinc-400" />}
                </button>
              );
            })}
          </div>
        </div>

        {/* Separator */}
        <div className="hidden md:block h-4 w-[1px] bg-zinc-800/80" />

        {/* System Health Badges */}
        <div className="flex items-center gap-2 text-zinc-400">
          <span className="text-[10px] text-zinc-500 uppercase tracking-wider font-semibold">Health:</span>
          <div className="flex items-center gap-2 text-[10px]">
            <span className="flex items-center gap-1">
              <span className={`h-1.5 w-1.5 rounded-full ${pgStatus ? "bg-emerald-500" : "bg-red-500"}`} />
              <span className="text-zinc-400">DB</span>
            </span>
            <span className="flex items-center gap-1">
              <span className={`h-1.5 w-1.5 rounded-full ${redisStatus ? "bg-emerald-500" : "bg-red-500"}`} />
              <span className="text-zinc-400">Redis</span>
            </span>
            <span className="flex items-center gap-1">
              <span className={`h-1.5 w-1.5 rounded-full ${celeryStatus ? "bg-emerald-500" : "bg-amber-500"}`} />
              <span className="text-zinc-400">Celery</span>
            </span>
          </div>
        </div>

        {/* Separator */}
        <div className="hidden md:block h-4 w-[1px] bg-zinc-800/80" />

        {/* Notifications Bell */}
        <NotificationCenter />

        {/* Quick Actions Dropdown */}
        <div className="relative">
          <button 
            onClick={() => setShowDropdown(!showDropdown)}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-zinc-900 border border-zinc-800 text-zinc-200 hover:text-white hover:bg-zinc-850 transition-all text-xs font-semibold cursor-pointer"
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
              <div className="absolute right-0 mt-2 w-48 bg-[#0a0a0c] border border-zinc-800/80 rounded-lg shadow-2xl p-1 z-20 animate-fade-in text-[11px] font-sans">
                <button
                  onClick={() => {
                    handleSyncSheets();
                    setShowDropdown(false);
                  }}
                  disabled={isSyncing}
                  className="w-full flex items-center gap-2 px-3 py-2 rounded-md text-zinc-350 hover:bg-zinc-900 hover:text-white transition-all text-left"
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
                  className="w-full flex items-center gap-2 px-3 py-2 rounded-md text-zinc-350 hover:bg-zinc-900 hover:text-white transition-all text-left"
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
