"use client";

import React, { useState, useEffect } from "react";
import { useStore } from "@/store/useStore";
import { API_BASE } from "@/config";
import { 
  X, 
  Play, 
  Trash2, 
  RotateCcw, 
  FileText, 
  CheckSquare, 
  Layers, 
  Calendar, 
  ImageIcon, 
  ExternalLink,
  Save,
  CheckCircle,
  HelpCircle,
  Eye
} from "lucide-react";

interface JobDetailsDrawerProps {
  app: any;
  onClose: () => void;
}

export default function JobDetailsDrawer({ app, onClose }: JobDetailsDrawerProps) {
  const { 
    token,
    approveApplication, 
    rejectApplication, 
    updateApplicationAnswers,
    retryApplication,
    addLogLine
  } = useStore();

  const [activeTab, setActiveTab] = useState<"info" | "qa" | "timeline" | "evidence">("info");
  const [evidence, setEvidence] = useState<any[]>([]);
  const [events, setEvents] = useState<any[]>([]);
  const [isLoadingDetails, setIsLoadingDetails] = useState(false);
  const [zoomedImage, setZoomedImage] = useState<string | null>(null);

  // QA and Letter edits
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [coverLetter, setCoverLetter] = useState("");
  const [isSaving, setIsSaving] = useState(false);
  const [saveSuccess, setSaveSuccess] = useState(false);

  // Load events and evidence
  useEffect(() => {
    if (app && token) {
      setIsLoadingDetails(true);
      setAnswers(app.generated_answers || {});
      setCoverLetter(app.cover_letter || "");
      setSaveSuccess(false);

      const fetchEv = fetch(`${API_BASE}/applications/${app.id}/evidence`, {
        headers: { "Authorization": `Bearer ${token}` }
      })
      .then(res => res.json())
      .catch(err => {
        console.error("Failed fetching evidence", err);
        return [];
      });

      const fetchEvs = fetch(`${API_BASE}/applications/${app.id}/events`, {
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
    }
  }, [app, token]);

  const handleSaveAnswers = async () => {
    setIsSaving(true);
    const ok = await updateApplicationAnswers(app.id, {
      generated_answers: answers,
      cover_letter: coverLetter
    });
    setIsSaving(false);
    if (ok) {
      setSaveSuccess(true);
      setTimeout(() => setSaveSuccess(false), 3000);
      addLogLine(`[User] Saved screening QA answers/cover letter updates for app: ${app.id}`);
    }
  };

  const handleApprove = async () => {
    addLogLine(`[User] Approved browser submission for: ${app.job_posting?.company_name}`);
    await handleSaveAnswers(); // save answers before approving
    await approveApplication(app.id);
    onClose();
  };

  const handleReject = async () => {
    addLogLine(`[User] Dismissed application for: ${app.job_posting?.company_name}`);
    await rejectApplication(app.id);
    onClose();
  };

  const handleRetry = async () => {
    addLogLine(`[User] Enqueued manual crawl retry for: ${app.job_posting?.company_name}`);
    await retryApplication(app.id);
    onClose();
  };

  const cleanLabel = (key: string) => {
    const match = key.match(/name=['"]([^'"]+)['"]/);
    if (match) {
      return match[1].replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase());
    }
    return key.replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase());
  };

  const isFailedState = app.status === "FAILED" || app.status === "LIMIT_EXCEEDED" || app.status === "RETRY_PENDING";

  return (
    <div className="fixed inset-0 z-50 flex justify-end font-mono text-xs">
      {/* Background overlay */}
      <div 
        className="fixed inset-0 bg-zinc-950/80 backdrop-blur-sm transition-opacity duration-300"
        onClick={onClose}
      />

      {/* Slide-over panel */}
      <div className="relative w-full max-w-2xl bg-[#09090c] border-l border-zinc-900 h-full flex flex-col shadow-2xl animate-slide-in text-zinc-300">
        
        {/* Panel Header */}
        <div className="p-5 border-b border-zinc-900 flex items-start justify-between bg-zinc-950/60 shrink-0">
          <div className="space-y-1 flex-1 min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <h3 className="text-sm font-bold text-zinc-150 truncate font-sans">
                {app.job_posting?.company_name || app.job_description_parsed?.company_name || "Unknown Company"}
              </h3>
              <span className={`px-2 py-0.5 rounded-full text-[8px] font-bold border uppercase
                ${app.status === "SUBMITTED" ? "bg-emerald-950/30 text-emerald-400 border-emerald-800/40" : ""}
                ${app.status === "PENDING_APPROVAL" ? "bg-amber-950/30 text-amber-400 border-amber-800/40 animate-pulse border-dashed" : ""}
                ${app.status === "REJECTED" ? "bg-red-950/30 text-red-400 border-red-800/40" : ""}
                ${app.status === "INTERVIEW" ? "bg-purple-950/30 text-purple-400 border-purple-800/40" : ""}
                ${app.status === "APPLYING" ? "bg-blue-950/20 text-blue-400 border-blue-800/40 animate-pulse" : ""}
                ${app.status === "DISCOVERED" ? "bg-zinc-900 text-zinc-400 border-zinc-800" : ""}
              `}>
                {app.status}
              </span>
            </div>
            
            <p className="text-[10px] text-zinc-400 font-sans truncate">
              {app.job_posting?.role_title || app.job_description_parsed?.role_title || "Developer Position"}
            </p>
          </div>

          <button 
            onClick={onClose}
            className="p-1.5 rounded-lg bg-zinc-950 border border-zinc-900 text-zinc-500 hover:text-zinc-200 hover:bg-zinc-900/60 transition-all cursor-pointer"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Tab Selector */}
        <div className="flex border-b border-zinc-900 bg-zinc-950/30 px-3 shrink-0">
          {[
            { id: "info", label: "Job Info", icon: Layers },
            { id: "qa", label: "QA & Cover Letter", icon: FileText },
            { id: "timeline", label: "Audit Timeline", icon: Calendar },
            { id: "evidence", label: "Evidence", icon: ImageIcon }
          ].map(tab => {
            const Icon = tab.icon;
            return (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id as any)}
                className={`flex items-center gap-1.5 px-4 py-3 border-b-2 text-[9.5px] uppercase font-bold tracking-wider transition-all cursor-pointer ${
                  activeTab === tab.id 
                    ? "border-emerald-500 text-zinc-100 bg-zinc-900/20" 
                    : "border-transparent text-zinc-500 hover:text-zinc-300"
                }`}
              >
                <Icon className="w-3.5 h-3.5" />
                {tab.label}
              </button>
            );
          })}
        </div>

        {/* Tab Body */}
        <div className="flex-1 overflow-y-auto p-5 space-y-5 scrollbar-thin">
          {isLoadingDetails ? (
            <div className="h-full flex flex-col items-center justify-center gap-3 py-20 text-zinc-500">
              <RotateCcw className="w-5 h-5 animate-spin text-emerald-500" />
              <span>Fetching latest run audit...</span>
            </div>
          ) : (
            <>
              {/* Tab 1: Job Info */}
              {activeTab === "info" && (
                <div className="space-y-5">
                  <div className="p-4 bg-zinc-950 border border-zinc-900 rounded-xl space-y-2.5">
                    <h4 className="font-bold text-[9px] uppercase tracking-wider text-zinc-500">Match Breakdown</h4>
                    <div className="grid grid-cols-2 gap-y-2 text-[10px]">
                      <span className="text-zinc-550">Match rating:</span>
                      <span className="font-bold text-emerald-400">{app.match_score ? Math.round(app.match_score) : 0}%</span>
                      <span className="text-zinc-550">Selected resume:</span>
                      <span className="text-zinc-300 truncate">{app.resume?.resume_name || "Primary Resume"} ({app.resume?.resume_type})</span>
                      <span className="text-zinc-550">Applied Date:</span>
                      <span className="text-zinc-300">
                        {app.submitted_at ? new Date(app.submitted_at).toLocaleString() : (app.created_at ? new Date(app.created_at).toLocaleString() : "—")}
                      </span>
                      {app.last_error && (
                        <>
                          <span className="text-red-500 font-bold">Execution Error:</span>
                          <span className="text-red-400 font-sans leading-normal break-words select-text">{app.last_error}</span>
                        </>
                      )}
                    </div>
                  </div>

                  {app.job_posting?.job_description && (
                    <div className="space-y-1.5">
                      <h4 className="font-bold text-[9px] uppercase tracking-wider text-zinc-500">Job Description</h4>
                      <div className="p-4 bg-zinc-950/60 border border-zinc-900 text-[10px] font-sans rounded-xl leading-relaxed whitespace-pre-wrap max-h-96 overflow-y-auto select-text scrollbar-thin">
                        {app.job_posting.job_description}
                      </div>
                    </div>
                  )}
                </div>
              )}

              {/* Tab 2: QA & Answers */}
              {activeTab === "qa" && (
                <div className="space-y-5">
                  <div className="flex items-center justify-between">
                    <h4 className="font-bold text-[9px] uppercase tracking-wider text-zinc-500">Generated Profile Answers</h4>
                    
                    <button
                      onClick={handleSaveAnswers}
                      disabled={isSaving}
                      className="flex items-center gap-1.5 px-3 py-1 bg-zinc-900 border border-zinc-800 text-zinc-300 hover:text-white hover:bg-zinc-800 rounded-lg text-[9px] font-bold transition-all cursor-pointer"
                    >
                      {saveSuccess ? (
                        <>
                          <CheckCircle className="w-3 h-3 text-emerald-400" />
                          Saved Successfully
                        </>
                      ) : (
                        <>
                          <Save className="w-3 h-3 text-zinc-400" />
                          {isSaving ? "Saving..." : "Save Draft"}
                        </>
                      )}
                    </button>
                  </div>

                  {Object.keys(answers).length > 0 ? (
                    <div className="space-y-4">
                      {Object.entries(answers).map(([key, val]) => (
                        <div key={key} className="space-y-1.5">
                          <label className="block text-[9.5px] text-zinc-550 font-bold">
                            {cleanLabel(key)}
                          </label>
                          {key.includes("textarea") || val.length > 60 ? (
                            <textarea
                              rows={3}
                              value={val}
                              onChange={(e) => setAnswers({ ...answers, [key]: e.target.value })}
                              className="w-full px-3.5 py-2 bg-zinc-950 border border-zinc-900 hover:border-zinc-800 focus:border-emerald-800 rounded-xl text-zinc-200 focus:outline-none font-mono text-[10px] leading-relaxed scrollbar-thin"
                            />
                          ) : (
                            <input
                              type="text"
                              value={val}
                              onChange={(e) => setAnswers({ ...answers, [key]: e.target.value })}
                              className="w-full px-3.5 py-2 bg-zinc-950 border border-zinc-900 hover:border-zinc-800 focus:border-emerald-800 rounded-xl text-zinc-200 focus:outline-none font-mono text-[10px]"
                            />
                          )}
                        </div>
                      ))}
                    </div>
                  ) : (
                    <div className="text-[10px] text-zinc-500 italic p-4 bg-zinc-950 border border-zinc-900 rounded-xl">
                      // No screening questions parsed for this application
                    </div>
                  )}

                  {/* Cover Letter Editor */}
                  <div className="space-y-1.5">
                    <label className="block text-[9.5px] text-zinc-550 font-bold">Personalized Cover Letter</label>
                    <textarea
                      rows={8}
                      value={coverLetter}
                      onChange={(e) => setCoverLetter(e.target.value)}
                      className="w-full px-3.5 py-2 bg-zinc-950 border border-zinc-900 hover:border-zinc-800 focus:border-emerald-800 rounded-xl text-zinc-250 focus:outline-none font-sans text-[10.5px] leading-relaxed scrollbar-thin select-text"
                      placeholder="No cover letter drafted for this application."
                    />
                  </div>
                </div>
              )}

              {/* Tab 3: Audit Timeline */}
              {activeTab === "timeline" && (
                <div className="space-y-4">
                  <h4 className="font-bold text-[9px] uppercase tracking-wider text-zinc-500">Execution Audit Log</h4>
                  {events.length === 0 ? (
                    <div className="text-[10px] text-zinc-500 italic p-4 bg-zinc-950 border border-zinc-900 rounded-xl">
                      // No background worker events logged yet
                    </div>
                  ) : (
                    <div className="border-l border-zinc-900 ml-2 pl-4 space-y-4">
                      {events.map((ev, i) => (
                        <div key={ev.id || i} className="relative">
                          <span className="absolute -left-[21px] top-1.5 w-2 h-2 rounded-full bg-emerald-500 ring-4 ring-[#09090c]" />
                          <div className="text-[10px] font-bold text-zinc-200">{ev.event_type}</div>
                          <div className="text-[8px] text-zinc-500 mt-0.5">
                            {new Date(ev.created_at).toLocaleTimeString()} — {new Date(ev.created_at).toLocaleDateString()}
                          </div>
                          {ev.details && (
                            <pre className="mt-1.5 p-2 bg-[#050508] border border-zinc-900 text-zinc-400 font-mono text-[9px] rounded-lg max-w-full overflow-x-auto leading-relaxed scrollbar-thin select-text">
                              {JSON.stringify(ev.details, null, 2)}
                            </pre>
                          )}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )}

              {/* Tab 4: Evidence */}
              {activeTab === "evidence" && (
                <div className="space-y-5">
                  <h4 className="font-bold text-[9px] uppercase tracking-wider text-zinc-500">Playwright Run Screen Evidence</h4>
                  {evidence.length === 0 ? (
                    <div className="text-[10px] text-zinc-500 italic p-4 bg-zinc-950 border border-zinc-900 rounded-xl">
                      // No confirmation screenshots captured yet
                    </div>
                  ) : (
                    evidence.map((ev, i) => (
                      <div key={ev.id || i} className="space-y-4 bg-zinc-950/40 p-3.5 border border-zinc-900 rounded-xl">
                        
                        {/* Screenshot */}
                        <div className="space-y-1.5">
                          <div className="text-[9px] text-zinc-550 uppercase tracking-widest font-bold">Screenshot Confirmation</div>
                          <div 
                            className="relative border border-zinc-900 rounded-lg overflow-hidden bg-zinc-950 aspect-video cursor-zoom-in group"
                            onClick={() => setZoomedImage(`${API_BASE}/applications/evidence/download?key=${ev.screenshot_path}`)}
                          >
                            <img
                              src={`${API_BASE}/applications/evidence/download?key=${ev.screenshot_path}`}
                              alt="Submission Confirmation Screenshot"
                              className="w-full h-full object-contain group-hover:scale-[1.02] transition-transform duration-300"
                            />
                            <div className="absolute inset-0 bg-black/40 opacity-0 group-hover:opacity-100 flex items-center justify-center transition-all duration-300">
                              <Eye className="w-6 h-6 text-white" />
                            </div>
                          </div>
                        </div>

                        {/* Confirmation text */}
                        {ev.confirmation_text && (
                          <div className="space-y-1.5">
                            <div className="text-[9px] text-zinc-550 uppercase tracking-widest font-bold">Confirmation Text Extracted</div>
                            <div className="p-3 bg-[#040407] border border-zinc-900 text-zinc-400 font-sans text-[10px] rounded-lg leading-relaxed max-h-48 overflow-y-auto whitespace-pre-wrap scrollbar-thin select-text">
                              {ev.confirmation_text}
                            </div>
                          </div>
                        )}
                      </div>
                    ))
                  )}
                </div>
              )}
            </>
          )}
        </div>

        {/* Panel Footer Controls */}
        <div className="p-5 border-t border-zinc-900 bg-zinc-950/60 shrink-0 flex items-center justify-between gap-3">
          
          <div className="flex items-center gap-2">
            {app.status === "PENDING_APPROVAL" && (
              <>
                <button
                  onClick={handleApprove}
                  className="px-4 py-2 bg-emerald-600 hover:bg-emerald-500 text-white font-bold rounded-xl transition-all flex items-center gap-1.5 shadow-[0_0_15px_rgba(16,185,129,0.15)] cursor-pointer"
                >
                  <Play className="w-3.5 h-3.5 fill-current" />
                  Approve & Queue
                </button>
                <button
                  onClick={handleReject}
                  className="px-3.5 py-2 bg-zinc-900 hover:bg-zinc-800 border border-zinc-800 hover:border-red-900/30 text-zinc-400 hover:text-red-400 rounded-xl transition-all flex items-center gap-1.5 cursor-pointer"
                >
                  <Trash2 className="w-3.5 h-3.5" />
                  Dismiss
                </button>
              </>
            )}
            
            {isFailedState && (
              <button
                onClick={handleRetry}
                className="px-4 py-2 bg-zinc-900 hover:bg-zinc-850 border border-zinc-800 hover:border-emerald-900/40 text-emerald-400 rounded-xl transition-all flex items-center gap-1.5 font-bold cursor-pointer"
              >
                <RotateCcw className="w-3.5 h-3.5 text-emerald-500" />
                Retry Submission
              </button>
            )}

            {app.job_posting?.source_url && (
              <a
                href={app.job_posting.source_url}
                target="_blank"
                rel="noreferrer"
                className="px-3.5 py-2 bg-zinc-900 hover:bg-zinc-800 border border-zinc-800 text-zinc-350 hover:text-white rounded-xl transition-all flex items-center gap-1.5"
              >
                <span>Job Link</span>
                <ExternalLink className="w-3.5 h-3.5" />
              </a>
            )}
          </div>

          <button
            onClick={onClose}
            className="px-4 py-2 bg-zinc-950 border border-zinc-850 hover:border-zinc-700 text-zinc-400 hover:text-zinc-200 rounded-xl transition-all cursor-pointer font-bold"
          >
            Close
          </button>
        </div>

      </div>

      {/* Expanded screenshot zoom modal */}
      {zoomedImage && (
        <div 
          className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/95 backdrop-blur-md cursor-zoom-out"
          onClick={() => setZoomedImage(null)}
        >
          <div className="relative max-w-5xl max-h-[90vh]">
            <img 
              src={zoomedImage} 
              alt="Zoomed Evidence Screenshot" 
              className="max-w-full max-h-[85vh] object-contain rounded-lg border border-zinc-850 shadow-2xl"
            />
            <div className="text-center text-zinc-500 font-mono text-[9px] mt-2.5">
              Click anywhere to close zoom overlay
            </div>
          </div>
        </div>
      )}

    </div>
  );
}
