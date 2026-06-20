"use client";

import React, { useState, useEffect } from "react";
import { useStore } from "@/store/useStore";
import { API_BASE } from "@/config";
import { 
  FileText, 
  Upload, 
  Trash2, 
  Check, 
  Clock, 
  Download, 
  AlertCircle,
  FileCheck,
  ChevronRight,
  Briefcase,
  GraduationCap,
  Award,
  Layers,
  Code
} from "lucide-react";

interface Resume {
  id: string;
  resume_name: string;
  resume_type: string;
  file_key: string;
  file_url: string | null;
  file_size_bytes: number;
  original_filename: string;
  parsed_text: string | null;
  parsed_json: any | null;
  skills_extracted: string[];
  is_active: boolean;
  is_primary: boolean;
  upload_at: string;
}

export default function ResumesPage() {
  const { token, addLogLine } = useStore();
  const [resumes, setResumes] = useState<Resume[]>([]);
  const [selectedResume, setSelectedResume] = useState<Resume | null>(null);
  
  // Upload states
  const [file, setFile] = useState<File | null>(null);
  const [resumeName, setResumeName] = useState("");
  const [isPrimary, setIsPrimary] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const [uploadError, setUploadError] = useState("");
  const [uploadSuccess, setUploadSuccess] = useState("");
  const [uploadWarning, setUploadWarning] = useState("");
  
  // Tab control inside detailed view
  const [activeTab, setActiveTab] = useState<"parsed" | "raw" | "json">("parsed");



  const fetchResumes = async () => {
    if (!token) return [];
    try {
      const res = await fetch(`${API_BASE}/resumes`, {
        headers: { "Authorization": `Bearer ${token}` }
      });
      if (res.ok) {
        const data = await res.json();
        setResumes(data);
        // Default select primary or first resume if none selected
        if (data.length > 0 && !selectedResume) {
          const primary = data.find((r: Resume) => r.is_primary) || data[0];
          setSelectedResume(primary);
        }
        return data;
      }
    } catch (e) {
      console.error(e);
    }
    return [];
  };

  useEffect(() => {
    fetchResumes();
  }, [token]);

  const handleUpload = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!file || !resumeName || !token) return;

    setIsUploading(true);
    setUploadError("");
    setUploadSuccess("");
    setUploadWarning("");
    addLogLine(`[ResumeAgent] Uploading and initiating ATS parser workflow for '${resumeName}'...`);

    const formData = new FormData();
    formData.append("file", file);
    formData.append("resume_name", resumeName);
    formData.append("is_primary", String(isPrimary));

    try {
      const res = await fetch(`${API_BASE}/resumes/upload`, {
        method: "POST",
        headers: { "Authorization": `Bearer ${token}` },
        body: formData
      });

      if (res.ok) {
        const data = await res.json();
        
        if (data.warning) {
          setUploadWarning("Resume uploaded. AI analysis is temporarily unavailable. You can continue using the platform.");
          addLogLine(`[ResumeAgent] WARNING: AI parser failed. Stored via deterministic parser.`);
        } else {
          setUploadSuccess("Resume uploaded successfully.");
          addLogLine(`[ResumeAgent] Successfully parsed and bootstrapped profile with type: ${data.resume?.resume_type || "GENERALIST"}`);
        }

        setFile(null);
        setResumeName("");
        setIsPrimary(false);
        
        const freshResumes = await fetchResumes();
        if (data.resume) {
          const matched = freshResumes.find((r: Resume) => r.id === data.resume.id) || data.resume;
          setSelectedResume(matched);
        }
      } else {
        const err = await res.json();
        setUploadError(err.detail || "Failed to process resume.");
        addLogLine(`[ResumeAgent] ERROR: ${err.detail || "Failed parsing PDF content."}`);
      }
    } catch (e) {
      setUploadError("Network error. Backend connection refused.");
      addLogLine("[System] ERROR: Resume parser service endpoint unreachable.");
    } finally {
      setIsUploading(false);
    }
  };

  const handleSetPrimary = async (id: string) => {
    if (!token) return;
    try {
      const res = await fetch(`${API_BASE}/resumes/${id}/set-primary`, {
        method: "PUT",
        headers: { "Authorization": `Bearer ${token}` }
      });
      if (res.ok) {
        addLogLine(`[System] Set resume ID '${id}' as primary selection.`);
        const freshResumes = await fetchResumes();
        // Update selection state using fresh records
        const updated = freshResumes.find((r: Resume) => r.id === id);
        if (updated) {
          setSelectedResume(updated);
        }
      }
    } catch (e) {
      console.error(e);
    }
  };

  const handleDelete = async (id: string, name: string) => {
    if (!token) return;
    if (!confirm(`Are you sure you want to remove resume profile '${name}'?`)) return;

    try {
      const res = await fetch(`${API_BASE}/resumes/${id}`, {
        method: "DELETE",
        headers: { "Authorization": `Bearer ${token}` }
      });
      if (res.ok) {
        addLogLine(`[System] Deleted resume record and vectors for '${name}'.`);
        await fetchResumes();
        if (selectedResume?.id === id) {
          setSelectedResume(null);
        }
      }
    } catch (e) {
      console.error(e);
    }
  };

  const formatBytes = (bytes: number) => {
    if (bytes === 0) return "0 Bytes";
    const k = 1024;
    const sizes = ["Bytes", "KB", "MB"];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + " " + sizes[i];
  };

  const formatDate = (dateStr: string) => {
    return new Date(dateStr).toLocaleDateString("en-IN", {
      day: "2-digit",
      month: "short",
      year: "numeric"
    });
  };

  return (
    <div className="space-y-8 animate-fade-in">
      
      {/* Page Title */}
      <div>
        <h2 className="text-xl font-bold tracking-tight text-zinc-100">Resume Vault</h2>
        <p className="text-xs text-zinc-400 mt-1">Upload and review PDF resumes. The AI analyzes skills, formats, and auto-populates preferences.</p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-12 gap-8">
        
        {/* Left Column: List & Upload Form (col-span-5) */}
        <div className="lg:col-span-5 space-y-6">
          
          {/* Upload Card: Double-Bezel */}
          <div className="p-1.5 rounded-[1.25rem] bg-zinc-900/40 ring-1 ring-zinc-800/80">
            <div className="bg-[#0b0b0f] rounded-[calc(1.25rem-0.375rem)] p-5 shadow-[inset_0_1px_1px_rgba(255,255,255,0.03)]">
              <h3 className="font-semibold text-xs text-zinc-200 uppercase tracking-wider mb-4 flex items-center gap-2">
                <Upload className="w-4 h-4 text-emerald-500" />
                Ingest New Resume
              </h3>

              {uploadSuccess && (
                <div className="mb-4 p-3 bg-emerald-950/20 border border-emerald-900/50 rounded-lg text-emerald-400 text-xs flex items-center gap-2">
                  <Check className="w-4 h-4 shrink-0" />
                  <span>{uploadSuccess}</span>
                </div>
              )}

              {uploadWarning && (
                <div className="mb-4 p-3 bg-amber-950/20 border border-amber-900/50 rounded-lg text-amber-400 text-xs flex items-center gap-2">
                  <AlertCircle className="w-4 h-4 shrink-0" />
                  <span>{uploadWarning}</span>
                </div>
              )}

              {uploadError && (
                <div className="mb-4 p-3 bg-red-950/20 border border-red-900/50 rounded-lg text-red-400 text-xs flex items-center gap-2">
                  <AlertCircle className="w-4 h-4 shrink-0" />
                  <span>{uploadError}</span>
                </div>
              )}

              <form onSubmit={handleUpload} className="space-y-4 text-xs">
                <div>
                  <label className="block text-zinc-400 font-medium mb-1.5">Resume Label</label>
                  <input 
                    type="text"
                    required
                    placeholder="e.g. ML Engineering CV, Fullstack Developer"
                    value={resumeName}
                    onChange={(e) => setResumeName(e.target.value)}
                    className="w-full px-3 py-2 bg-zinc-950 border border-zinc-800 rounded-lg text-zinc-200 placeholder-zinc-600 focus:outline-none focus:border-emerald-500 transition-colors"
                  />
                </div>

                <div>
                  <label className="block text-zinc-400 font-medium mb-1.5">PDF Document</label>
                  <div className="border border-dashed border-zinc-800 hover:border-zinc-700 bg-zinc-950/50 rounded-lg p-5 text-center cursor-pointer transition-colors relative group">
                    <input 
                      type="file"
                      required
                      accept=".pdf"
                      onChange={(e) => setFile(e.target.files?.[0] || null)}
                      className="absolute inset-0 w-full h-full opacity-0 cursor-pointer"
                    />
                    <div className="flex flex-col items-center gap-2">
                      <FileText className="w-8 h-8 text-zinc-600 group-hover:text-emerald-500 transition-colors" />
                      <span className="text-[11px] text-zinc-400 font-medium">
                        {file ? file.name : "Drag & drop PDF here, or click to browse"}
                      </span>
                      <span className="text-[9px] text-zinc-600">PDF documents only (max 10MB)</span>
                    </div>
                  </div>
                </div>

                <div className="flex items-center gap-2.5">
                  <input 
                    type="checkbox"
                    id="is_primary"
                    checked={isPrimary}
                    onChange={(e) => setIsPrimary(e.target.checked)}
                    className="w-3.5 h-3.5 bg-zinc-950 rounded border-zinc-800 text-emerald-600 focus:ring-0 focus:ring-offset-0"
                  />
                  <label htmlFor="is_primary" className="text-zinc-400 select-none">Set as primary application document</label>
                </div>

                <button 
                  type="submit"
                  disabled={isUploading}
                  className="w-full py-2.5 bg-emerald-600 hover:bg-emerald-500 disabled:bg-zinc-800 disabled:text-zinc-500 text-emerald-50 font-bold rounded-lg transition-colors flex items-center justify-center gap-2 shadow-[0_0_15px_rgba(16,185,129,0.15)] cursor-pointer"
                >
                  {isUploading ? "Running LLM Parser workflow..." : "Upload & Analyze PDF"}
                </button>
              </form>
            </div>
          </div>

          {/* Resume List: Double-Bezel */}
          <div className="p-1.5 rounded-[1.25rem] bg-zinc-900/40 ring-1 ring-zinc-800/80">
            <div className="bg-[#0b0b0f] rounded-[calc(1.25rem-0.375rem)] p-5 shadow-[inset_0_1px_1px_rgba(255,255,255,0.03)] space-y-4">
              <h3 className="font-semibold text-xs text-zinc-200 uppercase tracking-wider flex items-center justify-between">
                <span>Stored CV Configurations</span>
                <span className="text-[10px] text-zinc-500 font-mono">({resumes.length})</span>
              </h3>

              <div className="space-y-3">
                {resumes.length === 0 ? (
                  <div className="text-center py-8 text-zinc-600 font-mono text-[10px]">
                    // No resume profiles uploaded
                  </div>
                ) : (
                  resumes.map((resume) => {
                    const isSelected = selectedResume?.id === resume.id;
                    return (
                      <div 
                        key={resume.id}
                        onClick={() => setSelectedResume(resume)}
                        className={`p-3 rounded-lg border transition-all duration-300 cursor-pointer flex items-center justify-between gap-3 ${
                          isSelected 
                            ? "bg-zinc-900/80 border-zinc-700 shadow-sm" 
                            : "bg-zinc-950/30 border-zinc-900 hover:border-zinc-800"
                        }`}
                      >
                        <div className="flex items-center gap-3 min-w-0">
                          <div className={`p-2 rounded ${
                            resume.is_primary ? "bg-emerald-950/40 text-emerald-400" : "bg-zinc-900 text-zinc-500"
                          }`}>
                            <FileText className="w-4 h-4" />
                          </div>
                          <div className="min-w-0">
                            <div className="font-medium text-xs text-zinc-200 truncate flex items-center gap-1.5">
                              {resume.resume_name}
                              {resume.is_primary && (
                                <span className="px-1.5 py-0.5 rounded-full text-[8px] bg-emerald-950/60 text-emerald-400 border border-emerald-800/50 font-bold uppercase tracking-wider">
                                  Primary
                                </span>
                              )}
                            </div>
                            <div className="text-[10px] text-zinc-500 flex items-center gap-2 mt-0.5 font-mono">
                              <span>{resume.resume_type}</span>
                              <span>•</span>
                              <span>{formatBytes(resume.file_size_bytes)}</span>
                            </div>
                          </div>
                        </div>

                        {/* Action buttons */}
                        <div className="flex items-center gap-1.5 shrink-0" onClick={(e) => e.stopPropagation()}>
                          {!resume.is_primary && (
                            <button
                              onClick={() => handleSetPrimary(resume.id)}
                              className="p-1.5 rounded hover:bg-zinc-800 text-zinc-500 hover:text-emerald-400 transition-colors"
                              title="Set as Primary"
                            >
                              <Check className="w-3.5 h-3.5" />
                            </button>
                          )}
                          <button
                            onClick={() => handleDelete(resume.id, resume.resume_name)}
                            className="p-1.5 rounded hover:bg-zinc-800 text-zinc-500 hover:text-red-400 transition-colors"
                            title="Delete Resume"
                          >
                            <Trash2 className="w-3.5 h-3.5" />
                          </button>
                        </div>
                      </div>
                    );
                  })
                )}
              </div>
            </div>
          </div>

        </div>

        {/* Right Column: Parsed Viewer (col-span-7) */}
        <div className="lg:col-span-7">
          
          {selectedResume ? (
            <div className="p-1.5 rounded-[1.25rem] bg-zinc-900/40 ring-1 ring-zinc-800/80">
              <div className="bg-[#0b0b0f] rounded-[calc(1.25rem-0.375rem)] p-6 shadow-[inset_0_1px_1px_rgba(255,255,255,0.03)] space-y-6">
                
                {/* Profile Header */}
                <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-4 border-b border-zinc-900">
                  <div className="flex items-start gap-3.5">
                    <div className="p-3 bg-zinc-900 border border-zinc-800 rounded-xl text-emerald-400">
                      <FileCheck className="w-6 h-6" />
                    </div>
                    <div>
                      <h3 className="font-bold text-sm text-zinc-100">{selectedResume.resume_name}</h3>
                      <p className="text-[10px] text-zinc-500 flex items-center gap-2 mt-1">
                        <span>Original: {selectedResume.original_filename}</span>
                        <span>•</span>
                        <span>Uploaded {formatDate(selectedResume.upload_at)}</span>
                      </p>
                    </div>
                  </div>

                  <a 
                    href={`${API_BASE}/resumes/download-file?key=${selectedResume.file_key}`}
                    download
                    target="_blank"
                    rel="noreferrer"
                    className="py-1.5 px-3 bg-zinc-900 hover:bg-zinc-800 border border-zinc-800 text-zinc-300 font-semibold rounded-lg text-[10px] flex items-center justify-center gap-1.5 transition-colors self-start sm:self-center"
                  >
                    <Download className="w-3.5 h-3.5" />
                    <span>Download PDF</span>
                  </a>
                </div>

                {/* Sub Tab Controls */}
                <div className="flex items-center gap-2 border-b border-zinc-900/60 pb-2">
                  <button
                    onClick={() => setActiveTab("parsed")}
                    className={`px-3 py-1 rounded-md text-[10px] font-bold uppercase tracking-wider transition-colors ${
                      activeTab === "parsed" 
                        ? "bg-zinc-900 text-emerald-400" 
                        : "text-zinc-500 hover:text-zinc-300"
                    }`}
                  >
                    Structured Profile
                  </button>
                  <button
                    onClick={() => setActiveTab("raw")}
                    className={`px-3 py-1 rounded-md text-[10px] font-bold uppercase tracking-wider transition-colors ${
                      activeTab === "raw" 
                        ? "bg-zinc-900 text-emerald-400" 
                        : "text-zinc-500 hover:text-zinc-300"
                    }`}
                  >
                    Raw Document Text
                  </button>
                  <button
                    onClick={() => setActiveTab("json")}
                    className={`px-3 py-1 rounded-md text-[10px] font-bold uppercase tracking-wider transition-colors ${
                      activeTab === "json" 
                        ? "bg-zinc-900 text-emerald-400" 
                        : "text-zinc-500 hover:text-zinc-300"
                    }`}
                  >
                    JSON Payload
                  </button>
                </div>

                {/* Tab Contents */}
                <div className="min-h-[300px]">
                  
                  {activeTab === "parsed" && (
                    <div className="space-y-6 text-xs text-zinc-300">
                      
                      {/* Classification Badge */}
                      <div className="flex items-center gap-2">
                        <span className="text-zinc-500 font-medium">Specialization:</span>
                        <span className="px-2.5 py-0.5 rounded-full bg-emerald-950/40 text-emerald-400 border border-emerald-800/40 font-mono text-[9px] font-bold tracking-wider">
                          {selectedResume.resume_type}
                        </span>
                      </div>

                      {/* Summary Section */}
                      {selectedResume.parsed_json?.summary && (
                        <div className="space-y-2">
                          <h4 className="text-zinc-400 font-semibold uppercase tracking-wider text-[10px] flex items-center gap-1.5">
                            <ChevronRight className="w-3.5 h-3.5 text-emerald-500" />
                            Professional Summary
                          </h4>
                          <p className="leading-relaxed bg-zinc-950/40 border border-zinc-900 p-3.5 rounded-xl text-zinc-300 italic">
                            "{selectedResume.parsed_json.summary}"
                          </p>
                        </div>
                      )}

                      {/* Skills Section */}
                      {((selectedResume.parsed_json?.skills && selectedResume.parsed_json.skills.length > 0) || (selectedResume.skills_extracted && selectedResume.skills_extracted.length > 0)) && (
                        <div className="space-y-2">
                          <h4 className="text-zinc-400 font-semibold uppercase tracking-wider text-[10px] flex items-center gap-1.5">
                            <Layers className="w-3.5 h-3.5 text-emerald-500" />
                            Skills Taxonomy Extracted
                          </h4>
                          <div className="flex flex-wrap gap-1.5 p-3.5 bg-zinc-950/20 border border-zinc-900 rounded-xl">
                            {(selectedResume.parsed_json?.skills || selectedResume.skills_extracted || []).map((skill: string, index: number) => (
                              <span 
                                key={index}
                                className="px-2 py-0.5 bg-zinc-900 text-zinc-300 rounded border border-zinc-800/60 font-mono text-[10px]"
                              >
                                {skill}
                              </span>
                            ))}
                          </div>
                        </div>
                      )}

                      {/* Experience Section */}
                      {(() => {
                        const validExp = selectedResume.parsed_json?.experience?.filter((exp: any) => 
                          exp && exp.company_name && exp.company_name !== "N/A"
                        ) || [];
                        const uniqueExps: any[] = [];
                        const seenExpNames = new Set<string>();
                        for (const exp of validExp) {
                          if (exp?.company_name) {
                            const name = exp.company_name.trim().toUpperCase();
                            if (!seenExpNames.has(name)) {
                              seenExpNames.add(name);
                              uniqueExps.push(exp);
                            }
                          }
                        }
                        if (uniqueExps.length === 0) return null;
                        
                        return (
                          <div className="space-y-3">
                            <h4 className="text-zinc-400 font-semibold uppercase tracking-wider text-[10px] flex items-center gap-1.5">
                              <Briefcase className="w-3.5 h-3.5 text-emerald-500" />
                              Work History
                            </h4>
                            <div className="space-y-3 pl-3.5 border-l border-zinc-900">
                              {uniqueExps.map((exp: any, index: number) => {
                                const startStr = exp.start_year 
                                  ? (exp.start_month ? `${exp.start_month}/${exp.start_year}` : `${exp.start_year}`) 
                                  : (exp.start_date || "N/A");
                                const endStr = exp.is_current 
                                  ? "Present" 
                                  : (exp.end_year ? (exp.end_month ? `${exp.end_month}/${exp.end_year}` : `${exp.end_year}`) : (exp.end_date || "N/A"));
                                
                                return (
                                  <div key={index} className="space-y-1 relative">
                                    <span className="absolute -left-[19px] top-1.5 w-2 h-2 rounded-full bg-emerald-500/80" />
                                    <div className="flex items-center justify-between text-zinc-200">
                                      <span className="font-bold">{exp.role_title}</span>
                                      <span className="text-[10px] text-zinc-500 font-mono">
                                        {startStr} to {endStr}
                                      </span>
                                    </div>
                                    <div className="text-zinc-400 text-[11px]">{exp.company_name}</div>
                                    {exp.description && (
                                      <p className="text-zinc-500 text-[10px] leading-relaxed mt-1 whitespace-pre-wrap">{exp.description}</p>
                                    )}
                                    {exp.skills_used && exp.skills_used.length > 0 && (
                                      <div className="flex flex-wrap gap-1 mt-1.5">
                                        {exp.skills_used.map((sk: string, i: number) => (
                                          <span key={i} className="text-[9px] bg-zinc-900 text-zinc-400 px-1 py-0.5 rounded font-mono border border-zinc-850">{sk}</span>
                                        ))}
                                      </div>
                                    )}
                                  </div>
                                );
                              })}
                            </div>
                          </div>
                        );
                      })()}

                      {/* Projects Section */}
                      {(() => {
                        const validProjs = selectedResume.parsed_json?.projects?.filter((proj: any) => 
                          proj && proj.project_name && proj.project_name !== "N/A" && !proj.project_name.startsWith("•") && !proj.project_name.startsWith("*")
                        ) || [];
                        const uniqueProjs: any[] = [];
                        const seenProjNames = new Set<string>();
                        for (const proj of validProjs) {
                          if (proj?.project_name) {
                            const name = proj.project_name.trim().toUpperCase();
                            if (!seenProjNames.has(name)) {
                              seenProjNames.add(name);
                              uniqueProjs.push(proj);
                            }
                          }
                        }
                        if (uniqueProjs.length === 0) return null;
                        
                        return (
                          <div className="space-y-3">
                            <h4 className="text-zinc-400 font-semibold uppercase tracking-wider text-[10px] flex items-center gap-1.5">
                              <Code className="w-3.5 h-3.5 text-emerald-500" />
                              Personal Projects
                            </h4>
                            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                              {uniqueProjs.map((proj: any, index: number) => (
                                <div key={index} className="bg-zinc-950/40 border border-zinc-900 rounded-xl p-3.5 space-y-2">
                                  <div className="font-bold text-zinc-250 flex items-center justify-between gap-2">
                                    <span>{proj.project_name}</span>
                                    <div className="flex items-center gap-2 shrink-0">
                                      {proj.project_url && proj.project_url !== "N/A" && (
                                        <a href={proj.project_url} target="_blank" rel="noreferrer" className="text-emerald-500 hover:underline text-[9px] font-semibold">Live</a>
                                      )}
                                      {proj.github_url && proj.github_url !== "N/A" && (
                                        <a href={proj.github_url} target="_blank" rel="noreferrer" className="text-emerald-500 hover:underline text-[9px] font-semibold">GitHub</a>
                                      )}
                                    </div>
                                  </div>
                                  {proj.description && (
                                    <p className="text-zinc-500 text-[10px] leading-relaxed whitespace-pre-wrap">{proj.description}</p>
                                  )}
                                  {proj.tech_stack && proj.tech_stack.length > 0 && (
                                    <div className="flex flex-wrap gap-1">
                                      {proj.tech_stack.map((ts: string, i: number) => (
                                        <span key={i} className="text-[9px] bg-zinc-900/60 text-emerald-500 px-1 py-0.5 rounded font-mono">{ts}</span>
                                      ))}
                                    </div>
                                  )}
                                </div>
                              ))}
                            </div>
                          </div>
                        );
                      })()}

                      {/* Education Section */}
                      {(() => {
                        const validEdus = selectedResume.parsed_json?.education?.filter((edu: any) => 
                          edu && edu.institution_name && edu.institution_name !== "N/A"
                        ) || [];
                        if (validEdus.length === 0) return null;
                        
                        return (
                          <div className="space-y-3">
                            <h4 className="text-zinc-400 font-semibold uppercase tracking-wider text-[10px] flex items-center gap-1.5">
                              <GraduationCap className="w-3.5 h-3.5 text-emerald-500" />
                              Academic Qualifications
                            </h4>
                            <div className="space-y-3 pl-3.5 border-l border-zinc-900">
                              {validEdus.map((edu: any, index: number) => {
                                const subStr = edu.degree && edu.degree !== "N/A"
                                  ? (edu.field_of_study && edu.field_of_study !== "N/A" ? `${edu.degree} in ${edu.field_of_study}` : edu.degree)
                                  : (edu.field_of_study || "");
                                  
                                return (
                                  <div key={index} className="space-y-1 relative">
                                    <span className="absolute -left-[19px] top-1.5 w-2 h-2 rounded-full bg-emerald-500/80" />
                                    <div className="flex items-center justify-between text-zinc-250">
                                      <span className="font-semibold">{edu.institution_name}</span>
                                      <span className="text-[10px] text-zinc-500 font-mono">
                                        {edu.start_year || "N/A"} - {edu.end_year || "Present"}
                                      </span>
                                    </div>
                                    {subStr && <div className="text-zinc-400 text-[11px]">{subStr}</div>}
                                    {(edu.cgpa || edu.percentage) && (
                                      <div className="text-[10px] font-mono text-emerald-500 mt-1">
                                        Score: {edu.cgpa ? `CGPA ${edu.cgpa}` : `${edu.percentage}%`}
                                      </div>
                                    )}
                                  </div>
                                );
                              })}
                            </div>
                          </div>
                        );
                      })()}

                      {/* Achievements Section */}
                      {(() => {
                        const validAchs = selectedResume.parsed_json?.achievements?.filter((ach: any) => 
                          ach && ach !== "N/A"
                        ) || [];
                        if (validAchs.length === 0) return null;
                        
                        return (
                          <div className="space-y-2">
                            <h4 className="text-zinc-400 font-semibold uppercase tracking-wider text-[10px] flex items-center gap-1.5">
                              <Award className="w-3.5 h-3.5 text-emerald-500" />
                              Achievements & Awards
                            </h4>
                            <ul className="list-disc list-inside space-y-1.5 pl-2 text-zinc-400">
                              {validAchs.map((ach: string, index: number) => (
                                <li key={index} className="leading-relaxed text-[11px]">{ach}</li>
                              ))}
                            </ul>
                          </div>
                        );
                      })()}

                    </div>
                  )}

                  {activeTab === "raw" && (
                    <div className="p-4 bg-zinc-950 border border-zinc-900 rounded-xl font-mono text-[10px] text-zinc-500 overflow-y-auto max-h-[500px] whitespace-pre-wrap leading-relaxed select-text select-all-btn">
                      {selectedResume.parsed_text || "// No raw text parsed or parsed document was empty."}
                    </div>
                  )}

                  {activeTab === "json" && (
                    <pre className="p-4 bg-zinc-950 border border-zinc-900 rounded-xl font-mono text-[10px] text-emerald-500 overflow-y-auto max-h-[500px] select-text">
                      {JSON.stringify(selectedResume.parsed_json || {}, null, 2)}
                    </pre>
                  )}

                </div>

              </div>
            </div>
          ) : (
            <div className="p-1.5 rounded-[1.25rem] bg-zinc-900/40 ring-1 ring-zinc-800/80 h-full flex items-center justify-center text-center">
              <div className="bg-[#0b0b0f] rounded-[calc(1.25rem-0.375rem)] p-12 shadow-[inset_0_1px_1px_rgba(255,255,255,0.03)] text-zinc-500 font-mono text-[11px] w-full h-full flex flex-col items-center justify-center gap-2">
                <FileText className="w-8 h-8 text-zinc-800" />
                <span>// Select a resume profile to review details</span>
              </div>
            </div>
          )}

        </div>

      </div>
    </div>
  );
}
