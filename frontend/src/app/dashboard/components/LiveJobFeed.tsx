"use client";

import React, { useState, useMemo } from "react";
import { useStore } from "@/store/useStore";
import { Search, Filter, SortAsc, CheckCircle, AlertCircle, Eye, RefreshCw } from "lucide-react";

interface LiveJobFeedProps {
  onSelectApplication: (app: any) => void;
}

export default function LiveJobFeed({ onSelectApplication }: LiveJobFeedProps) {
  const { applications, refreshJobs, addLogLine } = useStore();

  const [searchTerm, setSearchTerm] = useState("");
  const [statusFilter, setStatusFilter] = useState("ALL_ACTIVE");
  const [sourceFilter, setSourceFilter] = useState("ALL");
  const [minScore, setMinScore] = useState(0);
  const [sortBy, setSortBy] = useState("date_desc");
  const [isRefreshing, setIsRefreshing] = useState(false);

  const handleRefresh = async () => {
    setIsRefreshing(true);
    addLogLine("[User] Refreshed job crawlers manually.");
    await refreshJobs();
    setIsRefreshing(false);
  };

  // Filter only matching/discovered/skipped raw logs (the raw stream of crawler findings)
  const feedApplications = useMemo(() => {
    return applications.filter(app => {
      const status = app.status.toUpperCase();
      return (
        status.startsWith("SKIPPED_") || 
        status === "DISCOVERED" || 
        status === "MATCHED" ||
        status === "READY"
      );
    });
  }, [applications]);

  const filteredAndSortedFeed = useMemo(() => {
    let result = [...feedApplications];

    // 1. Search filter
    if (searchTerm.trim()) {
      const term = searchTerm.toLowerCase();
      result = result.filter(app => {
        const company = (app.job_posting?.company_name || "").toLowerCase();
        const role = (app.job_posting?.role_title || "").toLowerCase();
        return company.includes(term) || role.includes(term);
      });
    }

    // 2. Status filter
    if (statusFilter === "ALL_ACTIVE") {
      result = result.filter(app => !app.status.toUpperCase().startsWith("SKIPPED_"));
    } else if (statusFilter === "SKIPPED") {
      result = result.filter(app => app.status.toUpperCase().startsWith("SKIPPED_"));
    } else if (statusFilter !== "ALL") {
      result = result.filter(app => app.status.toUpperCase() === statusFilter);
    }

    // 3. Source filter
    if (sourceFilter !== "ALL") {
      result = result.filter(app => (app.job_posting?.source || "").toUpperCase() === sourceFilter.toUpperCase());
    }

    // 4. Min match score filter
    if (minScore > 0) {
      result = result.filter(app => (app.match_score || 0) >= minScore);
    }

    // 5. Sorting
    result.sort((a, b) => {
      if (sortBy === "score_desc") {
        return (b.match_score || 0) - (a.match_score || 0);
      }
      if (sortBy === "score_asc") {
        return (a.match_score || 0) - (b.match_score || 0);
      }
      if (sortBy === "date_asc") {
        return new Date(a.created_at).getTime() - new Date(b.created_at).getTime();
      }
      // default: date_desc (newest first)
      return new Date(b.created_at).getTime() - new Date(a.created_at).getTime();
    });

    return result;
  }, [feedApplications, searchTerm, statusFilter, sourceFilter, minScore, sortBy]);

  // Unique sources list for filters
  const sources = useMemo(() => {
    const set = new Set<string>();
    feedApplications.forEach(app => {
      if (app.job_posting?.source) {
        set.add(app.job_posting.source);
      }
    });
    return Array.from(set);
  }, [feedApplications]);

  return (
    <div className="p-1.5 rounded-[1.25rem] bg-zinc-900/30 ring-1 ring-zinc-800/50 backdrop-blur-md flex flex-col h-full min-h-[500px]">
      <div className="bg-[#0b0b0f] rounded-[calc(1.25rem-0.375rem)] p-5 shadow-[inset_0_1px_1px_rgba(255,255,255,0.03)] flex flex-col gap-4 flex-1">
        
        {/* Header section */}
        <div className="flex items-center justify-between border-b border-zinc-900 pb-3">
          <div>
            <h3 className="font-semibold text-xs text-zinc-250 uppercase tracking-widest font-mono">
              Live Job Discovery Feed
            </h3>
            <p className="text-[9px] text-zinc-500 font-sans mt-0.5">
              Parsed results from LinkedIn, Naukri, and Greenhouse/Lever/Ashby ATS crawlers
            </p>
          </div>
          
          <button
            onClick={handleRefresh}
            disabled={isRefreshing}
            className="flex items-center gap-1.5 px-2.5 py-1 bg-zinc-950/60 hover:bg-zinc-900 hover:text-zinc-200 text-zinc-400 rounded-lg border border-zinc-850 font-mono text-[9px] transition-all cursor-pointer"
          >
            <RefreshCw className={`w-3 h-3 ${isRefreshing ? "animate-spin text-emerald-400" : ""}`} />
            Scan Now
          </button>
        </div>

        {/* Filters Panel */}
        <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-4 gap-3 bg-[#060609]/40 p-3 rounded-xl border border-zinc-900/80 font-mono text-[10px]">
          {/* Search box */}
          <div className="relative flex items-center">
            <Search className="absolute left-2.5 w-3.5 h-3.5 text-zinc-500" />
            <input
              type="text"
              placeholder="Search role or company..."
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              className="w-full pl-8 pr-3 py-1.5 bg-zinc-950 border border-zinc-900 focus:border-emerald-800 rounded-lg text-zinc-300 focus:outline-none placeholder-zinc-650"
            />
          </div>

          {/* Status filter */}
          <div className="flex items-center gap-1.5">
            <span className="text-zinc-550">Status:</span>
            <select
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value)}
              className="flex-1 px-2.5 py-1.5 bg-zinc-950 border border-zinc-900 hover:border-zinc-800 focus:outline-none rounded-lg text-zinc-300 text-[10px]"
            >
              <option value="ALL">All Found (Inc. Skips)</option>
              <option value="ALL_ACTIVE">Matches (Excl. Skips)</option>
              <option value="DISCOVERED">Discovered Only</option>
              <option value="MATCHED">Matched Only</option>
              <option value="READY">Ready</option>
              <option value="SKIPPED">Skipped (Low Compatibility)</option>
            </select>
          </div>

          {/* Source filter */}
          <div className="flex items-center gap-1.5">
            <span className="text-zinc-550">Source:</span>
            <select
              value={sourceFilter}
              onChange={(e) => setSourceFilter(e.target.value)}
              className="flex-1 px-2.5 py-1.5 bg-zinc-950 border border-zinc-900 hover:border-zinc-800 focus:outline-none rounded-lg text-zinc-300 text-[10px]"
            >
              <option value="ALL">All Sources</option>
              {sources.map(src => (
                <option key={src} value={src.toUpperCase()}>{src}</option>
              ))}
            </select>
          </div>

          {/* Sorting */}
          <div className="flex items-center gap-1.5">
            <span className="text-zinc-550">Sort:</span>
            <select
              value={sortBy}
              onChange={(e) => setSortBy(e.target.value)}
              className="flex-1 px-2.5 py-1.5 bg-zinc-950 border border-zinc-900 hover:border-zinc-800 focus:outline-none rounded-lg text-zinc-300 text-[10px]"
            >
              <option value="date_desc">Newest Discovered</option>
              <option value="date_asc">Oldest Discovered</option>
              <option value="score_desc">Match Score (High-Low)</option>
              <option value="score_asc">Match Score (Low-High)</option>
            </select>
          </div>
        </div>

        {/* Matches statistics bar */}
        <div className="flex justify-between items-center bg-[#07070a] px-3.5 py-2.5 rounded-lg border border-zinc-900 text-[9.5px] font-mono">
          <span className="text-zinc-500">
            Found <strong className="text-zinc-300">{filteredAndSortedFeed.length}</strong> matching feed rows
          </span>
          {minScore > 0 && (
            <span className="text-zinc-500">
              Min Score: <strong className="text-emerald-400">{minScore}%</strong>
            </span>
          )}
          <div className="flex items-center gap-2">
            <span className="text-zinc-550">Score Threshold:</span>
            <input 
              type="range" 
              min="0" 
              max="95" 
              step="5"
              value={minScore} 
              onChange={(e) => setMinScore(Number(e.target.value))}
              className="w-24 h-1 bg-zinc-900 rounded-lg appearance-none cursor-pointer accent-emerald-500" 
            />
          </div>
        </div>

        {/* Job feed listings */}
        <div className="flex-1 overflow-y-auto max-h-[500px] divide-y divide-zinc-900/60 pr-1.5 scrollbar-thin space-y-2">
          {filteredAndSortedFeed.length === 0 ? (
            <div className="py-24 text-center text-zinc-500 font-mono text-[10px] italic">
              // No jobs fit the specified search filter criteria
            </div>
          ) : (
            filteredAndSortedFeed.map((app) => {
              const isSkipped = app.status.toUpperCase().startsWith("SKIPPED_");
              const isMatch = app.status === "MATCHED" || app.status === "READY" || (app.match_score >= 75 && !isSkipped);
              
              return (
                <div 
                  key={app.id} 
                  className="flex items-center justify-between p-3.5 hover:bg-zinc-900/20 rounded-xl border border-transparent hover:border-zinc-900/60 transition-all duration-300 gap-4"
                >
                  <div className="flex-1 min-w-0 space-y-1">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="font-bold text-zinc-200 font-sans text-xs truncate">
                        {app.job_posting?.company_name || "Unknown Company"}
                      </span>
                      <span className="px-1.5 py-0.5 rounded bg-zinc-900 text-zinc-500 text-[8.5px] uppercase tracking-wider font-mono border border-zinc-850 shrink-0">
                        {app.job_posting?.source || "Direct"}
                      </span>
                    </div>

                    <div className="text-[10px] text-zinc-400 font-sans truncate">
                      {app.job_posting?.role_title || "Developer Position"}
                    </div>

                    <div className="flex items-center gap-1.5 text-[9px] text-zinc-500 font-mono flex-wrap">
                      <span>{app.job_posting?.location || "Remote"}</span>
                      <span>•</span>
                      <span>Found {new Date(app.created_at).toLocaleDateString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })}</span>
                    </div>
                  </div>

                  <div className="flex items-center gap-3 shrink-0">
                    {/* Match compatibility rating */}
                    <div className="flex flex-col items-center">
                      <span className={`px-2 py-0.5 rounded-lg font-mono font-bold text-[9.5px] border shadow-sm ${
                        isSkipped 
                          ? "bg-zinc-950 text-zinc-600 border-zinc-900" 
                          : isMatch 
                            ? "bg-emerald-950/20 text-emerald-400 border-emerald-800/40" 
                            : "bg-amber-950/20 text-amber-400 border-amber-800/40"
                      }`}>
                        {app.match_score ? Math.round(app.match_score) : 0}%
                      </span>
                      <span className="text-[7.5px] text-zinc-600 font-mono mt-0.5 uppercase tracking-widest">
                        Fit Score
                      </span>
                    </div>

                    {/* Status Badge */}
                    <span className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[8.5px] font-bold tracking-wider border font-mono uppercase shrink-0
                      ${isSkipped ? "bg-red-950/10 text-red-500/80 border-red-900/30" : ""}
                      ${app.status === "DISCOVERED" ? "bg-zinc-900 text-zinc-400 border-zinc-800" : ""}
                      ${app.status === "MATCHED" ? "bg-zinc-900 text-emerald-400/90 border-zinc-800" : ""}
                      ${app.status === "READY" ? "bg-blue-950/20 text-blue-400 border-blue-800/40 animate-pulse" : ""}
                    `}>
                      {app.status.replace("SKIPPED_", "SKIP_")}
                    </span>

                    {/* Quick view button */}
                    <button
                      onClick={() => onSelectApplication(app)}
                      className="p-1.5 bg-zinc-950/50 hover:bg-zinc-900 border border-zinc-900 hover:border-zinc-800 text-zinc-550 hover:text-zinc-300 rounded-lg transition-all cursor-pointer"
                      title="View Details"
                    >
                      <Eye className="w-3.5 h-3.5" />
                    </button>
                  </div>
                </div>
              );
            })
          )}
        </div>

      </div>
    </div>
  );
}
