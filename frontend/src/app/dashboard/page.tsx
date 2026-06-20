"use client";

import React, { useEffect, useRef, useState } from "react";
import { useStore } from "@/store/useStore";
import { API_BASE } from "@/config";
import { 
  Activity, 
  CheckCircle, 
  Clock, 
  ExternalLink, 
  FileSpreadsheet, 
  Play, 
  Pause,
  RefreshCw,
  Terminal as TermIcon, 
  XCircle,
  Zap,
  Settings,
  ShieldCheck,
  TrendingUp
} from "lucide-react";

export default function DashboardPage() {
  const { 
    token,
    applications, 
    stats, 
    logs, 
    sheetsStatus,
    googleIntegration,
    agentStatus,
    systemHealth,
    fetchApplications, 
    fetchStats, 
    initializeSheets, 
    approveApplication, 
    rejectApplication, 
    updateApplicationAnswers,
    fetchAgentStatus,
    fetchSystemHealth,
    fetchSystemEvents,
    fetchSheetsStatus,
    startDiscovery,
    stopDiscovery,
    startAutoApply,
    stopAutoApply,
    startEmailMonitoring,
    stopEmailMonitoring,
    syncSheets,
    connectGoogleSheets,
    disconnectGoogleSheets,
    manualSyncGoogleSheets,
    refreshJobs,
    addLogLine 
  } = useStore();

  const terminalContainerRef = useRef<HTMLDivElement>(null);
  const [isSyncing, setIsSyncing] = useState(false);
  const [isCrawling, setIsCrawling] = useState(false);
  const [isConnectingGoogle, setIsConnectingGoogle] = useState(false);
  const [isDisconnecting, setIsDisconnecting] = useState(false);
  const [googleCallbackMsg, setGoogleCallbackMsg] = useState<string | null>(null);

  // Review Queue and Details States
  const [activeReviewId, setActiveReviewId] = useState<string | null>(null);
  const [reviewAnswers, setReviewAnswers] = useState<Record<string, string>>({});
  const [reviewCoverLetter, setReviewCoverLetter] = useState<string>("");
  const [isSubmittingAnswers, setIsSubmittingAnswers] = useState(false);

  const [selectedAppForDetails, setSelectedAppForDetails] = useState<any | null>(null);
  const [evidence, setEvidence] = useState<any[]>([]);
  const [events, setEvents] = useState<any[]>([]);
  const [isLoadingDetails, setIsLoadingDetails] = useState(false);

  useEffect(() => {
    if (selectedAppForDetails && token) {
      setIsLoadingDetails(true);
      
      const fetchEv = fetch(`${API_BASE}/applications/${selectedAppForDetails.id}/evidence`, {
        headers: { "Authorization": `Bearer ${token}` }
      })
      .then(res => res.json())
      .catch(err => {
        console.error("Failed fetching evidence", err);
        return [];
      });

      const fetchEvs = fetch(`${API_BASE}/applications/${selectedAppForDetails.id}/events`, {
        headers: { "Authorization": `Bearer ${token}` }
      })
      .then(res => res.json())
      .catch(err => {
        console.error("Failed fetching events", err);
        return [];
      });

      Promise.all([fetchEv, fetchEvs]).then(([evData, evsData]) => {
        setEvidence(evData || []);
        setEvents(evsData || []);
        setIsLoadingDetails(false);
      });
    } else {
      setEvidence([]);
      setEvents([]);
    }
  }, [selectedAppForDetails, token]);

  const cleanLabel = (key: string) => {
    const match = key.match(/name=['"]([^'"]+)['"]/);
    if (match) {
      return match[1].replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase());
    }
    return key.replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase());
  };

  // Initial Data Load & Periodic Poll (every 10 seconds for real-time status)
  useEffect(() => {
    fetchApplications();
    fetchStats();
    fetchAgentStatus();
    fetchSystemHealth();
    fetchSystemEvents();
    fetchSheetsStatus();

    const interval = setInterval(() => {
      fetchAgentStatus();
      fetchApplications();
      fetchSystemHealth();
      fetchStats();
      fetchSystemEvents();
      // Poll integration status so provisioning spinner resolves automatically
      fetchSheetsStatus();
    }, 5000);

    return () => clearInterval(interval);
  }, []);

  // Handle Google OAuth callback result from URL query params
  useEffect(() => {
    if (typeof window === "undefined") return;
    const params = new URLSearchParams(window.location.search);
    const gsParam = params.get("google_sheets");
    if (gsParam === "connected") {
      const email = params.get("email") || "";
      setGoogleCallbackMsg(`Google Sheets connected${email ? ` (${email})` : ""}. Setting up your spreadsheet...`);
      addLogLine(`[System] Google Sheets OAuth connected${email ? " for " + email : ""}. Spreadsheet provisioning in progress...`);
      fetchSheetsStatus();
      // Clean URL
      const cleanUrl = window.location.pathname;
      window.history.replaceState({}, "", cleanUrl);
    } else if (gsParam === "denied") {
      setGoogleCallbackMsg("Google Sheets connection was cancelled.");
      const cleanUrl = window.location.pathname;
      window.history.replaceState({}, "", cleanUrl);
    } else if (gsParam === "error") {
      const reason = params.get("reason") || "unknown";
      setGoogleCallbackMsg(`Google Sheets connection failed: ${reason}`);
      const cleanUrl = window.location.pathname;
      window.history.replaceState({}, "", cleanUrl);
    }
  }, []);

  // Auto-scroll logs terminal
  useEffect(() => {
    if (terminalContainerRef.current) {
      terminalContainerRef.current.scrollTop = terminalContainerRef.current.scrollHeight;
    }
  }, [logs]);

  const handleLinkSheets = async () => {
    addLogLine("[System] Initializing Google spreadsheet tracker...");
    const success = await initializeSheets();
    if (success) {
      addLogLine("[System] Google spreadsheet linked successfully.");
    } else {
      addLogLine("[System] Failed linking Google spreadsheet.");
    }
  };

  const handleConnectGoogle = async () => {
    setIsConnectingGoogle(true);
    addLogLine("[System] Initiating Google OAuth connection...");
    await connectGoogleSheets();
    // Note: if redirect works, this line never runs
    setIsConnectingGoogle(false);
  };

  const handleDisconnectGoogle = async () => {
    setIsDisconnecting(true);
    const ok = await disconnectGoogleSheets();
    setIsDisconnecting(false);
    if (!ok) addLogLine("[System] Failed to disconnect Google Sheets.");
  };

  const handleManualSyncSheets = async () => {
    setIsSyncing(true);
    await manualSyncGoogleSheets();
    setIsSyncing(false);
  };

  const handleSyncSheets = async () => {
    setIsSyncing(true);
    addLogLine("[System] Starting manual Google Sheets synchronization pass...");
    await syncSheets();
    setIsSyncing(false);
  };

  const handleRefreshJobs = async () => {
    setIsCrawling(true);
    addLogLine("[System] Enqueuing manual job discovery crawlers...");
    const success = await refreshJobs();
    setIsCrawling(false);
  };

  const handleToggleDiscovery = async () => {
    if (agentStatus?.discovery_running) {
      addLogLine("[System] Stopping job discovery daemon...");
      await stopDiscovery();
    } else {
      addLogLine("[System] Starting job discovery daemon...");
      await startDiscovery();
    }
  };

  const handleToggleAutoApply = async () => {
    if (agentStatus?.auto_apply_running) {
      addLogLine("[System] Disabling Auto-Apply. Switched back to Human Approval Mode.");
      await stopAutoApply();
    } else {
      addLogLine("[System] Enabling Full-Auto Apply mode. AutoApply AI will submit matches without approval.");
      await startAutoApply();
    }
  };

  const handleToggleEmailMonitoring = async () => {
    if (agentStatus?.email_monitoring_running) {
      addLogLine("[System] Disabling recruiter email monitoring...");
      await stopEmailMonitoring();
    } else {
      addLogLine("[System] Enabling recruiter email monitoring...");
      const success = await startEmailMonitoring();
      if (!success) {
        addLogLine("[System] Warning: Please configure your Gmail App Password in Preferences first.");
      }
    }
  };

  const handlePauseSystem = async () => {
    addLogLine("[System] Pausing all background agent pipelines...");
    await stopDiscovery();
  };

  const handleResumeSystem = async () => {
    addLogLine("[System] Resuming background agent pipelines...");
    await startDiscovery();
  };

  return (
    <div className="space-y-8 animate-fade-in text-xs">
      
      {/* Overview Intro */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <h2 className="text-xl font-bold tracking-tight text-zinc-100 font-mono">Control Center Dashboard</h2>
          <p className="text-[10px] text-zinc-400 mt-1">Autonomous orchestration panel for discovery crawlers, AI matcher, and browser subagents.</p>
        </div>
        
        {/* Quick Sync/Control Row */}
        <div className="flex items-center gap-2">
          <button 
            onClick={handleSyncSheets}
            disabled={isSyncing}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-zinc-900 border border-zinc-800 text-zinc-300 hover:text-zinc-100 hover:bg-zinc-800 transition-all font-mono font-bold text-[10px]"
            title="Force synchronization with Google Sheets"
          >
            <RefreshCw className={`w-3 h-3 ${isSyncing ? "animate-spin text-emerald-400" : ""}`} />
            Sync Sheets
          </button>
          <button 
            onClick={handleRefreshJobs}
            disabled={isCrawling}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-emerald-950/20 border border-emerald-800 text-emerald-400 hover:text-emerald-300 hover:bg-emerald-900/20 transition-all font-mono font-bold text-[10px]"
            title="Scan for new jobs immediately"
          >
            <Zap className={`w-3 h-3 ${isCrawling ? "animate-pulse" : ""}`} />
            Refresh Jobs
          </button>
        </div>
      </div>

      {agentStatus && agentStatus.redis_connected === false && (
        <div className="p-3 bg-red-950/20 border border-red-800 rounded-xl text-red-400 font-mono text-[10px] flex items-center justify-between">
          <div className="flex items-center gap-2">
            <XCircle className="w-4 h-4 text-red-500 shrink-0 animate-pulse" />
            <span><strong>CRITICAL WARNING:</strong> Redis connection is down. Background tasks (Celery worker/beat) are offline. Job discovery, matching, and auto-applying will not run automatically.</span>
          </div>
        </div>
      )}

      {/* Google OAuth callback notification */}
      {googleCallbackMsg && (
        <div className={`p-3 rounded-xl font-mono text-[10px] flex items-center justify-between border ${
          googleCallbackMsg.includes("connected")
            ? "bg-emerald-950/20 border-emerald-800 text-emerald-400"
            : "bg-amber-950/20 border-amber-800 text-amber-400"
        }`}>
          <div className="flex items-center gap-2">
            <FileSpreadsheet className="w-4 h-4 shrink-0" />
            <span>{googleCallbackMsg}</span>
          </div>
          <button
            onClick={() => setGoogleCallbackMsg(null)}
            className="shrink-0 text-zinc-500 hover:text-zinc-300 transition-colors ml-4"
          >
            <XCircle className="w-3 h-3" />
          </button>
        </div>
      )}


      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        
        {/* 1. Orchestrator Widget Panel */}
        <div className="lg:col-span-2 p-1.5 rounded-[1.25rem] bg-zinc-900/30 ring-1 ring-zinc-800/50 backdrop-blur-md">
          <div className="bg-[#0b0b0f] rounded-[calc(1.25rem-0.375rem)] p-5 shadow-[inset_0_1px_1px_rgba(255,255,255,0.03)] space-y-6">
            <h3 className="font-bold text-xs text-zinc-300 uppercase tracking-widest border-b border-zinc-900 pb-3 flex items-center gap-2 font-mono">
              <Settings className="w-4 h-4 text-emerald-500" />
              Autonomous Agent Orchestrator
            </h3>

            {/* Grid of Daemon Statuses */}
            <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-4 gap-4">
              
              {/* Discovery Daemon Status */}
              <div className="p-3 bg-zinc-950/40 rounded-xl border border-zinc-900/80 flex flex-col justify-between gap-3">
                <span className="text-[10px] text-zinc-500 font-semibold uppercase tracking-wider font-mono">Job Discovery</span>
                <div className="flex items-center justify-between">
                  <span className="font-bold text-zinc-200">Crawlers</span>
                  <span className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded-full text-[9px] font-mono font-bold border ${
                    agentStatus?.discovery_running 
                      ? "bg-emerald-950/40 text-emerald-400 border-emerald-800/40 shadow-[0_0_8px_rgba(16,185,129,0.15)] animate-pulse" 
                      : "bg-zinc-900 text-zinc-500 border-zinc-800"
                  }`}>
                    {agentStatus?.discovery_running ? "RUNNING" : "STOPPED"}
                  </span>
                </div>
              </div>

              {/* Matching Engine Status */}
              <div className="p-3 bg-zinc-950/40 rounded-xl border border-zinc-900/80 flex flex-col justify-between gap-3">
                <span className="text-[10px] text-zinc-500 font-semibold uppercase tracking-wider font-mono">AI Matching</span>
                <div className="flex items-center justify-between">
                  <span className="font-bold text-zinc-200">Weights</span>
                  <span className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded-full text-[9px] font-mono font-bold border ${
                    agentStatus?.agent_enabled 
                      ? "bg-emerald-950/40 text-emerald-400 border-emerald-800/40" 
                      : "bg-zinc-900 text-zinc-500 border-zinc-800"
                  }`}>
                    {agentStatus?.agent_enabled ? "ACTIVE" : "PAUSED"}
                  </span>
                </div>
              </div>

              {/* Auto Apply Status */}
              <div className="p-3 bg-zinc-950/40 rounded-xl border border-zinc-900/80 flex flex-col justify-between gap-3">
                <span className="text-[10px] text-zinc-500 font-semibold uppercase tracking-wider font-mono">Auto Apply</span>
                <div className="flex items-center justify-between">
                  <span className="font-bold text-zinc-200">Mode</span>
                  <span className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded-full text-[9px] font-mono font-bold border ${
                    agentStatus?.auto_apply_running 
                      ? "bg-blue-950/40 text-blue-400 border-blue-800/40 shadow-[0_0_8px_rgba(59,130,246,0.15)]" 
                      : "bg-amber-950/40 text-amber-400 border-amber-800/40"
                  }`}>
                    {agentStatus?.auto_apply_running ? "FULL_AUTO" : "SEMI_AUTO"}
                  </span>
                </div>
              </div>

              {/* Email Monitor Status */}
              <div className="p-3 bg-zinc-950/40 rounded-xl border border-zinc-900/80 flex flex-col justify-between gap-3">
                <span className="text-[10px] text-zinc-500 font-semibold uppercase tracking-wider font-mono">Email Monitor</span>
                <div className="flex items-center justify-between">
                  <span className="font-bold text-zinc-200">Gmail IMAP</span>
                  <span className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded-full text-[9px] font-mono font-bold border ${
                    agentStatus?.email_monitoring_running 
                      ? "bg-emerald-950/40 text-emerald-400 border-emerald-800/40 shadow-[0_0_8px_rgba(16,185,129,0.15)] animate-pulse" 
                      : "bg-zinc-900 text-zinc-500 border-zinc-800"
                  }`}>
                    {agentStatus?.email_monitoring_running ? "TRACKING" : "OFFLINE"}
                  </span>
                </div>
              </div>

            </div>

            {/* Daemon Control Action Buttons */}
            <div className="border-t border-zinc-900 pt-4 flex flex-wrap items-center justify-between gap-4">
              <div className="flex flex-wrap items-center gap-2">
                {(!agentStatus?.discovery_running && (systemHealth?.celery_metrics?.queue_size || 0) > 2000) ? (
                  <div className="relative group inline-block">
                    <button 
                      disabled
                      className="px-3 py-2 rounded-lg font-bold border font-mono text-[10px] bg-zinc-900 border-zinc-800 text-zinc-500 cursor-not-allowed"
                    >
                      Start Discovery (Blocked)
                    </button>
                    <div className="absolute bottom-full left-1/2 transform -translate-x-1/2 mb-2 hidden group-hover:block w-48 p-2 bg-zinc-950 border border-zinc-900 text-[9px] text-amber-400 font-mono rounded-lg shadow-xl text-center z-10 leading-normal">
                      Discovery blocked due to queue backpressure. Pending tasks exceed 2000.
                    </div>
                  </div>
                ) : (
                  <button 
                    onClick={handleToggleDiscovery}
                    className={`px-3 py-2 rounded-lg font-bold transition-all border font-mono text-[10px] ${
                      agentStatus?.discovery_running 
                        ? "bg-zinc-900 border-zinc-800 text-red-400 hover:bg-zinc-850 hover:border-red-900/50" 
                        : "bg-emerald-600 border-emerald-500 text-white hover:bg-emerald-500"
                    }`}
                  >
                    {agentStatus?.discovery_running ? "Stop Discovery" : "Start Discovery"}
                  </button>
                )}
                <button 
                  onClick={handleToggleAutoApply}
                  className={`px-3 py-2 rounded-lg font-bold transition-all border font-mono text-[10px] ${
                    agentStatus?.auto_apply_running 
                      ? "bg-amber-950/20 border-amber-800 text-amber-400 hover:bg-amber-900/20" 
                      : "bg-blue-600 border-blue-500 text-white hover:bg-blue-500"
                  }`}
                >
                  {agentStatus?.auto_apply_running ? "Switch to Semi-Auto" : "Start Auto Apply"}
                </button>
                <button 
                  onClick={handleToggleEmailMonitoring}
                  className={`px-3 py-2 rounded-lg font-bold transition-all border font-mono text-[10px] ${
                    agentStatus?.email_monitoring_running 
                      ? "bg-zinc-900 border-zinc-800 text-zinc-400 hover:bg-zinc-850" 
                      : "bg-zinc-900 border-zinc-800 text-emerald-400 hover:bg-zinc-800"
                  }`}
                >
                  {agentStatus?.email_monitoring_running ? "Stop Email Tracker" : "Start Email Tracker"}
                </button>
              </div>

              {/* Pause / Resume General System */}
              <div className="flex items-center gap-2">
                {agentStatus?.agent_enabled ? (
                  <button 
                    onClick={handlePauseSystem}
                    className="flex items-center gap-1 px-3 py-2 rounded-lg bg-zinc-900 hover:bg-zinc-850 border border-zinc-800 text-zinc-400 font-mono text-[10px]"
                  >
                    <Pause className="w-3 h-3" />
                    Pause System
                  </button>
                ) : (
                  <button 
                    onClick={handleResumeSystem}
                    className="flex items-center gap-1 px-3 py-2 rounded-lg bg-emerald-950/20 border border-emerald-800 text-emerald-400 font-mono text-[10px] font-bold"
                  >
                    <Play className="w-3 h-3 fill-current" />
                    Resume System
                  </button>
                )}
              </div>
            </div>

          </div>
        </div>

        {/* Right side Stack: Sheets and System Health */}
        <div className="flex flex-col gap-6">
          {/* Sheets Tracker Card — Google OAuth Multi-Tenant */}
          <div className="p-1.5 rounded-[1.25rem] bg-zinc-900/30 ring-1 ring-zinc-800/50 backdrop-blur-md">
            <div className="bg-[#0b0b0f] rounded-[calc(1.25rem-0.375rem)] p-5 shadow-[inset_0_1px_1px_rgba(255,255,255,0.03)] flex flex-col justify-between h-full gap-4">
              <div className="flex items-start gap-3.5">
                <div className={`p-2.5 rounded-lg border shrink-0 ${googleIntegration.connected && googleIntegration.provisioned ? "bg-emerald-950/20 border-emerald-800/40 text-emerald-400" : "bg-zinc-900 border-zinc-800 text-zinc-500"}`}>
                  <FileSpreadsheet className="w-5 h-5" />
                </div>
                <div className="space-y-1 flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <h3 className="font-semibold text-xs text-zinc-200">Google Sheets Tracker</h3>
                    {googleIntegration.connected && googleIntegration.provisioned && (
                      <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded-full text-[9px] font-mono font-bold bg-emerald-950/40 text-emerald-400 border border-emerald-800/40">
                        LIVE
                      </span>
                    )}
                    {googleIntegration.connected && !googleIntegration.provisioned && (
                      <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded-full text-[9px] font-mono font-bold bg-amber-950/40 text-amber-400 border border-amber-800/40 animate-pulse">
                        SETUP
                      </span>
                    )}
                  </div>
                  {googleIntegration.connected ? (
                    <div className="space-y-0.5">
                      <p className="text-[10px] text-zinc-400 truncate">
                        {googleIntegration.google_email || "Google account connected"}
                      </p>
                      {googleIntegration.last_sync_at && (
                        <div className="text-[9px] font-mono text-zinc-500">
                          Last sync: {new Date(googleIntegration.last_sync_at).toLocaleTimeString()}
                        </div>
                      )}
                    </div>
                  ) : (
                    <p className="text-[10px] text-zinc-400 leading-relaxed">
                      {googleIntegration.configured
                        ? "Connect your Google account to sync applications to your personal spreadsheet."
                        : "Google OAuth not configured. Add GOOGLE_OAUTH_CLIENT_ID to .env"}
                    </p>
                  )}
                </div>
              </div>

              {/* Action buttons */}
              <div className="flex flex-col gap-2">
                {!googleIntegration.connected ? (
                  /* Disconnected — show Connect button */
                  <button
                    onClick={handleConnectGoogle}
                    disabled={!googleIntegration.configured || isConnectingGoogle}
                    className="w-full py-2 px-3 bg-zinc-900 hover:bg-zinc-800 border border-zinc-700 disabled:border-zinc-800 disabled:text-zinc-600 disabled:cursor-not-allowed text-zinc-200 font-semibold rounded-lg text-xs transition-all duration-300 font-mono flex items-center justify-center gap-2"
                  >
                    <FileSpreadsheet className="w-3.5 h-3.5" />
                    {isConnectingGoogle ? "Redirecting to Google..." : "Connect Google Sheets"}
                  </button>
                ) : !googleIntegration.provisioned ? (
                  /* Connected but spreadsheet still being set up */
                  <div className="w-full py-2 px-3 bg-amber-950/10 border border-amber-800/30 rounded-lg text-xs font-mono text-amber-400 flex items-center gap-2">
                    <RefreshCw className="w-3 h-3 animate-spin" />
                    Setting up your spreadsheet...
                  </div>
                ) : (
                  /* Fully connected & provisioned */
                  <div className="flex flex-col gap-1.5">
                    <a
                      href={googleIntegration.spreadsheet_url || "#"}
                      target="_blank"
                      rel="noreferrer"
                      className="w-full py-2 px-3 bg-emerald-950/20 hover:bg-emerald-900/20 border border-emerald-800 text-emerald-400 font-semibold rounded-lg text-xs flex items-center justify-center gap-2 transition-all duration-300 font-mono font-bold"
                    >
                      <span>Open Spreadsheet</span>
                      <ExternalLink className="w-3 h-3" />
                    </a>
                    <div className="flex gap-1.5">
                      <button
                        onClick={handleManualSyncSheets}
                        disabled={isSyncing}
                        className="flex-1 py-1.5 px-2 bg-zinc-900 hover:bg-zinc-800 border border-zinc-800 text-zinc-400 hover:text-zinc-300 text-[10px] rounded-lg font-mono flex items-center justify-center gap-1 transition-all"
                      >
                        <RefreshCw className={`w-3 h-3 ${isSyncing ? "animate-spin text-emerald-400" : ""}`} />
                        Sync Now
                      </button>
                      <button
                        onClick={handleDisconnectGoogle}
                        disabled={isDisconnecting}
                        className="flex-1 py-1.5 px-2 bg-zinc-950 hover:bg-zinc-900 border border-zinc-900 hover:border-red-900/40 text-zinc-500 hover:text-red-400 text-[10px] rounded-lg font-mono transition-all"
                      >
                        {isDisconnecting ? "..." : "Disconnect"}
                      </button>
                    </div>
                  </div>
                )}
              </div>
            </div>
          </div>

          {/* System Infrastructure Status Bento Card */}
          <div className="p-1.5 rounded-[1.25rem] bg-zinc-900/30 ring-1 ring-zinc-800/50 backdrop-blur-md">
            <div className="bg-[#0b0b0f] rounded-[calc(1.25rem-0.375rem)] p-5 shadow-[inset_0_1px_1px_rgba(255,255,255,0.03)] flex flex-col justify-between h-full gap-4">
              <div>
                <div className="flex items-center justify-between border-b border-zinc-900 pb-3 mb-3">
                  <h3 className="font-semibold text-xs text-zinc-200 uppercase tracking-wider font-mono flex items-center gap-1.5">
                    <Activity className="w-4 h-4 text-emerald-500" />
                    System Infrastructure
                  </h3>
                  <span className={`w-2 h-2 rounded-full ${
                    systemHealth?.status === "healthy" ? "bg-emerald-500" : "bg-red-500 animate-pulse"
                  }`} />
                </div>
                
                <div className="space-y-2 font-mono text-[10px]">
                  <div className="flex justify-between items-center">
                    <span className="text-zinc-500">PostgreSQL DB:</span>
                    <span className={systemHealth?.services?.postgres === "healthy" ? "text-emerald-400" : "text-red-400"}>
                      {systemHealth?.services?.postgres === "healthy" ? "ONLINE" : "OFFLINE"}
                    </span>
                  </div>
                  <div className="flex justify-between items-center">
                    <span className="text-zinc-500">Redis Broker:</span>
                    <span className={systemHealth?.services?.redis === "healthy" ? "text-emerald-400" : "text-red-400"}>
                      {systemHealth?.services?.redis === "healthy" ? "ONLINE" : "OFFLINE"}
                    </span>
                  </div>
                  <div className="flex justify-between items-center">
                    <span className="text-zinc-500">Celery Workers:</span>
                    <span className={systemHealth?.services?.celery === "healthy" ? "text-emerald-400" : "text-amber-400"}>
                      {systemHealth?.services?.celery === "healthy" 
                        ? `ONLINE (${systemHealth?.celery_metrics?.active_workers})` 
                        : "OFFLINE"}
                    </span>
                  </div>
                  <div className="flex justify-between items-center border-t border-zinc-900/60 pt-2 mt-2">
                    <span className="text-zinc-500 font-bold">Pending Queue:</span>
                    <span className={`font-bold ${
                      (systemHealth?.celery_metrics?.queue_size || 0) > 2000 ? "text-red-400 animate-pulse" : "text-zinc-300"
                    }`}>
                      {systemHealth?.celery_metrics?.queue_size || 0} tasks
                    </span>
                  </div>
                </div>
              </div>
              
              <div className="text-[9px] text-zinc-500 leading-normal border-t border-zinc-900 pt-2 font-mono">
                AutoApply AI self-heals by pausing discovery if queue size &gt; 2000.
              </div>
            </div>
          </div>
        </div>

        {/* 3. Core Stats Cards */}
        <div className="lg:col-span-3 grid grid-cols-2 sm:grid-cols-4 gap-4">
          
          {/* Double-Bezel Card: Shortlisted */}
          <div className="p-1.5 rounded-[1.25rem] bg-zinc-900/40 ring-1 ring-zinc-800/80">
            <div className="bg-[#0b0b0f] rounded-[calc(1.25rem-0.375rem)] p-4 shadow-[inset_0_1px_1px_rgba(255,255,255,0.03)] flex flex-col justify-between h-full">
              <span className="text-[10px] text-zinc-500 font-semibold uppercase tracking-wider font-mono">Shortlisted</span>
              <div className="flex items-baseline gap-2 mt-4">
                <span className="text-3xl font-bold font-mono text-emerald-400">{stats.shortlisted}</span>
                <span className="text-[10px] text-zinc-500 font-mono">reviewed</span>
              </div>
            </div>
          </div>

          {/* Double-Bezel Card: Submitted */}
          <div className="p-1.5 rounded-[1.25rem] bg-zinc-900/40 ring-1 ring-zinc-800/80">
            <div className="bg-[#0b0b0f] rounded-[calc(1.25rem-0.375rem)] p-4 shadow-[inset_0_1px_1px_rgba(255,255,255,0.03)] flex flex-col justify-between h-full">
              <span className="text-[10px] text-zinc-500 font-semibold uppercase tracking-wider font-mono">Submitted</span>
              <div className="flex items-baseline gap-2 mt-4">
                <span className="text-3xl font-bold font-mono text-blue-400">{stats.applied}</span>
                <span className="text-[10px] text-zinc-500 font-mono">apps</span>
              </div>
            </div>
          </div>

          {/* Double-Bezel Card: Failed */}
          <div className="p-1.5 rounded-[1.25rem] bg-zinc-900/40 ring-1 ring-zinc-800/80">
            <div className="bg-[#0b0b0f] rounded-[calc(1.25rem-0.375rem)] p-4 shadow-[inset_0_1px_1px_rgba(255,255,255,0.03)] flex flex-col justify-between h-full">
              <span className="text-[10px] text-zinc-500 font-semibold uppercase tracking-wider font-mono">Failed Runs</span>
              <div className="flex items-baseline gap-2 mt-4">
                <span className="text-3xl font-bold font-mono text-red-400">{stats.failed}</span>
                <span className="text-[10px] text-zinc-500 font-mono">errors</span>
              </div>
            </div>
          </div>

          {/* Double-Bezel Card: Match Rating */}
          <div className="p-1.5 rounded-[1.25rem] bg-zinc-900/40 ring-1 ring-zinc-800/80">
            <div className="bg-[#0b0b0f] rounded-[calc(1.25rem-0.375rem)] p-4 shadow-[inset_0_1px_1px_rgba(255,255,255,0.03)] flex flex-col justify-between h-full">
              <span className="text-[10px] text-zinc-500 font-semibold uppercase tracking-wider font-mono">Avg Match</span>
              <div className="flex items-baseline gap-2 mt-4">
                <span className="text-3xl font-bold font-mono text-amber-400">{stats.avg_match_score || 0}%</span>
                <span className="text-[10px] text-zinc-500 font-mono">rating</span>
              </div>
            </div>
          </div>

        </div>

        {/* 4. Live Logs Terminal */}
        <div className="lg:col-span-3 bg-[#050507] border border-zinc-900 rounded-2xl overflow-hidden shadow-xl flex flex-col">
          <div className="bg-[#0c0c0f] px-5 py-3 border-b border-zinc-900 flex items-center justify-between">
            <div className="flex items-center gap-2">
              <TermIcon className="w-4 h-4 text-emerald-500" />
              <span className="text-[10px] font-mono tracking-wider text-zinc-300 uppercase">Agent Event Logger Stream</span>
            </div>
            <div className="flex items-center gap-1.5">
              <span className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse" />
              <span className="text-[9px] font-mono text-emerald-500 uppercase tracking-widest">Live</span>
            </div>
          </div>

          <div 
            ref={terminalContainerRef} 
            className="p-5 font-mono text-[11px] text-emerald-400/90 h-56 overflow-y-auto space-y-1.5 select-text bg-[#030305] scan-line scrollbar-thin"
            style={{ scrollBehavior: 'auto' }}
          >
            {logs.map((log, i) => (
              <div key={i} className="leading-relaxed opacity-95">
                <span className="text-emerald-800 mr-2 font-bold select-none">&gt;&gt;</span>
                {log}
              </div>
            ))}
          </div>
        </div>

        {/* Review Queue (Pending Human Approval) */}
        {applications.filter(app => app.status === "PENDING_APPROVAL").length > 0 && (
          <div className="lg:col-span-3 p-1.5 rounded-[1.25rem] bg-amber-950/10 ring-1 ring-amber-500/30 backdrop-blur-md">
            <div className="bg-[#0b0b0f] rounded-[calc(1.25rem-0.375rem)] p-5 shadow-[inset_0_1px_1px_rgba(255,255,255,0.03)] space-y-6">
              <div className="flex items-center justify-between border-b border-zinc-900 pb-3">
                <h3 className="font-bold text-xs text-amber-400 uppercase tracking-widest flex items-center gap-2 font-mono">
                  <Clock className="w-4 h-4 text-amber-500 animate-pulse" />
                  Review Queue (Requires Approval)
                </h3>
                <span className="px-2 py-0.5 rounded bg-amber-950/40 text-amber-400 font-mono text-[9px] border border-amber-800/40">
                  {applications.filter(app => app.status === "PENDING_APPROVAL").length} pending execution
                </span>
              </div>

              <div className="grid grid-cols-1 gap-4">
                {applications.filter(app => app.status === "PENDING_APPROVAL").map((app) => {
                  const isEditing = activeReviewId === app.id;
                  return (
                    <div key={app.id} className="p-4 bg-[#07070a] rounded-xl border border-zinc-900 flex flex-col gap-4">
                      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
                        <div>
                          <div className="font-bold text-zinc-100 font-mono text-sm">
                            {app.job_posting?.company_name || "Unknown Company"}
                          </div>
                          <div className="text-[10px] text-zinc-400 mt-0.5">
                            {app.job_posting?.role_title || "Developer Role"} • Match Score:{" "}
                            <span className="text-emerald-400 font-bold font-mono">{app.match_score || 0}%</span>
                          </div>
                          <div className="text-[9px] text-zinc-500 font-mono mt-1">
                            Resume: <span className="text-zinc-400">{app.resume?.resume_name || "Primary Resume"}</span>
                          </div>
                        </div>

                        <div className="flex items-center gap-2 shrink-0">
                          {!isEditing && (
                            <button
                              onClick={() => {
                                setActiveReviewId(app.id);
                                setReviewAnswers(app.generated_answers || {});
                                setReviewCoverLetter(app.cover_letter || "");
                              }}
                              className="px-3 py-1.5 bg-zinc-900 hover:bg-zinc-800 border border-zinc-800 text-zinc-350 hover:text-zinc-150 text-[10px] rounded-lg transition-all font-mono cursor-pointer"
                            >
                              Review & Edit Answers
                            </button>
                          )}
                          <button
                            onClick={async () => {
                              if (isEditing) {
                                setIsSubmittingAnswers(true);
                                await updateApplicationAnswers(app.id, {
                                  generated_answers: reviewAnswers,
                                  cover_letter: reviewCoverLetter
                                });
                                setIsSubmittingAnswers(false);
                              }
                              await approveApplication(app.id);
                              if (isEditing) setActiveReviewId(null);
                            }}
                            disabled={isSubmittingAnswers}
                            className="px-3 py-1.5 bg-emerald-600 hover:bg-emerald-500 text-white font-bold text-[10px] rounded-lg transition-all flex items-center gap-1 font-mono shadow-[0_0_12px_rgba(16,185,129,0.2)] cursor-pointer"
                          >
                            <Play className="w-3 h-3 fill-current" />
                            Approve & Apply
                          </button>
                          <button
                            onClick={() => rejectApplication(app.id)}
                            className="px-3 py-1.5 bg-zinc-950 hover:bg-zinc-900 border border-zinc-900 hover:border-red-900/40 text-zinc-500 hover:text-red-400 text-[10px] rounded-lg transition-all font-mono cursor-pointer"
                          >
                            Dismiss
                          </button>
                        </div>
                      </div>

                      {isEditing && (
                        <div className="mt-2 border-t border-zinc-900/60 pt-4 space-y-4 animate-fade-in">
                          {/* Custom answers fields */}
                          {Object.keys(reviewAnswers).length > 0 ? (
                            <div className="space-y-3">
                              <h4 className="font-semibold text-zinc-300 text-[10px] uppercase tracking-wider font-mono">Screening Answers</h4>
                              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                                {Object.entries(reviewAnswers).map(([key, val]) => (
                                  <div key={key} className="space-y-1">
                                    <label className="block text-[10px] text-zinc-500 font-semibold font-mono">
                                      {cleanLabel(key)}
                                    </label>
                                    {key.includes("textarea") || val.length > 50 ? (
                                      <textarea
                                        rows={2}
                                        value={val}
                                        onChange={(e) => setReviewAnswers({ ...reviewAnswers, [key]: e.target.value })}
                                        className="w-full px-3 py-2 bg-zinc-950 border border-zinc-900 rounded-lg text-zinc-200 focus:outline-none focus:border-emerald-500 font-mono text-[10px]"
                                      />
                                    ) : (
                                      <input
                                        type="text"
                                        value={val}
                                        onChange={(e) => setReviewAnswers({ ...reviewAnswers, [key]: e.target.value })}
                                        className="w-full px-3 py-1.5 bg-zinc-950 border border-zinc-900 rounded-lg text-zinc-200 focus:outline-none focus:border-emerald-500 font-mono text-[10px]"
                                      />
                                    )}
                                  </div>
                                ))}
                              </div>
                            </div>
                          ) : (
                            <div className="text-[10px] text-zinc-500 italic font-mono">// No screening answers required for this form.</div>
                          )}

                          {/* Cover Letter Draft */}
                          <div className="space-y-1">
                            <label className="block text-[10px] text-zinc-500 font-semibold font-mono">Tailored Cover Letter</label>
                            <textarea
                              rows={6}
                              value={reviewCoverLetter}
                              onChange={(e) => setReviewCoverLetter(e.target.value)}
                              className="w-full px-3 py-2 bg-zinc-950 border border-zinc-900 rounded-lg text-zinc-200 focus:outline-none focus:border-emerald-500 font-sans text-[10.5px] leading-relaxed scrollbar-thin"
                              placeholder="Drafting cover letter..."
                            />
                          </div>

                          <div className="flex justify-end gap-2 pt-2">
                            <button
                              onClick={async () => {
                                setIsSubmittingAnswers(true);
                                const ok = await updateApplicationAnswers(app.id, {
                                  generated_answers: reviewAnswers,
                                  cover_letter: reviewCoverLetter
                                });
                                setIsSubmittingAnswers(false);
                                if (ok) setActiveReviewId(null);
                              }}
                              disabled={isSubmittingAnswers}
                              className="px-3 py-1.5 bg-zinc-900 hover:bg-zinc-850 border border-zinc-800 text-zinc-300 text-[10px] rounded-lg transition-all font-mono cursor-pointer"
                            >
                              Save Changes Only
                            </button>
                            <button
                              onClick={() => setActiveReviewId(null)}
                              className="px-3 py-1.5 bg-zinc-950 hover:bg-zinc-900 border border-zinc-900 text-zinc-500 hover:text-zinc-400 text-[10px] rounded-lg transition-all font-mono cursor-pointer"
                            >
                              Cancel
                            </button>
                          </div>
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            </div>
          </div>
        )}

        {/* 5. Applications table */}
        <div className="lg:col-span-3 bg-[#0b0b0f] border border-zinc-900 rounded-2xl overflow-hidden shadow-sm">
          <div className="px-6 py-4 border-b border-zinc-900 flex items-center justify-between bg-zinc-900/10">
            <div>
              <h3 className="font-semibold text-xs text-zinc-200 uppercase tracking-wider font-mono">Active Applications Pipeline</h3>
              <p className="text-[10px] text-zinc-500 mt-0.5">Jobs passing through the verification and browser submission stages</p>
            </div>
            <span className="px-2 py-0.5 rounded bg-zinc-900 text-zinc-400 font-mono text-[10px] border border-zinc-800">
              {applications.length} pipeline records
            </span>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs border-collapse font-sans">
              <thead>
                <tr className="border-b border-zinc-900 text-zinc-400 uppercase tracking-wider bg-zinc-950/40 text-[9px] font-bold">
                  <th className="px-6 py-3.5">Company & Role</th>
                  <th className="px-6 py-3.5 text-center">Match Score</th>
                  <th className="px-6 py-3.5 text-center">Status</th>
                  <th className="px-6 py-3.5 text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-zinc-900/50">
                {applications.length === 0 ? (
                  <tr>
                    <td colSpan={4} className="px-6 py-12 text-center text-zinc-500 font-mono text-[10px]">
                      // No jobs discovered in application pipeline yet
                    </td>
                  </tr>
                ) : (
                  applications.map((app) => (
                    <tr key={app.id} className="hover:bg-zinc-900/20 transition-colors duration-300">
                      <td className="px-6 py-4">
                        <div className="font-semibold text-zinc-250">
                          {app.job_posting?.company_name || app.job_description_parsed?.company_name || "Unknown Company"}
                        </div>
                        <div className="text-[10px] text-zinc-400 mt-0.5">
                          {app.job_posting?.role_title || app.job_description_parsed?.role_title || "Developer Role"}
                        </div>
                      </td>
                      <td className="px-6 py-4 text-center">
                        <span className={`px-2 py-0.5 rounded font-mono font-bold text-[10px] border ${
                          (app.match_score || 0) >= 75 
                            ? "bg-emerald-950/20 text-emerald-400 border-emerald-900/50" 
                            : "bg-zinc-900 text-amber-400 border-zinc-800"
                        }`}>
                          {app.match_score || 0}%
                        </span>
                      </td>
                      <td className="px-6 py-4 text-center">
                        <span className={`inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-[9px] font-semibold tracking-wider border uppercase font-mono
                          ${app.status === "SUBMITTED" ? "bg-emerald-950/30 text-emerald-400 border-emerald-800/40" : ""}
                          ${app.status === "PENDING_APPROVAL" ? "bg-amber-950/30 text-amber-400 border-amber-800/40 animate-pulse border-dashed" : ""}
                          ${app.status === "INTERVIEW" ? "bg-purple-950/30 text-purple-400 border-purple-800/40 shadow-[0_0_8px_rgba(168,85,247,0.1)]" : ""}
                          ${app.status === "OA_RECEIVED" ? "bg-indigo-950/30 text-indigo-400 border-indigo-800/40 shadow-[0_0_8px_rgba(99,102,241,0.1)]" : ""}
                          ${app.status === "OFFER" ? "bg-teal-950/30 text-teal-400 border-teal-800/40 shadow-[0_0_12px_rgba(20,184,166,0.2)] animate-pulse" : ""}
                          ${app.status === "REJECTED" ? "bg-red-950/30 text-red-400 border-red-800/40" : ""}
                          ${app.status === "READY" ? "bg-zinc-900 text-zinc-300 border-zinc-800" : ""}
                          ${app.status === "DISCOVERED" ? "bg-zinc-900 text-zinc-500 border-zinc-850" : ""}
                          ${app.status === "MATCHED" ? "bg-zinc-900 text-zinc-400 border-zinc-850" : ""}
                        `}>
                          {app.status}
                        </span>
                      </td>
                      <td className="px-6 py-4 text-right">
                        {app.status === "PENDING_APPROVAL" ? (
                          <div className="inline-flex items-center gap-2">
                            <button
                              onClick={() => approveApplication(app.id)}
                              className="px-2.5 py-1 bg-emerald-600 hover:bg-emerald-500 text-emerald-50 text-[10px] rounded-md transition-all flex items-center gap-1 font-semibold cursor-pointer"
                            >
                              <Play className="w-3 h-3 fill-current" />
                              Approve
                            </button>
                            <button
                              onClick={() => rejectApplication(app.id)}
                              className="px-2.5 py-1 bg-zinc-900 hover:bg-zinc-800 text-zinc-400 text-[10px] rounded-md border border-zinc-800 transition-all font-semibold cursor-pointer"
                            >
                              Dismiss
                            </button>
                          </div>
                        ) : (
                          <button
                            onClick={() => setSelectedAppForDetails(app)}
                            className="px-2.5 py-1 bg-zinc-900 hover:bg-zinc-850 border border-zinc-800 hover:border-zinc-700 text-zinc-300 text-[10px] rounded-md transition-all font-semibold cursor-pointer font-mono"
                          >
                            Details
                          </button>
                        )}
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </div>

      </div>

      {/* Application Details Modal */}
      {selectedAppForDetails && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-zinc-950/80 backdrop-blur-sm animate-fade-in text-xs">
          <div className="relative w-full max-w-4xl max-h-[85vh] overflow-y-auto bg-[#09090c] border border-zinc-800/80 rounded-2xl p-6 shadow-2xl flex flex-col gap-6 text-xs scrollbar-thin">
            
            {/* Modal Header */}
            <div className="flex items-start justify-between border-b border-zinc-900 pb-4">
              <div>
                <h3 className="text-sm font-bold text-zinc-150 font-mono">
                  {selectedAppForDetails.job_posting?.company_name || "Unknown Company"}
                </h3>
                <p className="text-[10px] text-zinc-400 mt-1">
                  {selectedAppForDetails.job_posting?.role_title || "Developer Role"} • Status:{" "}
                  <span className="text-emerald-400 font-bold font-mono">{selectedAppForDetails.status}</span>
                </p>
              </div>
              <button
                onClick={() => setSelectedAppForDetails(null)}
                className="p-1 rounded-lg bg-zinc-900 border border-zinc-800 text-zinc-400 hover:text-zinc-200 transition-all cursor-pointer"
              >
                <XCircle className="w-4 h-4" />
              </button>
            </div>

            {isLoadingDetails ? (
              <div className="py-20 flex flex-col items-center justify-center gap-3 text-zinc-400 font-mono">
                <RefreshCw className="w-5 h-5 animate-spin text-emerald-500" />
                Loading timeline & evidence...
              </div>
            ) : (
              <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                
                {/* Left side: Timeline Events & Info */}
                <div className="space-y-6">
                  {/* General details */}
                  <div className="p-4 bg-[#050507] border border-zinc-900 rounded-xl space-y-2">
                    <h4 className="font-bold text-[10px] uppercase tracking-wider text-zinc-400 font-mono">Application Details</h4>
                    <div className="grid grid-cols-2 gap-y-2 font-mono text-[10px]">
                      <span className="text-zinc-500">Match score:</span>
                      <span className="text-zinc-350">{selectedAppForDetails.match_score || 0}%</span>
                      <span className="text-zinc-500">Attempts:</span>
                      <span className="text-zinc-350">{selectedAppForDetails.attempts || 0}</span>
                      <span className="text-zinc-500">Resume:</span>
                      <span className="text-zinc-355">{selectedAppForDetails.resume?.resume_name || "Primary"}</span>
                      {selectedAppForDetails.submitted_at && (
                        <>
                          <span className="text-zinc-500">Submitted at:</span>
                          <span className="text-zinc-350">{new Date(selectedAppForDetails.submitted_at).toLocaleString()}</span>
                        </>
                      )}
                      {selectedAppForDetails.last_error && (
                        <>
                          <span className="text-red-500 font-bold">Last error:</span>
                          <span className="text-red-400 leading-normal select-text">{selectedAppForDetails.last_error}</span>
                        </>
                      )}
                    </div>
                  </div>

                  {/* Timeline events */}
                  <div className="space-y-3">
                    <h4 className="font-bold text-[10px] uppercase tracking-wider text-zinc-400 font-mono">Execution Timeline</h4>
                    {events.length === 0 ? (
                      <div className="text-[10px] text-zinc-500 italic font-mono p-4 bg-[#050507] border border-zinc-900 rounded-xl">
                        // No activity logged yet
                      </div>
                    ) : (
                      <div className="border-l border-zinc-900 ml-2 pl-4 space-y-4">
                        {events.map((ev, i) => (
                          <div key={ev.id || i} className="relative">
                            <span className="absolute -left-[21px] top-1 w-2 h-2 rounded-full bg-emerald-500 ring-4 ring-[#09090c]" />
                            <div className="text-[10px] font-semibold text-zinc-250 font-mono">{ev.event_type}</div>
                            <div className="text-[9px] text-zinc-500 font-mono mt-0.5">
                              {new Date(ev.created_at).toLocaleTimeString()}
                            </div>
                            {ev.details && (
                              <pre className="mt-1.5 p-2 bg-[#030304] border border-zinc-900 text-zinc-400 font-mono text-[9px] rounded-lg max-w-full overflow-x-auto leading-relaxed scrollbar-thin select-text">
                                {JSON.stringify(ev.details, null, 2)}
                              </pre>
                            )}
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                </div>

                {/* Right side: Screenshot & Confirmation Text Evidence */}
                <div className="space-y-6">
                  <h4 className="font-bold text-[10px] uppercase tracking-wider text-zinc-400 font-mono">Submission Evidence</h4>
                  {evidence.length === 0 ? (
                    <div className="text-[10px] text-zinc-500 italic font-mono p-4 bg-[#050507] border border-zinc-900 rounded-xl">
                      // No submission evidence captured yet
                    </div>
                  ) : (
                    evidence.map((ev, i) => (
                      <div key={ev.id || i} className="space-y-4">
                        {/* Embedded Screenshot */}
                        <div className="space-y-1.5">
                          <div className="text-[9px] text-zinc-500 uppercase tracking-widest font-mono">Confirmation Screenshot</div>
                          <div className="relative border border-zinc-900 rounded-xl overflow-hidden bg-zinc-950 aspect-video group">
                            <img
                              src={`${API_BASE}/applications/evidence/download?key=${ev.screenshot_path}`}
                              alt="Confirmation Screenshot"
                              className="w-full h-full object-contain hover:scale-105 transition-transform duration-300"
                            />
                          </div>
                        </div>

                        {/* Confirmation text */}
                        {ev.confirmation_text && (
                          <div className="space-y-1.5">
                            <div className="text-[9px] text-zinc-500 uppercase tracking-widest font-mono">Confirmation Text</div>
                            <div className="p-3 bg-[#030304] border border-zinc-900 text-zinc-350 font-mono text-[9.5px] rounded-xl leading-relaxed max-h-48 overflow-y-auto whitespace-pre-wrap scrollbar-thin select-text">
                              {ev.confirmation_text}
                            </div>
                          </div>
                        )}
                      </div>
                    ))
                  )}
                </div>

              </div>
            )}
            
            {/* Modal Footer */}
            <div className="border-t border-zinc-900 pt-4 flex justify-end">
              <button
                onClick={() => setSelectedAppForDetails(null)}
                className="px-4 py-2 bg-zinc-900 hover:bg-zinc-800 border border-zinc-800 text-zinc-300 font-bold rounded-xl transition-all cursor-pointer font-mono"
              >
                Close
              </button>
            </div>

          </div>
        </div>
      )}
    </div>
  );
}
