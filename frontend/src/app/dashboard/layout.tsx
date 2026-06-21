"use client";

import React, { useEffect, useState, useRef } from "react";
import { useRouter, usePathname } from "next/navigation";
import Link from "next/link";
import { useStore } from "@/store/useStore";
import { WS_BASE } from "@/config";
import { 
  Activity, 
  FileText, 
  Settings, 
  User as UserIcon, 
  LogOut,
  Terminal as TermIcon
} from "lucide-react";

export default function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const router = useRouter();
  const pathname = usePathname();
  
  const { 
    token, 
    user, 
    fetchProfile, 
    fetchApplications, 
    fetchStats, 
    fetchSheetsStatus,
    fetchAgentStatus,
    addLogLine,
    logout 
  } = useStore();

  const [wsStatus, setWsStatus] = useState<"connected" | "connecting" | "disconnected">("disconnected");

  // ── Prevent ALL programmatic viewport scrolling (Issue #1) ────────────────
  // The dashboard must NEVER auto-scroll the viewport. Log updates, WebSocket
  // messages, and React state changes must not change the user's scroll
  // position. Only the ActivityLog container scrolls its own internal area.
  useEffect(() => {
    if (typeof window === "undefined") return;

    const noop = () => {};

    // Freeze all window-level scroll APIs
    const origScrollTo  = window.scrollTo;
    const origScroll    = window.scroll;
    const origScrollBy  = window.scrollBy;
    window.scrollTo  = noop as any;
    window.scroll    = noop as any;
    window.scrollBy  = noop as any;

    // Block scrollIntoView entirely — it causes viewport jumps on dashboard.
    // The ActivityLog uses scrollContainerRef.current.scrollTop directly
    // (not scrollIntoView), so this block does not affect log scrolling.
    const origScrollIntoView = Element.prototype.scrollIntoView;
    Element.prototype.scrollIntoView = noop as any;

    // Force preventScroll on every focus so focusing a new element never
    // jumps the viewport.
    const origFocus = HTMLElement.prototype.focus;
    HTMLElement.prototype.focus = function (options?: FocusOptions) {
      origFocus.call(this, { ...options, preventScroll: true });
    };

    return () => {
      window.scrollTo  = origScrollTo;
      window.scroll    = origScroll;
      window.scrollBy  = origScrollBy;
      Element.prototype.scrollIntoView = origScrollIntoView;
      HTMLElement.prototype.focus      = origFocus;
    };
  }, []);


  // Auth Protection & Initial Data Load
  useEffect(() => {
    if (!token) {
      router.push("/");
    } else {
      fetchProfile();
      fetchApplications();
      fetchStats();
      fetchSheetsStatus();
      fetchAgentStatus();
    }
  }, [token, router]);

  // WebSocket connection with auto-reconnect and exponential backoff
  useEffect(() => {
    if (!user?.id) return;
    
    let socket: WebSocket | null = null;
    let reconnectTimeoutId: NodeJS.Timeout | null = null;
    let reconnectDelay = 1000; // start at 1 second
    const maxReconnectDelay = 30000; // max 30 seconds
    let wasIntentionallyClosed = false;

    const connect = () => {
      if (wasIntentionallyClosed) return;
      
      const wsUrl = `${WS_BASE}/ws/${user.id}`;
      console.log(`[WebSocket] Connecting to ${wsUrl}...`);
      setWsStatus("connecting");
      addLogLine("[System] WebSocket connecting...");
      
      socket = new WebSocket(wsUrl);

      socket.onopen = () => {
        console.log(`[WebSocket] Connected successfully to ${wsUrl}`);
        setWsStatus("connected");
        addLogLine("[System] WebSocket connection established.");
        reconnectDelay = 1000; // reset retry delay
      };

      socket.onmessage = (event) => {
        try {
          const payload = JSON.parse(event.data);
          console.log(`[WebSocket] Received payload:`, payload);
          if (payload.event === "SYSTEM_STATUS") {
            useStore.setState({ systemHealth: payload.data });
            return;
          }
          if (payload.event === "JOB_MATCHED") {
            addLogLine(`[MatchingAgent] Matched job ID '${payload.job_id}' with score ${payload.score}% -> ${payload.decision}`);
          } else if (payload.event === "APPLICATION_SUBMITTED") {
            addLogLine(`[ApplicationAgent] Successfully submitted application ID: ${payload.application_id}`);
          } else if (payload.event === "RESUME_PARSED") {
            addLogLine(`[ResumeAgent] Parsed resume details successfully. Specialized type: ${payload.type}`);
          }
          // Refresh values
          fetchApplications();
          fetchStats();
        } catch (e) {
          addLogLine(`[Agent] ${event.data}`);
        }
      };

      socket.onclose = (event) => {
        setWsStatus("disconnected");
        if (wasIntentionallyClosed) {
          console.log("[WebSocket] Intentional disconnect.");
          addLogLine("[System] WebSocket disconnected.");
          return;
        }

        console.warn(`[WebSocket] Disconnected. Reconnecting in ${reconnectDelay}ms... (Code: ${event.code})`);
        addLogLine(`[System] WebSocket disconnected. Retrying connection in ${Math.round(reconnectDelay / 1000)}s...`);
        
        reconnectTimeoutId = setTimeout(() => {
          reconnectDelay = Math.min(reconnectDelay * 1.5, maxReconnectDelay);
          connect();
        }, reconnectDelay);
      };

      socket.onerror = (error) => {
        console.error(`[WebSocket] Connection error:`, error);
      };
    };

    connect();

    return () => {
      wasIntentionallyClosed = true;
      if (socket) {
        socket.close();
      }
      if (reconnectTimeoutId) {
        clearTimeout(reconnectTimeoutId);
      }
    };
  }, [user?.id]);

  const handleLogout = () => {
    logout();
    router.push("/");
  };

  if (!user) {
    return (
      <div className="min-h-screen bg-[#09090b] flex items-center justify-center text-zinc-400 font-mono">
        <div className="flex flex-col items-center gap-3">
          <Activity className="w-8 h-8 text-emerald-500 animate-pulse" />
          <span className="text-xs uppercase tracking-[0.2em] pulse-glow">Loading candidate workspace...</span>
        </div>
      </div>
    );
  }

  // Navigation items
  const navItems = [
    { name: "Overview", href: "/dashboard", icon: Activity },
    { name: "Resumes", href: "/dashboard/resumes", icon: FileText },
    { name: "Preferences & Profile", href: "/dashboard/profile", icon: Settings },
  ];

  return (
    <div className="min-h-screen bg-[#050507] text-[#f4f4f5] font-sans flex flex-col relative overflow-hidden">
      {/* Background glow effects */}
      <div className="absolute inset-0 bg-[linear-gradient(to_right,#0f0f12_1px,transparent_1px),linear-gradient(to_bottom,#0f0f12_1px,transparent_1px)] bg-[size:5rem_5rem] [mask-image:radial-gradient(ellipse_60%_50%_at_50%_50%,#000_70%,transparent_100%)] pointer-events-none" />
      <div className="absolute top-0 right-1/4 w-[600px] h-[300px] bg-[#10b981]/5 rounded-full blur-[120px] pointer-events-none" />
      <div className="absolute bottom-12 left-10 w-[400px] h-[300px] bg-[#10b981]/3 rounded-full blur-[100px] pointer-events-none" />

      {/* Top Navbar */}
      <header className="border-b border-zinc-900 bg-[#07070a]/80 backdrop-blur sticky top-0 z-40 px-6 py-4 flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <Activity className="w-6 h-6 text-emerald-500 animate-pulse" />
            <span className="font-bold text-lg tracking-tight bg-gradient-to-r from-white via-zinc-200 to-zinc-400 bg-clip-text text-transparent">
              AutoApply AI
            </span>
            <span className={`px-2.5 py-0.5 rounded-full text-[9px] font-mono tracking-wider font-semibold border ${
              wsStatus === "connected" 
                ? "bg-emerald-950/40 text-emerald-400 border-emerald-800/40" 
                : wsStatus === "connecting"
                  ? "bg-amber-950/40 text-amber-400 border-amber-800/40 animate-pulse"
                  : "bg-red-950/40 text-red-400 border-red-800/40"
            }`}>
              {wsStatus === "connected" ? "LIVE_SYNC_ON" : wsStatus === "connecting" ? "CONNECTING..." : "OFFLINE_SYNC"}
            </span>
          </div>
        </div>

        {/* Tab Links inside Navbar */}
        <nav className="flex items-center bg-[#0d0d11] p-1 rounded-full border border-zinc-800/80 max-w-md w-full md:w-auto">
          {navItems.map((item) => {
            const isActive = pathname === item.href;
            const Icon = item.icon;
            return (
              <Link
                key={item.href}
                href={item.href}
                className={`flex items-center justify-center gap-2 px-4 py-1.5 rounded-full text-xs font-medium transition-all duration-300 ease-[cubic-bezier(0.32,0.72,0,1)] ${
                  isActive
                    ? "bg-emerald-600 text-white shadow-[0_0_15px_rgba(16,185,129,0.25)]"
                    : "text-zinc-400 hover:text-zinc-200 hover:bg-zinc-900/60"
                }`}
              >
                <Icon className="w-3.5 h-3.5" />
                <span>{item.name}</span>
              </Link>
            );
          })}
        </nav>
        
        <div className="flex items-center justify-end gap-4">
          <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-zinc-950/80 border border-zinc-850 text-sm">
            <UserIcon className="w-4 h-4 text-zinc-500" />
            <span className="font-medium text-zinc-300">{user.full_name}</span>
          </div>
          <button 
            onClick={handleLogout}
            className="p-2 rounded-lg bg-[#0d0d11] hover:bg-zinc-900 border border-zinc-850 text-zinc-500 hover:text-zinc-300 transition-colors"
            title="Logout"
          >
            <LogOut className="w-4 h-4" />
          </button>
        </div>
      </header>

      {/* Main Content Area */}
      <main className="flex-1 w-full max-w-7xl mx-auto px-6 py-8 relative z-10">
        {children}
      </main>
    </div>
  );
}
