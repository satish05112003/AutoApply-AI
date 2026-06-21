"use client";

import React, { useEffect, useState } from "react";
import { useStore } from "@/store/useStore";
import { API_BASE } from "@/config";
import { 
  Activity, 
  Clock, 
  Play, 
  Settings, 
  FileSpreadsheet, 
  RefreshCw, 
  XCircle,
  Pause,
  ExternalLink
} from "lucide-react";

// Modular bento components
import DashboardHeader from "./components/DashboardHeader";
import StatsGrid from "./components/StatsGrid";
import LiveJobFeed from "./components/LiveJobFeed";
import ApplicationPipeline from "./components/ApplicationPipeline";
import JobDetailsDrawer from "./components/JobDetailsDrawer";
import ActivityLog from "./components/ActivityLog";
import AdminDebugPanel from "./components/AdminDebugPanel";

export default function DashboardPage() {
  const { 
    token,
    applications, 
    agentStatus,
    googleIntegration,
    systemHealth,
    fetchApplications, 
    fetchStats, 
    fetchAgentStatus,
    fetchSystemHealth,
    fetchSystemEvents,
    fetchSheetsStatus,
    fetchPlatformSessions,
    approveApplication, 
    rejectApplication, 
    updateApplicationAnswers,
    startDiscovery,
    stopDiscovery,
    startAutoApply,
    stopAutoApply,
    startEmailMonitoring,
    stopEmailMonitoring,
    connectGoogleSheets,
    disconnectGoogleSheets,
    manualSyncGoogleSheets,
    addLogLine 
  } = useStore();

  const [isSyncing, setIsSyncing] = useState(false);
  const [isConnectingGoogle, setIsConnectingGoogle] = useState(false);
  const [isDisconnecting, setIsDisconnecting] = useState(false);
  const [googleCallbackMsg, setGoogleCallbackMsg] = useState<string | null>(null);

  // Review Queue and Details States
  const [activeReviewId, setActiveReviewId] = useState<string | null>(null);
  const [reviewAnswers, setReviewAnswers] = useState<Record<string, string>>({});
  const [reviewCoverLetter, setReviewCoverLetter] = useState<string>("");
  const [isSubmittingAnswers, setIsSubmittingAnswers] = useState(false);
  const [selectedAppForDetails, setSelectedAppForDetails] = useState<any | null>(null);

  // Load initial data and poll every 5 seconds
  useEffect(() => {
    fetchApplications();
    fetchStats();
    fetchAgentStatus();
    fetchSystemHealth();
    fetchSystemEvents();
    fetchSheetsStatus();
    fetchPlatformSessions();

    const interval = setInterval(() => {
      fetchAgentStatus();
      fetchApplications();
      fetchSystemHealth();
      fetchStats();
      fetchSystemEvents();
      fetchSheetsStatus();
      fetchPlatformSessions();
    }, 5000);

    return () => clearInterval(interval);
  }, []);

  // Handle Google OAuth callback query params
  useEffect(() => {
    if (typeof window === "undefined") return;
    const params = new URLSearchParams(window.location.search);
    const gsParam = params.get("google_sheets");
    if (gsParam === "connected") {
      const email = params.get("email") || "";
      setGoogleCallbackMsg(`Google Sheets connected (${email}). Spreadsheet provisioning in progress...`);
      addLogLine(`[System] Google Sheets connected for ${email}. Provisioning spreadsheet...`);
      fetchSheetsStatus();
      
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

  const handleConnectGoogle = async () => {
    setIsConnectingGoogle(true);
    addLogLine("[System] Connecting Google account...");
    await connectGoogleSheets();
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

  const cleanLabel = (key: string) => {
    const match = key.match(/name=['"]([^'"]+)['"]/);
    if (match) {
      return match[1].replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase());
    }
    return key.replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase());
  };

  return (
    <div className="space-y-6 text-xs text-zinc-300">
      
      {/* 1. Header component */}
      <DashboardHeader wsStatus={useStore.getState().token ? "connected" : "disconnected"} />

      {/* Redis Connection Down Alert */}
      {agentStatus?.redis_connected === false && (
        <div className="p-3.5 bg-red-950/20 border border-red-800 rounded-xl text-red-400 font-mono text-[10px] flex items-center justify-between shadow-md">
          <div className="flex items-center gap-2">
            <XCircle className="w-4 h-4 text-red-500 shrink-0 animate-pulse" />
            <span>
              <strong>CRITICAL WARNING:</strong> Redis connection is down. Background tasks (Celery worker/beat) are offline.
            </span>
          </div>
        </div>
      )}

      {/* Google OAuth Status Banner */}
      {googleCallbackMsg && (
        <div className={`p-3.5 rounded-xl font-mono text-[10px] flex items-center justify-between border shadow-md ${
          googleCallbackMsg.includes("connected")
            ? "bg-emerald-950/20 border-emerald-800 text-emerald-400"
            : "bg-amber-950/20 border-amber-800 text-amber-400"
        }`}>
          <div className="flex items-center gap-2">
            <FileSpreadsheet className="w-4 h-4 shrink-0 text-emerald-400" />
            <span>{googleCallbackMsg}</span>
          </div>
          <button
            onClick={() => setGoogleCallbackMsg(null)}
            className="text-zinc-500 hover:text-zinc-300 transition-colors ml-4 cursor-pointer"
          >
            <XCircle className="w-4 h-4" />
          </button>
        </div>
      )}

      {/* 2. Stats Grid component */}
      <StatsGrid />

      {/* 3. Review Queue (Human Approval Block) */}
      {applications.filter(app => app.status === "PENDING_APPROVAL").length > 0 && (
        <div className="premium-card p-6 border-amber-900/35 bg-amber-950/5 space-y-6">
            <div className="flex items-center justify-between border-b border-zinc-900 pb-3">
              <h3 className="font-bold text-xs text-amber-400 uppercase tracking-widest flex items-center gap-2 font-mono">
                <Clock className="w-4 h-4 text-amber-500 animate-pulse" />
                Review Queue (Requires Approval)
              </h3>
              <span className="px-2 py-0.5 rounded bg-amber-950/40 text-amber-400 font-mono text-[9px] border border-amber-850/40 font-bold">
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
                        <div className="text-[9px] text-zinc-550 font-mono mt-1">
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
                            className="px-3 py-1.5 bg-zinc-900 hover:bg-zinc-850 border border-zinc-800 text-zinc-350 hover:text-zinc-150 text-[10px] rounded-lg transition-all font-mono cursor-pointer"
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
                          className="px-3 py-1.5 bg-emerald-655 bg-emerald-600 hover:bg-emerald-500 text-white font-bold text-[10px] rounded-lg transition-all flex items-center gap-1 font-mono shadow-[0_0_12px_rgba(16,185,129,0.2)] cursor-pointer"
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
                        {/* Screening questions custom answers */}
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
                          <div className="text-[10px] text-zinc-500 italic font-mono">// No custom screening answers required.</div>
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
      )}

      {/* 4. Controls layout (Orchestrator Controls and Sheets Card) */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        
        {/* Left Side: Agent Orchestrator Panel */}
        <div className="lg:col-span-2 premium-card p-6 space-y-6">
            <h3 className="font-bold text-xs text-zinc-300 uppercase tracking-widest border-b border-zinc-900 pb-3 flex items-center gap-2 font-mono">
              <Settings className="w-4 h-4 text-emerald-500" />
              Autonomous Agent Orchestrator
            </h3>

            {/* Daemon statuses grid */}
            <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-4 gap-4">
              {/* Job Discovery */}
              <div className="p-3 bg-zinc-950/40 rounded-xl border border-zinc-900/80 flex flex-col justify-between gap-3">
                <span className="text-[10px] text-zinc-550 font-bold uppercase tracking-wider font-mono">Job Discovery</span>
                <div className="flex items-center justify-between">
                  <span className="font-bold text-zinc-200">Crawlers</span>
                  <span className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded-full text-[9px] font-mono font-bold border ${
                    agentStatus?.discovery_running 
                      ? "bg-emerald-950/40 text-emerald-400 border-emerald-800/40 shadow-[0_0_8px_rgba(16,185,129,0.15)] animate-pulse" 
                      : "bg-zinc-900 text-zinc-500 border-zinc-850"
                  }`}>
                    {agentStatus?.discovery_running ? "RUNNING" : "STOPPED"}
                  </span>
                </div>
              </div>

              {/* AI Matching */}
              <div className="p-3 bg-zinc-950/40 rounded-xl border border-zinc-900/80 flex flex-col justify-between gap-3">
                <span className="text-[10px] text-zinc-550 font-bold uppercase tracking-wider font-mono">AI Matching</span>
                <div className="flex items-center justify-between">
                  <span className="font-bold text-zinc-200">Weights</span>
                  <span className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded-full text-[9px] font-mono font-bold border ${
                    agentStatus?.agent_enabled 
                      ? "bg-emerald-950/40 text-emerald-400 border-emerald-800/40" 
                      : "bg-zinc-900 text-zinc-500 border-zinc-850"
                  }`}>
                    {agentStatus?.agent_enabled ? "ACTIVE" : "PAUSED"}
                  </span>
                </div>
              </div>

              {/* Auto Apply */}
              <div className="p-3 bg-zinc-950/40 rounded-xl border border-zinc-900/80 flex flex-col justify-between gap-3">
                <span className="text-[10px] text-zinc-550 font-bold uppercase tracking-wider font-mono">Auto Apply</span>
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

              {/* Email Monitor */}
              <div className="p-3 bg-zinc-950/40 rounded-xl border border-zinc-900/80 flex flex-col justify-between gap-3">
                <span className="text-[10px] text-zinc-550 font-bold uppercase tracking-wider font-mono">Email Monitor</span>
                <div className="flex items-center justify-between">
                  <span className="font-bold text-zinc-200">Gmail IMAP</span>
                  <span className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded-full text-[9px] font-mono font-bold border ${
                    agentStatus?.email_monitoring_running 
                      ? "bg-emerald-950/40 text-emerald-400 border-emerald-800/40 shadow-[0_0_8px_rgba(16,185,129,0.15)] animate-pulse" 
                      : "bg-zinc-900 text-zinc-500 border-zinc-850"
                  }`}>
                    {agentStatus?.email_monitoring_running ? "TRACKING" : "OFFLINE"}
                  </span>
                </div>
              </div>
            </div>

            {/* Daemon control buttons */}
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
                  </div>
                ) : (
                  <button 
                    onClick={handleToggleDiscovery}
                    className={`px-3 py-2 rounded-lg font-bold transition-all border font-mono text-[10px] cursor-pointer ${
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
                  className={`px-3 py-2 rounded-lg font-bold transition-all border font-mono text-[10px] cursor-pointer ${
                    agentStatus?.auto_apply_running 
                      ? "bg-amber-950/20 border-amber-800 text-amber-400 hover:bg-amber-900/20" 
                      : "bg-blue-600 border-blue-500 text-white hover:bg-blue-500"
                  }`}
                >
                  {agentStatus?.auto_apply_running ? "Switch to Semi-Auto" : "Start Auto Apply"}
                </button>
                
                <button 
                  onClick={handleToggleEmailMonitoring}
                  className={`px-3 py-2 rounded-lg font-bold transition-all border font-mono text-[10px] cursor-pointer ${
                    agentStatus?.email_monitoring_running 
                      ? "bg-zinc-900 border-zinc-850 text-zinc-400 hover:bg-zinc-800" 
                      : "bg-zinc-900 border-zinc-855 text-emerald-400 hover:bg-zinc-800 border-zinc-800"
                  }`}
                >
                  {agentStatus?.email_monitoring_running ? "Stop Email Tracker" : "Start Email Tracker"}
                </button>
              </div>

              {/* Pause system */}
              <div className="flex items-center gap-2">
                {agentStatus?.agent_enabled ? (
                  <button 
                    onClick={handlePauseSystem}
                    className="flex items-center gap-1 px-3 py-2 rounded-lg bg-zinc-900 hover:bg-zinc-850 border border-zinc-850 text-zinc-400 font-mono text-[10px] cursor-pointer"
                  >
                    <Pause className="w-3 h-3" />
                    Pause System
                  </button>
                ) : (
                  <button 
                    onClick={handleResumeSystem}
                    className="flex items-center gap-1 px-3 py-2 rounded-lg bg-emerald-950/20 border border-emerald-800 text-emerald-400 font-mono text-[10px] font-bold cursor-pointer"
                  >
                    <Play className="w-3 h-3 fill-current" />
                    Resume System
                  </button>
                )}
              </div>
            </div>
          </div>

        {/* Right Side: Sheets Tracker Card */}
        <div className="premium-card p-6 flex flex-col justify-between h-full gap-4">
            <div className="flex items-start gap-3.5">
              <div className={`p-2.5 rounded-lg border shrink-0 ${googleIntegration.connected && googleIntegration.provisioned ? "bg-emerald-950/20 border-emerald-800/45 text-emerald-450" : "bg-zinc-900 border-zinc-850 text-zinc-500"}`}>
                <FileSpreadsheet className="w-5 h-5 text-emerald-500" />
              </div>
              <div className="space-y-1 flex-1 min-w-0 font-mono">
                <div className="flex items-center gap-2">
                  <h3 className="font-semibold text-xs text-zinc-200">Google Sheets</h3>
                  {googleIntegration.connected && googleIntegration.provisioned && (
                    <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded-full text-[8px] font-mono font-bold bg-emerald-950/40 text-emerald-400 border border-emerald-800/40">
                      LIVE
                    </span>
                  )}
                </div>

                {googleIntegration.connected ? (
                  <div className="space-y-0.5 text-[9.5px]">
                    <p className="text-zinc-400 truncate">
                      {googleIntegration.google_email || "Connected"}
                    </p>
                    {googleIntegration.last_sync_at && (
                      <div className="text-zinc-500">
                        Sync: {new Date(googleIntegration.last_sync_at).toLocaleTimeString()}
                      </div>
                    )}
                  </div>
                ) : (
                  <p className="text-[10px] text-zinc-400 font-sans leading-relaxed">
                    {googleIntegration.configured
                      ? "Connect your Google account to sync applications to your personal spreadsheet."
                      : "Google OAuth not configured."}
                  </p>
                )}
              </div>
            </div>

            {/* Google connection action button */}
            <div className="flex flex-col gap-2 font-mono text-[10px]">
              {!googleIntegration.connected ? (
                <button
                  onClick={handleConnectGoogle}
                  disabled={!googleIntegration.configured || isConnectingGoogle}
                  className="w-full py-2 px-3 bg-zinc-900 hover:bg-zinc-800 border border-zinc-800 text-zinc-200 font-semibold rounded-lg text-xs transition-all font-mono flex items-center justify-center gap-2 cursor-pointer"
                >
                  <FileSpreadsheet className="w-3.5 h-3.5" />
                  {isConnectingGoogle ? "Redirecting..." : "Connect Google Sheets"}
                </button>
              ) : !googleIntegration.provisioned ? (
                <div className="w-full py-2 px-3 bg-amber-950/10 border border-amber-800/30 rounded-lg text-xs text-amber-400 flex items-center gap-2">
                  <RefreshCw className="w-3.5 h-3.5 animate-spin" />
                  Setting up spreadsheet...
                </div>
              ) : (
                <div className="flex flex-col gap-1.5">
                  <a
                    href={googleIntegration.spreadsheet_url || "#"}
                    target="_blank"
                    rel="noreferrer"
                    className="w-full py-2 px-3 bg-emerald-950/20 hover:bg-emerald-900/20 border border-emerald-800 text-emerald-400 font-semibold rounded-lg text-xs flex items-center justify-center gap-2 transition-all font-mono font-bold"
                  >
                    <span>Open Spreadsheet</span>
                    <ExternalLink className="w-3.5 h-3.5" />
                  </a>
                  <div className="flex gap-1.5">
                    <button
                      onClick={handleManualSyncSheets}
                      disabled={isSyncing}
                      className="flex-1 py-1.5 px-2 bg-zinc-900 hover:bg-zinc-850 border border-zinc-850 text-zinc-400 hover:text-zinc-200 rounded-lg flex items-center justify-center gap-1 transition-all cursor-pointer"
                    >
                      <RefreshCw className={`w-3 h-3 ${isSyncing ? "animate-spin text-emerald-400" : ""}`} />
                      Sync
                    </button>
                    <button
                      onClick={handleDisconnectGoogle}
                      disabled={isDisconnecting}
                      className="flex-1 py-1.5 px-2 bg-zinc-950 hover:bg-zinc-900 border border-zinc-900 hover:border-red-900/40 text-zinc-550 hover:text-red-400 rounded-lg transition-all cursor-pointer"
                    >
                      {isDisconnecting ? "..." : "Disconnect"}
                    </button>
                  </div>
                </div>
              )}
            </div>
          </div>

      </div>

      {/* 5. Stream and diagnostics row */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Live crawler job feed */}
        <div className="lg:col-span-2">
          <LiveJobFeed onSelectApplication={setSelectedAppForDetails} />
        </div>

        {/* Live log stream */}
        <div className="flex flex-col gap-6">
          <ActivityLog />
          <AdminDebugPanel />
        </div>
      </div>

      {/* 6. Kanban board pipeline component */}
      <div className="premium-card p-6">
        <ApplicationPipeline onSelectApplication={setSelectedAppForDetails} />
      </div>

      {/* Sliding Job detail drawer panel */}
      {selectedAppForDetails && (
        <JobDetailsDrawer 
          app={selectedAppForDetails} 
          onClose={() => setSelectedAppForDetails(null)} 
        />
      )}

    </div>
  );
}
