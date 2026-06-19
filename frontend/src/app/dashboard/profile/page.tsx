"use client";

import React, { useState, useEffect } from "react";
import { useStore } from "@/store/useStore";
import { API_BASE } from "@/config";
import { 
  User, 
  Sliders, 
  ShieldAlert, 
  BookOpen, 
  Briefcase, 
  Code, 
  Save, 
  Plus, 
  X, 
  CheckCircle, 
  AlertCircle,
  GraduationCap,
  Trophy,
  Trash2,
  Edit,
  Search,
  Sparkles,
  Clock,
  ExternalLink,
  ChevronDown,
  ChevronUp,
  Loader2,
  Globe,
  Settings,
  GitBranch,
  Download,
  Upload,
  Archive,
  FileJson,
  ShieldCheck,
  RotateCcw,
  Database
} from "lucide-react";

// Types
interface Profile {
  linkedin_url: string;
  github_url: string;
  portfolio_url: string;
  address_city: string;
  address_state: string;
  address_country: string;
  years_of_experience: number;
  current_company: string;
  current_role: string;
  current_salary_inr: number;
  profile_summary: string;
}

interface Preferences {
  preferred_roles: string[];
  preferred_locations: string[];
  preferred_companies: string[];
  blacklisted_companies: string[];
  blacklisted_keywords: string[];
  min_salary_inr: number;
  max_salary_inr: number;
  preferred_salary_inr: number;
  min_stipend_inr: number;
  preferred_stipend_inr: number;
  remote_preference: string;
  work_type_preference: string[];
  experience_level: string;
  required_skills: string[];
  min_match_score: number;
  auto_apply_threshold: number;
  max_applications_per_day: number;
  max_applications_per_hour?: number;
  notice_period_days: number;
  work_authorization: string;
  gmail_app_password?: string;
  email_monitoring_enabled?: boolean;
}

interface Education {
  id?: string;
  institution_name: string;
  degree: string;
  field_of_study: string;
  cgpa?: number;
  percentage?: number;
  start_year?: number;
  end_year?: number;
  is_current: boolean;
  education_type: string;
}

interface Experience {
  id?: string;
  company_name: string;
  role_title: string;
  employment_type: string;
  location: string;
  start_date?: string;
  end_date?: string;
  is_current: boolean;
  description: string;
  skills_used: string[];
}

interface Project {
  id?: string;
  project_name: string;
  description: string;
  tech_stack: string[];
  project_url: string;
  github_url: string;
}

interface Skill {
  id: string;
  skill_name: string;
  category?: string | null;
  proficiency_level?: string | null;
  is_primary: boolean;
}

interface Achievement {
  id?: string;
  achievement_type: string;
  title: string;
  issuer?: string;
  date_achieved?: string;
  description?: string;
  url?: string;
}

// 9 Official Skill Categories
const SKILLS_CATEGORIES = [
  "Programming Languages",
  "Frameworks & Libraries",
  "Databases",
  "Cloud & DevOps",
  "AI / Machine Learning",
  "Blockchain & Web3",
  "Embedded Systems",
  "Core Computer Science",
  "Other Technologies"
];

const DB_TO_UI_CATEGORY_MAP: Record<string, string> = {
  "Programming Languages": "Programming Languages",
  "Frameworks": "Frameworks & Libraries",
  "Databases": "Databases",
  "Cloud": "Cloud & DevOps",
  "AI/ML": "AI / Machine Learning",
  "Blockchain": "Blockchain & Web3",
  "Embedded Systems": "Embedded Systems",
  "Core CS": "Core Computer Science",
  "Other": "Other Technologies"
};

const UI_TO_DB_CATEGORY_MAP: Record<string, string> = {
  "Programming Languages": "Programming Languages",
  "Frameworks & Libraries": "Frameworks",
  "Databases": "Databases",
  "Cloud & DevOps": "Cloud",
  "AI / Machine Learning": "AI/ML",
  "Blockchain & Web3": "Blockchain",
  "Embedded Systems": "Embedded Systems",
  "Core Computer Science": "Core CS",
  "Other Technologies": "Other"
};

const normalizeSkillCategory = (cat: string): string => {
  const norm = cat ? cat.trim() : "";
  if (UI_TO_DB_CATEGORY_MAP[norm]) return norm;
  if (DB_TO_UI_CATEGORY_MAP[norm]) return DB_TO_UI_CATEGORY_MAP[norm];
  
  const c = norm.toLowerCase();
  if (c.includes("language") || c === "languages" || c === "programming") return "Programming Languages";
  if (c.includes("framework") || c === "frameworks" || c === "libraries" || c === "library") return "Frameworks & Libraries";
  if (c.includes("database") || c === "databases" || c === "sql" || c === "nosql") return "Databases";
  if (c.includes("cloud") || c.includes("devops") || c === "infrastructure" || c === "ci/cd" || c === "ci") return "Cloud & DevOps";
  if (c.includes("ai") || c.includes("machine learning") || c.includes("ml") || c === "deep learning" || c === "data science") return "AI / Machine Learning";
  if (c.includes("blockchain") || c === "web3" || c === "solidity" || c === "ethereum" || c === "crypto") return "Blockchain & Web3";
  if (c.includes("embed") || c === "iot" || c === "firmware" || c === "hardware") return "Embedded Systems";
  if (c.includes("core cs") || c === "computer science" || c.includes("structure") || c.includes("algorithm") || c === "dbms" || c === "oop" || c === "operating systems") return "Core Computer Science";
  return "Other Technologies";
};

export default function ProfilePage() {
  const { token, addLogLine } = useStore();
  const [activeTab, setActiveTab] = useState<"general" | "matching" | "blacklists" | "education" | "experience" | "projects" | "skills" | "achievements">("general");
  
  // Status states
  const [statusMessage, setStatusMessage] = useState("");
  const [statusType, setStatusType] = useState<"success" | "error" | "">("");

  // Loading States
  const [isLoading, setIsLoading] = useState(true);
  const [isSaving, setIsSaving] = useState(false);
  const [lastUpdated, setLastUpdated] = useState<string>("");

  // Search filter query
  const [searchQuery, setSearchQuery] = useState("");

  // ── Backup / Restore State ──────────────────────────────────────────────────
  const [isExporting, setIsExporting] = useState(false);
  const [isExportingZip, setIsExportingZip] = useState(false);
  const [isRestoring, setIsRestoring] = useState(false);
  const [backupPreview, setBackupPreview] = useState<any>(null);
  const [backupFile, setBackupFile] = useState<File | null>(null);
  const [showRestoreModal, setShowRestoreModal] = useState(false);
  const [isPreviewing, setIsPreviewing] = useState(false);
  const [showBackupMenu, setShowBackupMenu] = useState(false);
  // ────────────────────────────────────────────────────────────────────────────

  // Core Data States
  const [profile, setProfile] = useState<Profile>({
    linkedin_url: "",
    github_url: "",
    portfolio_url: "",
    address_city: "",
    address_state: "",
    address_country: "India",
    years_of_experience: 0,
    current_company: "",
    current_role: "",
    current_salary_inr: 0,
    profile_summary: ""
  });

  const [preferences, setPreferences] = useState<Preferences>({
    preferred_roles: [],
    preferred_locations: [],
    preferred_companies: [],
    blacklisted_companies: [],
    blacklisted_keywords: [],
    min_salary_inr: 0,
    max_salary_inr: 0,
    preferred_salary_inr: 0,
    min_stipend_inr: 0,
    preferred_stipend_inr: 0,
    remote_preference: "HYBRID",
    work_type_preference: ["FULL_TIME"],
    experience_level: "FRESHER",
    required_skills: [],
    min_match_score: 60,
    auto_apply_threshold: 75,
    max_applications_per_day: 20,
    max_applications_per_hour: 10,
    notice_period_days: 0,
    work_authorization: "INDIA_CITIZEN",
    gmail_app_password: "",
    email_monitoring_enabled: false
  });

  // Sub-items lists
  const [educationList, setEducationList] = useState<Education[]>([]);
  const [experienceList, setExperienceList] = useState<Experience[]>([]);
  const [projectsList, setProjectsList] = useState<Project[]>([]);
  const [skillsList, setSkillsList] = useState<Skill[]>([]);
  const [achievementsList, setAchievementsList] = useState<Achievement[]>([]);

  // Form toggles and inputs for Sub-items addition
  const [showEduForm, setShowEduForm] = useState(false);
  const [newEdu, setNewEdu] = useState<Education>({
    institution_name: "",
    degree: "",
    field_of_study: "",
    cgpa: undefined,
    start_year: undefined,
    end_year: undefined,
    is_current: false,
    education_type: "BTECH"
  });
  const [newEduLoc, setNewEduLoc] = useState(""); // Location field for Education

  const [showExpForm, setShowExpForm] = useState(false);
  const [newExp, setNewExp] = useState<Experience>({
    company_name: "",
    role_title: "",
    employment_type: "FULL_TIME",
    location: "",
    is_current: false,
    description: "",
    skills_used: []
  });
  const [expSkillInput, setExpSkillInput] = useState("");

  const [showProjForm, setShowProjForm] = useState(false);
  const [newProj, setNewProj] = useState<Project>({
    project_name: "",
    description: "",
    tech_stack: [],
    project_url: "",
    github_url: ""
  });
  const [projStackInput, setProjStackInput] = useState("");

  const [newSkillName, setNewSkillName] = useState("");
  const [newSkillCategory, setNewSkillCategory] = useState("Programming Languages");
  const [newSkillProficiency, setNewSkillProficiency] = useState("INTERMEDIATE");
  const [newSkillIsPrimary, setNewSkillIsPrimary] = useState(false);

  const [showAchForm, setShowAchForm] = useState(false);
  const [newAch, setNewAch] = useState<Achievement>({
    title: "",
    description: "",
    achievement_type: "AWARD",
    issuer: "",
    date_achieved: "", // format as YYYY-MM-DD
    url: ""
  });
  const [newAchYear, setNewAchYear] = useState(""); // Year helper

  // Overlay Modals Editing State
  const [editType, setEditType] = useState<"education" | "experience" | "project" | "skill" | "achievement" | null>(null);
  const [editItem, setEditItem] = useState<any>(null);
  
  // Custom states for split institution/location in Education Edit modal
  const [editEduInst, setEditEduInst] = useState("");
  const [editEduLoc, setEditEduLoc] = useState("");
  const [editProjStack, setEditProjStack] = useState("");
  const [editExpSkills, setEditExpSkills] = useState("");
  const [editAchYear, setEditAchYear] = useState("");

  // Delete Confirmation Dialog State
  const [deleteConfirmType, setDeleteConfirmType] = useState<"education" | "experience" | "project" | "skill" | "achievement" | null>(null);
  const [deleteConfirmItem, setDeleteConfirmItem] = useState<any>(null);

  // Tag inputs for arrays in Preferences
  const [roleInput, setRoleInput] = useState("");
  const [locInput, setLocInput] = useState("");
  const [companyInput, setCompanyInput] = useState("");
  const [blacklistCompanyInput, setBlacklistCompanyInput] = useState("");
  const [blacklistKeywordInput, setBlacklistKeywordInput] = useState("");
  const [reqSkillInput, setReqSkillInput] = useState("");

  // ── Backup Handlers ─────────────────────────────────────────────────────────

  /** Download full JSON backup */
  const handleDownloadBackup = async () => {
    if (!token) return;
    setIsExporting(true);
    try {
      const res = await fetch(`${API_BASE}/backup/export`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const blob = await res.blob();
      const now = new Date();
      const stamp = `${now.getFullYear()}_${String(now.getMonth() + 1).padStart(2, "0")}_${String(now.getDate()).padStart(2, "0")}`;
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `autoapply_profile_backup_${stamp}.json`;
      a.click();
      URL.revokeObjectURL(url);
      flashMessage("Backup downloaded successfully.", "success");
      addLogLine("[Backup] Full profile backup exported.");
    } catch (e: any) {
      flashMessage(`Export failed: ${e.message}`, "error");
    } finally {
      setIsExporting(false);
      setShowBackupMenu(false);
    }
  };

  /** Download ZIP package (JSON + PDFs) */
  const handleDownloadZip = async () => {
    if (!token) return;
    setIsExportingZip(true);
    try {
      const res = await fetch(`${API_BASE}/backup/export-zip`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const blob = await res.blob();
      const now = new Date();
      const stamp = `${now.getFullYear()}_${String(now.getMonth() + 1).padStart(2, "0")}_${String(now.getDate()).padStart(2, "0")}`;
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `autoapply_full_export_${stamp}.zip`;
      a.click();
      URL.revokeObjectURL(url);
      flashMessage("ZIP package downloaded.", "success");
      addLogLine("[Backup] Full ZIP export (JSON + PDFs) downloaded.");
    } catch (e: any) {
      flashMessage(`ZIP export failed: ${e.message}`, "error");
    } finally {
      setIsExportingZip(false);
      setShowBackupMenu(false);
    }
  };

  /** File picker → preview */
  const handleSelectRestoreFile = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file || !token) return;
    if (!file.name.endsWith(".json")) {
      flashMessage("Only .json backup files are accepted.", "error");
      return;
    }
    setBackupFile(file);
    setIsPreviewing(true);
    try {
      const fd = new FormData();
      fd.append("file", file);
      const res = await fetch(`${API_BASE}/backup/preview`, {
        method: "POST",
        headers: { Authorization: `Bearer ${token}` },
        body: fd,
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
      setBackupPreview(data);
      setShowRestoreModal(true);
    } catch (e: any) {
      flashMessage(`Preview failed: ${e.message}`, "error");
      setBackupFile(null);
    } finally {
      setIsPreviewing(false);
    }
  };

  /** Perform the actual merge-restore */
  const handleConfirmRestore = async () => {
    if (!token || !backupFile) return;
    setIsRestoring(true);
    try {
      const fd = new FormData();
      fd.append("file", backupFile);
      const res = await fetch(`${API_BASE}/backup/restore`, {
        method: "POST",
        headers: { Authorization: `Bearer ${token}` },
        body: fd,
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
      const s = data.stats || {};
      const inserted = (s.education_inserted || 0) + (s.experience_inserted || 0) +
        (s.projects_inserted || 0) + (s.skills_inserted || 0) + (s.achievements_inserted || 0);
      flashMessage(`Restore complete — ${inserted} new records merged.`, "success");
      addLogLine(`[Backup] Profile restored: ${inserted} records merged (no data deleted).`);
      setShowRestoreModal(false);
      setBackupPreview(null);
      setBackupFile(null);
      setLastUpdated(new Date().toLocaleTimeString());
      // Re-load all profile data to reflect restored records
      await loadProfileData();
    } catch (e: any) {
      flashMessage(`Restore failed: ${e.message}`, "error");
    } finally {
      setIsRestoring(false);
    }
  };
  // ────────────────────────────────────────────────────────────────────────────

  // Load all user profile configurations
  const loadProfileData = async () => {
    if (!token) return;
    setIsLoading(true);
    try {
      // 1. General Profile details
      const profRes = await fetch(`${API_BASE}/profile`, {
        headers: { "Authorization": `Bearer ${token}` }
      });
      if (profRes.ok) {
        const data = await profRes.json();
        setProfile({
          linkedin_url: data.linkedin_url || "",
          github_url: data.github_url || "",
          portfolio_url: data.portfolio_url || "",
          address_city: data.address_city || "",
          address_state: data.address_state || "",
          address_country: data.address_country || "India",
          years_of_experience: data.years_of_experience || 0,
          current_company: data.current_company || "",
          current_role: data.current_role || "",
          current_salary_inr: data.current_salary_inr || 0,
          profile_summary: data.profile_summary || ""
        });
      }

      // 2. Preferences
      const prefRes = await fetch(`${API_BASE}/profile/preferences`, {
        headers: { "Authorization": `Bearer ${token}` }
      });
      if (prefRes.ok) {
        setPreferences(await prefRes.json());
      }

      // 3. Sub-lists
      const eduRes = await fetch(`${API_BASE}/profile/education`, {
        headers: { "Authorization": `Bearer ${token}` }
      });
      if (eduRes.ok) setEducationList(await eduRes.json());

      const expRes = await fetch(`${API_BASE}/profile/experience`, {
        headers: { "Authorization": `Bearer ${token}` }
      });
      if (expRes.ok) setExperienceList(await expRes.json());

      const projRes = await fetch(`${API_BASE}/profile/projects`, {
        headers: { "Authorization": `Bearer ${token}` }
      });
      if (projRes.ok) setProjectsList(await projRes.json());

      const skillRes = await fetch(`${API_BASE}/profile/skills`, {
        headers: { "Authorization": `Bearer ${token}` }
      });
      if (skillRes.ok) setSkillsList(await skillRes.json());

      const achRes = await fetch(`${API_BASE}/profile/achievements`, {
        headers: { "Authorization": `Bearer ${token}` }
      });
      if (achRes.ok) setAchievementsList(await achRes.json());

      setLastUpdated(new Date().toLocaleTimeString());
    } catch (e) {
      console.error("Failed loading profile details:", e);
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    loadProfileData();
  }, [token]);

  const flashMessage = (message: string, type: "success" | "error") => {
    setStatusMessage(message);
    setStatusType(type);
    setTimeout(() => {
      setStatusMessage("");
      setStatusType("");
    }, 4000);
  };

  // Save General profile API
  const handleSaveProfile = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!token) return;
    setIsSaving(true);
    try {
      const res = await fetch(`${API_BASE}/profile`, {
        method: "PUT",
        headers: {
          "Authorization": `Bearer ${token}`,
          "Content-Type": "application/json"
        },
        body: JSON.stringify(profile)
      });
      if (res.ok) {
        const updated = await res.json();
        setProfile(updated);
        flashMessage("General profile updated successfully.", "success");
        addLogLine("[System] Successfully updated general candidate profile fields.");
        setLastUpdated(new Date().toLocaleTimeString());
      } else {
        flashMessage("Failed saving profile details.", "error");
      }
    } catch (e) {
      flashMessage("Connection failed.", "error");
    } finally {
      setIsSaving(false);
    }
  };

  // Save Preferences API
  const handleSavePreferences = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!token) return;
    setIsSaving(true);
    try {
      const res = await fetch(`${API_BASE}/profile/preferences`, {
        method: "PUT",
        headers: {
          "Authorization": `Bearer ${token}`,
          "Content-Type": "application/json"
        },
        body: JSON.stringify(preferences)
      });
      if (res.ok) {
        setPreferences(await res.json());
        flashMessage("Matching preferences saved successfully.", "success");
        addLogLine("[System] Candidate match weights and apply preferences saved.");
        setLastUpdated(new Date().toLocaleTimeString());
      } else {
        flashMessage("Failed saving preference configurations.", "error");
      }
    } catch (e) {
      flashMessage("Connection failed.", "error");
    } finally {
      setIsSaving(false);
    }
  };

  // Add Education
  const handleAddEducation = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!token) return;
    setIsSaving(true);
    const combinedInst = newEduLoc.trim()
      ? `${newEdu.institution_name.trim()} | ${newEduLoc.trim()}`
      : newEdu.institution_name.trim();

    try {
      const res = await fetch(`${API_BASE}/profile/education`, {
        method: "POST",
        headers: {
          "Authorization": `Bearer ${token}`,
          "Content-Type": "application/json"
        },
        body: JSON.stringify({ ...newEdu, institution_name: combinedInst })
      });
      if (res.ok) {
        const added = await res.json();
        setEducationList([...educationList, added]);
        setShowEduForm(false);
        setNewEdu({
          institution_name: "",
          degree: "",
          field_of_study: "",
          cgpa: undefined,
          start_year: undefined,
          end_year: undefined,
          is_current: false,
          education_type: "BTECH"
        });
        setNewEduLoc("");
        flashMessage("Academic record added.", "success");
        addLogLine(`[System] Added education entry at: ${added.institution_name}`);
        setLastUpdated(new Date().toLocaleTimeString());
      } else {
        flashMessage("Failed adding academic record.", "error");
      }
    } catch (e) {
      flashMessage("Connection failed.", "error");
    } finally {
      setIsSaving(false);
    }
  };

  // Add Experience
  const handleAddExperience = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!token) return;
    setIsSaving(true);
    try {
      const res = await fetch(`${API_BASE}/profile/experience`, {
        method: "POST",
        headers: {
          "Authorization": `Bearer ${token}`,
          "Content-Type": "application/json"
        },
        body: JSON.stringify(newExp)
      });
      if (res.ok) {
        const added = await res.json();
        setExperienceList([...experienceList, added]);
        setShowExpForm(false);
        setNewExp({
          company_name: "",
          role_title: "",
          employment_type: "FULL_TIME",
          location: "",
          is_current: false,
          description: "",
          skills_used: []
        });
        flashMessage("Experience record added.", "success");
        addLogLine(`[System] Registered experience record at: ${added.company_name}`);
        setLastUpdated(new Date().toLocaleTimeString());
      } else {
        flashMessage("Failed adding experience.", "error");
      }
    } catch (e) {
      flashMessage("Connection failed.", "error");
    } finally {
      setIsSaving(false);
    }
  };

  // Add Project
  const handleAddProject = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!token) return;
    setIsSaving(true);
    try {
      const res = await fetch(`${API_BASE}/profile/projects`, {
        method: "POST",
        headers: {
          "Authorization": `Bearer ${token}`,
          "Content-Type": "application/json"
        },
        body: JSON.stringify(newProj)
      });
      if (res.ok) {
        const added = await res.json();
        setProjectsList([...projectsList, added]);
        setShowProjForm(false);
        setNewProj({
          project_name: "",
          description: "",
          tech_stack: [],
          project_url: "",
          github_url: ""
        });
        flashMessage("Project record added.", "success");
        addLogLine(`[System] Logged project CV details for: ${added.project_name}`);
        setLastUpdated(new Date().toLocaleTimeString());
      } else {
        flashMessage("Failed adding project.", "error");
      }
    } catch (e) {
      flashMessage("Connection failed.", "error");
    } finally {
      setIsSaving(false);
    }
  };

  // Add Skill
  const handleAddSkill = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newSkillName.trim() || !token) return;
    
    // Prevent duplicate skill locally before sending
    const normalizedNewName = newSkillName.trim().toLowerCase();
    if (skillsList.some(s => s.skill_name.toLowerCase() === normalizedNewName)) {
      flashMessage("Skill already exists in your registry.", "error");
      return;
    }

    setIsSaving(true);
    try {
      const res = await fetch(`${API_BASE}/profile/skills`, {
        method: "POST",
        headers: {
          "Authorization": `Bearer ${token}`,
          "Content-Type": "application/json"
        },
        body: JSON.stringify({
          skill_name: newSkillName.trim(),
          category: newSkillCategory,
          proficiency_level: newSkillProficiency,
          is_primary: newSkillIsPrimary
        })
      });
      if (res.ok) {
        const added = await res.json();
        setSkillsList([...skillsList, added]);
        setNewSkillName("");
        flashMessage("Skill taxonomy registered.", "success");
        addLogLine(`[System] Synced skill taxonomy keyword: ${added.skill_name}`);
        setLastUpdated(new Date().toLocaleTimeString());
      } else {
        const err = await res.json();
        flashMessage(err.detail || "Failed adding skill.", "error");
      }
    } catch (e) {
      flashMessage("Connection failed.", "error");
    } finally {
      setIsSaving(false);
    }
  };

  // Add Achievement
  const handleAddAchievement = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!token) return;
    setIsSaving(true);
    const dateStr = newAchYear ? `${newAchYear}-01-01` : undefined;

    try {
      const res = await fetch(`${API_BASE}/profile/achievements`, {
        method: "POST",
        headers: {
          "Authorization": `Bearer ${token}`,
          "Content-Type": "application/json"
        },
        body: JSON.stringify({ ...newAch, date_achieved: dateStr })
      });
      if (res.ok) {
        const added = await res.json();
        setAchievementsList([...achievementsList, added]);
        setShowAchForm(false);
        setNewAch({
          title: "",
          description: "",
          achievement_type: "AWARD",
          issuer: "",
          date_achieved: "",
          url: ""
        });
        setNewAchYear("");
        flashMessage("Achievement record added.", "success");
        addLogLine(`[System] Registered achievement: ${added.title}`);
        setLastUpdated(new Date().toLocaleTimeString());
      } else {
        flashMessage("Failed adding achievement.", "error");
      }
    } catch (e) {
      flashMessage("Connection failed.", "error");
    } finally {
      setIsSaving(false);
    }
  };

  // Open Edit Modal
  const openEditModal = (type: "education" | "experience" | "project" | "skill" | "achievement", item: any) => {
    setEditType(type);
    setEditItem({ ...item });
    if (type === "education") {
      const parts = (item.institution_name || "").split(" | ");
      setEditEduInst(parts[0] || "");
      setEditEduLoc(parts[1] || "");
    } else if (type === "project") {
      setEditProjStack((item.tech_stack || []).join(", "));
    } else if (type === "experience") {
      setEditExpSkills((item.skills_used || []).join(", "));
    } else if (type === "achievement") {
      const year = item.date_achieved ? new Date(item.date_achieved).getFullYear().toString() : "";
      setEditAchYear(year);
    }
  };

  // Save Edit Action
  const handleSaveEdit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!token || !editType || !editItem) return;

    setIsSaving(true);

    // Strip server-managed fields so Pydantic only receives editable fields.
    // Sending id/user_id/created_at/source can cause validation errors or
    // unexpected 500s from FastAPI's request body parsing middleware.
    const SERVER_FIELDS = new Set(["id", "user_id", "created_at", "updated_at", "source"]);
    const stripped: Record<string, any> = {};
    for (const [k, v] of Object.entries(editItem)) {
      if (!SERVER_FIELDS.has(k)) stripped[k] = v;
    }
    let payload = { ...stripped };

    if (editType === "education") {
      const combined = editEduLoc.trim() 
        ? `${editEduInst.trim()} | ${editEduLoc.trim()}` 
        : editEduInst.trim();
      payload.institution_name = combined;
    } else if (editType === "project") {
      payload.tech_stack = editProjStack.split(",").map(t => t.trim()).filter(Boolean);
    } else if (editType === "experience") {
      payload.skills_used = editExpSkills.split(",").map(s => s.trim()).filter(Boolean);
    } else if (editType === "achievement") {
      payload.date_achieved = editAchYear ? `${editAchYear}-01-01` : null;
    }

    // Map singular editType -> plural API path segment
    const apiSegment: Record<string, string> = {
      education: "education",
      experience: "experience",
      project: "projects",
      skill: "skills",
      achievement: "achievements",
    };
    const segment = apiSegment[editType] ?? editType;
    const url = `${API_BASE}/profile/${segment}/${editItem.id}`;

    console.log("[ProfileEdit] Saving:", { editType, segment, url, payload });

    try {
      const res = await fetch(url, {
        method: "PUT",
        headers: {
          "Authorization": `Bearer ${token}`,
          "Content-Type": "application/json"
        },
        body: JSON.stringify(payload)
      });

      console.log("[ProfileEdit] Response status:", res.status);

      if (res.ok) {
        const updated = await res.json();
        console.log("[ProfileEdit] Success:", updated);
        if (editType === "education") {
          setEducationList(educationList.map(x => x.id === editItem.id ? updated : x));
        } else if (editType === "experience") {
          setExperienceList(experienceList.map(x => x.id === editItem.id ? updated : x));
        } else if (editType === "project") {
          setProjectsList(projectsList.map(x => x.id === editItem.id ? updated : x));
        } else if (editType === "skill") {
          setSkillsList(skillsList.map(x => x.id === editItem.id ? updated : x));
        } else if (editType === "achievement") {
          setAchievementsList(achievementsList.map(x => x.id === editItem.id ? updated : x));
        }

        flashMessage("Updated record successfully.", "success");
        addLogLine(`[System] Edited ${editType} registry details.`);
        setEditType(null);
        setEditItem(null);
        setLastUpdated(new Date().toLocaleTimeString());
      } else {
        // Always read raw text first — res.json() on a non-JSON 500 body silently
        // returns {} after catching the parse error, hiding the real failure.
        const rawText = await res.text();
        console.error("[ProfileEdit] FAILED ───────────────────────────");
        console.error("[ProfileEdit] Status    :", res.status, res.statusText);
        console.error("[ProfileEdit] URL       :", url);
        console.error("[ProfileEdit] Payload   :", JSON.stringify(payload, null, 2));
        console.error("[ProfileEdit] Raw body  :", rawText);

        let detail = `Save failed (HTTP ${res.status})`;
        try {
          const errBody = JSON.parse(rawText);
          console.error("[ProfileEdit] Parsed err:", errBody);
          if (errBody?.detail) {
            if (typeof errBody.detail === "string") {
              detail = errBody.detail;
            } else if (Array.isArray(errBody.detail)) {
              // Pydantic v2 returns an array of validation error objects
              detail = errBody.detail
                .map((e: any) => `${(e.loc || []).slice(1).join(".")}: ${e.msg}`)
                .join(" | ");
            } else {
              detail = JSON.stringify(errBody.detail);
            }
          }
        } catch {
          // Response was not JSON (e.g. raw 500 HTML traceback)
          console.error("[ProfileEdit] Body is not JSON – see Raw body above");
          detail = `Server error (${res.status}): check backend logs`;
        }
        flashMessage(detail, "error");
      }
    } catch (e) {
      console.error("[ProfileEdit] Network error:", e);
      flashMessage("Connection error – is the backend running?", "error");
    } finally {
      setIsSaving(false);
    }
  };

  // Trigger Delete confirmation
  const triggerDelete = (type: "education" | "experience" | "project" | "skill" | "achievement", item: any) => {
    setDeleteConfirmType(type);
    setDeleteConfirmItem(item);
  };

  // Perform delete after confirmation
  const handleConfirmDelete = async () => {
    if (!token || !deleteConfirmType || !deleteConfirmItem) return;
    setIsSaving(true);

    // Map singular deleteConfirmType -> plural API segment
    const apiSegment: Record<string, string> = {
      education: "education",
      experience: "experience",
      project: "projects",
      skill: "skills",
      achievement: "achievements",
    };
    const segment = apiSegment[deleteConfirmType] ?? deleteConfirmType;
    const url = `${API_BASE}/profile/${segment}/${deleteConfirmItem.id}`;

    console.log("[ProfileDelete] Deleting:", { deleteConfirmType, segment, url });

    try {
      const res = await fetch(url, {
        method: "DELETE",
        headers: { "Authorization": `Bearer ${token}` }
      });
      if (res.ok || res.status === 204) {
        if (deleteConfirmType === "education") {
          setEducationList(educationList.filter(x => x.id !== deleteConfirmItem.id));
        } else if (deleteConfirmType === "experience") {
          setExperienceList(experienceList.filter(x => x.id !== deleteConfirmItem.id));
        } else if (deleteConfirmType === "project") {
          setProjectsList(projectsList.filter(x => x.id !== deleteConfirmItem.id));
        } else if (deleteConfirmType === "skill") {
          setSkillsList(skillsList.filter(x => x.id !== deleteConfirmItem.id));
        } else if (deleteConfirmType === "achievement") {
          setAchievementsList(achievementsList.filter(x => x.id !== deleteConfirmItem.id));
        }
        flashMessage("Record deleted successfully.", "success");
        addLogLine(`[System] Removed ${deleteConfirmType} entry.`);
        setLastUpdated(new Date().toLocaleTimeString());
      } else {
        let detail = "Failed to delete record.";
        try {
          const errBody = await res.json();
          console.error("[ProfileDelete] Error body:", errBody);
          if (errBody?.detail) detail = typeof errBody.detail === "string" ? errBody.detail : JSON.stringify(errBody.detail);
        } catch {}
        flashMessage(detail, "error");
      }
    } catch (e) {
      console.error("[ProfileDelete] Network error:", e);
      flashMessage("Connection error.", "error");
    } finally {
      setIsSaving(false);
      setDeleteConfirmType(null);
      setDeleteConfirmItem(null);
    }
  };

  // Direct skill delete (no confirmation modal - skills are quick to re-add)
  const handleDeleteSkill = async (skillId: string, skillName: string) => {
    if (!token) return;
    console.log("[SkillDelete] Deleting skill:", { skillId, skillName });
    try {
      const res = await fetch(`${API_BASE}/profile/skills/${skillId}`, {
        method: "DELETE",
        headers: { "Authorization": `Bearer ${token}` }
      });
      if (res.ok || res.status === 204) {
        setSkillsList(prev => prev.filter(s => s.id !== skillId));
        flashMessage(`Skill "${skillName}" removed.`, "success");
        addLogLine(`[System] Removed skill: ${skillName}`);
        setLastUpdated(new Date().toLocaleTimeString());
      } else {
        let detail = "Failed to remove skill.";
        try {
          const errBody = await res.json();
          if (errBody?.detail) detail = typeof errBody.detail === "string" ? errBody.detail : JSON.stringify(errBody.detail);
        } catch {}
        flashMessage(detail, "error");
      }
    } catch (e) {
      console.error("[SkillDelete] Network error:", e);
      flashMessage("Connection error.", "error");
    }
  };

  // Preferences array managers
  const addTag = (field: keyof Preferences, value: string, cleanInput: () => void) => {
    const trimmed = value.trim();
    if (!trimmed) return;
    const currentList = preferences[field] as string[];
    if (!currentList.includes(trimmed)) {
      setPreferences({
        ...preferences,
        [field]: [...currentList, trimmed]
      });
    }
    cleanInput();
  };

  const removeTag = (field: keyof Preferences, tag: string) => {
    const currentList = preferences[field] as string[];
    setPreferences({
      ...preferences,
      [field]: currentList.filter(t => t !== tag)
    });
  };

  // Helper to get formatted Year from Date strings
  const getYearStr = (dateStr?: string) => {
    if (!dateStr) return "";
    const match = dateStr.match(/\b(19\d{2}|20\d{2})\b/);
    if (match) return match[1];
    try {
      const year = new Date(dateStr).getFullYear();
      return isNaN(year) ? "" : year.toString();
    } catch {
      return "";
    }
  };

  // Search filtering lists
  const filteredEdu = educationList.filter(x => 
    x.institution_name.toLowerCase().includes(searchQuery.toLowerCase()) ||
    x.degree.toLowerCase().includes(searchQuery.toLowerCase()) ||
    x.field_of_study.toLowerCase().includes(searchQuery.toLowerCase())
  );

  const filteredExp = experienceList.filter(x => 
    x.company_name.toLowerCase().includes(searchQuery.toLowerCase()) ||
    x.role_title.toLowerCase().includes(searchQuery.toLowerCase()) ||
    x.description.toLowerCase().includes(searchQuery.toLowerCase())
  );

  const filteredProj = projectsList.filter(x => 
    x.project_name.toLowerCase().includes(searchQuery.toLowerCase()) ||
    x.description.toLowerCase().includes(searchQuery.toLowerCase())
  );

  const filteredAch = achievementsList.filter(x => 
    x.title.toLowerCase().includes(searchQuery.toLowerCase()) ||
    (x.description || "").toLowerCase().includes(searchQuery.toLowerCase()) ||
    (x.issuer || "").toLowerCase().includes(searchQuery.toLowerCase())
  );

  // Normalise all skill records — coerce any null/undefined fields to safe defaults
  // before grouping or rendering, so no child component can crash on null.slice().
  const safeSkillsList: Skill[] = skillsList.map(s => ({
    ...s,
    skill_name: s.skill_name || "Unnamed Skill",
    category: s.category || "Other",
    proficiency_level: s.proficiency_level || "UNKNOWN",
    is_primary: s.is_primary ?? false,
  }));

  // Grouped skills compilation
  const groupedSkills: Record<string, Skill[]> = {};
  SKILLS_CATEGORIES.forEach(cat => {
    groupedSkills[cat] = [];
  });
  
  safeSkillsList.forEach(skill => {
    const norm = normalizeSkillCategory(skill.category || "");
    if (groupedSkills[norm]) {
      groupedSkills[norm].push(skill);
    } else {
      groupedSkills["Other Technologies"].push(skill);
    }
  });

  const filteredGroupedSkills: Record<string, Skill[]> = {};
  SKILLS_CATEGORIES.forEach(cat => {
    filteredGroupedSkills[cat] = groupedSkills[cat].filter(s => 
      s.skill_name.toLowerCase().includes(searchQuery.toLowerCase())
    );
  });

  // Skeleton screen rendering
  const SkeletonLoader = () => (
    <div className="space-y-4 animate-pulse">
      {[1, 2, 3].map(i => (
        <div key={i} className="p-5 bg-zinc-900/20 border border-zinc-800/40 rounded-2xl space-y-3">
          <div className="h-4 bg-zinc-800/50 rounded-full w-1/4"></div>
          <div className="h-3 bg-zinc-800/40 rounded-full w-2/3"></div>
          <div className="h-2 bg-zinc-800/30 rounded-full w-1/2"></div>
        </div>
      ))}
    </div>
  );

  return (
    <div className="space-y-8 animate-fade-in relative pb-16">
      
      {/* Save indicators and Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 border-b border-zinc-800/60 pb-6">
        <div>
          <h2 className="text-2xl font-black tracking-tight text-zinc-100 font-sans flex items-center gap-2">
            <Settings className="w-6 h-6 text-emerald-500 animate-spin-slow" />
            Candidate Profile Control Panel
          </h2>
          <p className="text-xs text-zinc-400 mt-1 flex items-center gap-1.5 font-mono">
            <Clock className="w-3.5 h-3.5" />
            Config parameters, skills registry, and manual CV inputs. 
            {lastUpdated && <span className="text-emerald-500 font-semibold">• Last synced: {lastUpdated}</span>}
          </p>
        </div>

        {/* Global saving indicator & toast */}
        <div className="flex items-center gap-3">
          {isSaving && (
            <div className="flex items-center gap-1.5 text-zinc-400 font-mono text-[10px] bg-zinc-900/60 py-1 px-2.5 rounded-full border border-zinc-800">
              <Loader2 className="w-3 h-3 animate-spin text-emerald-500" />
              <span>Saving database state...</span>
            </div>
          )}

          {statusMessage && (
            <div className={`py-1.5 px-3.5 rounded-full border text-xs flex items-center gap-2 font-mono font-medium shadow-lg transition-all ${
              statusType === "success" 
                ? "bg-emerald-950/40 text-emerald-400 border-emerald-800/80 shadow-emerald-950/20" 
                : "bg-red-950/40 text-red-400 border-red-800/80 shadow-red-950/20"
            }`}>
              {statusType === "success" ? <CheckCircle className="w-3.5 h-3.5 shrink-0" /> : <AlertCircle className="w-3.5 h-3.5 shrink-0" />}
              <span>{statusMessage}</span>
            </div>
          )}

          {/* ── Backup Controls ─────────────────────────────────────── */}
          <div className="relative">
            {/* Main export button */}
            <button
              id="backup-export-btn"
              onClick={handleDownloadBackup}
              disabled={isExporting}
              title="Download full JSON backup"
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-semibold font-mono
                bg-emerald-950/40 text-emerald-400 border border-emerald-800/60
                hover:bg-emerald-900/50 hover:border-emerald-600 hover:text-emerald-300
                disabled:opacity-50 disabled:cursor-not-allowed transition-all duration-200
                shadow-[0_0_12px_rgba(16,185,129,0.08)] hover:shadow-[0_0_18px_rgba(16,185,129,0.18)]"
            >
              {isExporting ? (
                <Loader2 className="w-3.5 h-3.5 animate-spin" />
              ) : (
                <Download className="w-3.5 h-3.5" />
              )}
              {isExporting ? "Exporting..." : "Backup"}
            </button>
          </div>

          {/* ZIP export button */}
          <button
            id="backup-zip-btn"
            onClick={handleDownloadZip}
            disabled={isExportingZip}
            title="Download ZIP package (JSON + PDFs)"
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-semibold font-mono
              bg-indigo-950/40 text-indigo-400 border border-indigo-800/60
              hover:bg-indigo-900/50 hover:border-indigo-600 hover:text-indigo-300
              disabled:opacity-50 disabled:cursor-not-allowed transition-all duration-200
              shadow-[0_0_12px_rgba(99,102,241,0.08)] hover:shadow-[0_0_18px_rgba(99,102,241,0.18)]"
          >
            {isExportingZip ? (
              <Loader2 className="w-3.5 h-3.5 animate-spin" />
            ) : (
              <Archive className="w-3.5 h-3.5" />
            )}
            {isExportingZip ? "Packing..." : "ZIP"}
          </button>

          {/* Restore button — triggers hidden file input */}
          <label
            id="backup-restore-btn"
            title="Restore from .json backup"
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-semibold font-mono cursor-pointer
              bg-amber-950/40 text-amber-400 border border-amber-800/60
              hover:bg-amber-900/50 hover:border-amber-600 hover:text-amber-300
              transition-all duration-200
              shadow-[0_0_12px_rgba(245,158,11,0.08)] hover:shadow-[0_0_18px_rgba(245,158,11,0.18)]
              ${isPreviewing ? "opacity-50 pointer-events-none" : ""}`}
          >
            {isPreviewing ? (
              <Loader2 className="w-3.5 h-3.5 animate-spin" />
            ) : (
              <RotateCcw className="w-3.5 h-3.5" />
            )}
            {isPreviewing ? "Reading..." : "Restore"}
            <input
              type="file"
              accept=".json"
              className="hidden"
              onChange={handleSelectRestoreFile}
            />
          </label>
          {/* ─────────────────────────────────────────────────────── */}
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-4 gap-8 items-start">
        
        {/* Navigation Sidebar: Double-Bezel premium deck */}
        <div className="p-1.5 rounded-[1.25rem] bg-zinc-900/30 ring-1 ring-zinc-800/50 backdrop-blur-md">
          <div className="bg-[#0b0b0f] rounded-[calc(1.25rem-0.375rem)] p-4 shadow-[inset_0_1px_1px_rgba(255,255,255,0.03)] space-y-1">
            <h3 className="font-bold text-[10px] text-zinc-500 uppercase tracking-widest px-3 mb-3 font-mono">
              Profile Sections
            </h3>

            {[
              { id: "general", label: "General & Social Links", icon: User },
              { id: "matching", label: "Match Preferences", icon: Sliders },
              { id: "blacklists", label: "Filters & Blacklists", icon: ShieldAlert },
              { id: "education", label: "Education History", icon: GraduationCap },
              { id: "experience", label: "Work Experience", icon: Briefcase },
              { id: "projects", label: "Projects Details", icon: Code },
              { id: "skills", label: "Skills Taxonomy", icon: BookOpen },
              { id: "achievements", label: "Achievements & Awards", icon: Trophy }
            ].map(tab => {
              const Icon = tab.icon;
              return (
                <button
                  key={tab.id}
                  onClick={() => {
                    setActiveTab(tab.id as any);
                    setStatusMessage("");
                    setSearchQuery("");
                  }}
                  className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-xl text-xs font-semibold tracking-wide transition-all ${
                    activeTab === tab.id
                      ? "bg-zinc-900/80 text-emerald-400 border-l-2 border-emerald-500 rounded-l-none"
                      : "text-zinc-400 hover:text-zinc-200 hover:bg-zinc-900/30"
                  }`}
                >
                  <Icon className="w-4 h-4 shrink-0" />
                  <span>{tab.label}</span>
                </button>
              );
            })}
          </div>
        </div>

        {/* Edit Panel Column (col-span-3) */}
        <div className="lg:col-span-3 space-y-6">
          
          {/* TAB 1: General Info */}
          {activeTab === "general" && (
            <div className="p-1.5 rounded-[1.25rem] bg-zinc-900/30 ring-1 ring-zinc-800/50">
              <form onSubmit={handleSaveProfile} className="bg-[#0b0b0f] rounded-[calc(1.25rem-0.375rem)] p-6 shadow-[inset_0_1px_1px_rgba(255,255,255,0.03)] space-y-6 text-xs">
                
                <h3 className="font-bold text-sm text-zinc-150 uppercase tracking-wide border-b border-zinc-900 pb-3 flex items-center gap-2 font-mono">
                  <User className="w-4 h-4 text-emerald-500" />
                  General Profile & Socials
                </h3>

                <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
                  <div>
                    <label className="block text-zinc-400 font-semibold mb-1.5">LinkedIn Profile Link</label>
                    <input 
                      type="url" 
                      placeholder="https://linkedin.com/in/..."
                      value={profile.linkedin_url}
                      onChange={e => setProfile({...profile, linkedin_url: e.target.value})}
                      className="w-full px-3 py-2 bg-zinc-950 border border-zinc-900 rounded-lg text-zinc-250 focus:outline-none focus:border-emerald-500 transition-all placeholder-zinc-700"
                    />
                  </div>
                  <div>
                    <label className="block text-zinc-400 font-semibold mb-1.5">GitHub Profile Link</label>
                    <input 
                      type="url" 
                      placeholder="https://github.com/..."
                      value={profile.github_url}
                      onChange={e => setProfile({...profile, github_url: e.target.value})}
                      className="w-full px-3 py-2 bg-zinc-950 border border-zinc-900 rounded-lg text-zinc-250 focus:outline-none focus:border-emerald-500 transition-all placeholder-zinc-700"
                    />
                  </div>
                  <div>
                    <label className="block text-zinc-400 font-semibold mb-1.5">Portfolio/Website Link</label>
                    <input 
                      type="url" 
                      placeholder="https://..."
                      value={profile.portfolio_url}
                      onChange={e => setProfile({...profile, portfolio_url: e.target.value})}
                      className="w-full px-3 py-2 bg-zinc-950 border border-zinc-900 rounded-lg text-zinc-250 focus:outline-none focus:border-emerald-500 transition-all placeholder-zinc-700"
                    />
                  </div>
                </div>

                <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
                  <div>
                    <label className="block text-zinc-400 font-semibold mb-1.5">City</label>
                    <input 
                      type="text" 
                      placeholder="e.g. Bangalore"
                      value={profile.address_city}
                      onChange={e => setProfile({...profile, address_city: e.target.value})}
                      className="w-full px-3 py-2 bg-zinc-950 border border-zinc-900 rounded-lg text-zinc-250 focus:outline-none focus:border-emerald-500 transition-all placeholder-zinc-700"
                    />
                  </div>
                  <div>
                    <label className="block text-zinc-400 font-semibold mb-1.5">State</label>
                    <input 
                      type="text" 
                      placeholder="e.g. Karnataka"
                      value={profile.address_state}
                      onChange={e => setProfile({...profile, address_state: e.target.value})}
                      className="w-full px-3 py-2 bg-zinc-950 border border-zinc-900 rounded-lg text-zinc-250 focus:outline-none focus:border-emerald-500 transition-all placeholder-zinc-700"
                    />
                  </div>
                  <div>
                    <label className="block text-zinc-400 font-semibold mb-1.5">Country</label>
                    <input 
                      type="text" 
                      placeholder="India"
                      value={profile.address_country}
                      onChange={e => setProfile({...profile, address_country: e.target.value})}
                      className="w-full px-3 py-2 bg-zinc-950 border border-zinc-900 rounded-lg text-zinc-250 focus:outline-none focus:border-emerald-500 transition-all placeholder-zinc-700"
                    />
                  </div>
                </div>

                <div className="grid grid-cols-1 md:grid-cols-4 gap-6">
                  <div>
                    <label className="block text-zinc-400 font-semibold mb-1.5">Years of Experience</label>
                    <input 
                      type="number" 
                      step="0.1" 
                      value={profile.years_of_experience}
                      onChange={e => setProfile({...profile, years_of_experience: parseFloat(e.target.value) || 0})}
                      className="w-full px-3 py-2 bg-zinc-950 border border-zinc-900 rounded-lg text-zinc-250 focus:outline-none focus:border-emerald-500 transition-all"
                    />
                  </div>
                  <div>
                    <label className="block text-zinc-400 font-semibold mb-1.5">Current Role</label>
                    <input 
                      type="text" 
                      placeholder="e.g. Software Engineer"
                      value={profile.current_role}
                      onChange={e => setProfile({...profile, current_role: e.target.value})}
                      className="w-full px-3 py-2 bg-zinc-950 border border-zinc-900 rounded-lg text-zinc-250 focus:outline-none focus:border-emerald-500 transition-all placeholder-zinc-700"
                    />
                  </div>
                  <div>
                    <label className="block text-zinc-400 font-semibold mb-1.5">Current Company</label>
                    <input 
                      type="text" 
                      placeholder="e.g. Acme Corp"
                      value={profile.current_company}
                      onChange={e => setProfile({...profile, current_company: e.target.value})}
                      className="w-full px-3 py-2 bg-zinc-950 border border-zinc-900 rounded-lg text-zinc-250 focus:outline-none focus:border-emerald-500 transition-all placeholder-zinc-700"
                    />
                  </div>
                  <div>
                    <label className="block text-zinc-400 font-semibold mb-1.5">Current Salary (LPA / INR)</label>
                    <input 
                      type="number" 
                      placeholder="e.g. 1200000"
                      value={profile.current_salary_inr || ""}
                      onChange={e => setProfile({...profile, current_salary_inr: parseInt(e.target.value) || 0})}
                      className="w-full px-3 py-2 bg-zinc-950 border border-zinc-900 rounded-lg text-zinc-200 focus:outline-none focus:border-emerald-500 transition-all placeholder-zinc-750 font-mono"
                    />
                  </div>
                </div>

                <div>
                  <label className="block text-zinc-400 font-semibold mb-1.5">Profile Summary</label>
                  <textarea 
                    rows={4}
                    placeholder="Short natural language description of your career profile, technical expertise, and goals..."
                    value={profile.profile_summary}
                    onChange={e => setProfile({...profile, profile_summary: e.target.value})}
                    className="w-full px-3 py-2 bg-zinc-950 border border-zinc-900 rounded-lg text-zinc-200 focus:outline-none focus:border-emerald-500 transition-all placeholder-zinc-700 leading-relaxed font-mono text-[11px]"
                  />
                </div>

                <button 
                  type="submit"
                  disabled={isSaving}
                  className="py-2.5 px-4 bg-emerald-600 hover:bg-emerald-500 text-white font-bold rounded-lg transition-colors flex items-center justify-center gap-2 shadow-[0_0_15px_rgba(16,185,129,0.15)] cursor-pointer self-start"
                >
                  <Save className="w-4 h-4" />
                  Save General Settings
                </button>
              </form>
            </div>
          )}

          {/* TAB 2: Matching Preferences */}
          {activeTab === "matching" && (
            <div className="p-1.5 rounded-[1.25rem] bg-zinc-900/30 ring-1 ring-zinc-800/50">
              <form onSubmit={handleSavePreferences} className="bg-[#0b0b0f] rounded-[calc(1.25rem-0.375rem)] p-6 shadow-[inset_0_1px_1px_rgba(255,255,255,0.03)] space-y-6 text-xs">
                
                <h3 className="font-bold text-sm text-zinc-150 uppercase tracking-wide border-b border-zinc-900 pb-3 flex items-center gap-2 font-mono">
                  <Sliders className="w-4 h-4 text-emerald-500" />
                  Match Criteria & Thresholds
                </h3>

                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
                  <div>
                    <label className="block text-zinc-400 font-semibold mb-1.5">Min Compatibility Match Score (%)</label>
                    <input 
                      type="number" 
                      min="30" 
                      max="100"
                      value={preferences.min_match_score}
                      onChange={e => setPreferences({...preferences, min_match_score: parseInt(e.target.value) || 60})}
                      className="w-full px-3 py-2 bg-zinc-950 border border-zinc-900 rounded-lg text-zinc-200 focus:outline-none focus:border-emerald-500 font-mono"
                    />
                  </div>
                  <div>
                    <label className="block text-zinc-400 font-semibold mb-1.5">Auto-Apply Score Threshold (%)</label>
                    <input 
                      type="number" 
                      min="40" 
                      max="100"
                      value={preferences.auto_apply_threshold}
                      onChange={e => setPreferences({...preferences, auto_apply_threshold: parseInt(e.target.value) || 75})}
                      className="w-full px-3 py-2 bg-zinc-950 border border-zinc-900 rounded-lg text-zinc-200 focus:outline-none focus:border-emerald-500 font-mono"
                    />
                  </div>
                  <div>
                    <label className="block text-zinc-400 font-semibold mb-1.5">Max Applications / Day</label>
                    <input 
                      type="number" 
                      min="1" 
                      max="100"
                      value={preferences.max_applications_per_day}
                      onChange={e => setPreferences({...preferences, max_applications_per_day: parseInt(e.target.value) || 20})}
                      className="w-full px-3 py-2 bg-zinc-950 border border-zinc-900 rounded-lg text-zinc-200 focus:outline-none focus:border-emerald-500 font-mono"
                    />
                  </div>
                  <div>
                    <label className="block text-zinc-400 font-semibold mb-1.5">Max Applications / Hour</label>
                    <input 
                      type="number" 
                      min="1" 
                      max="100"
                      value={preferences.max_applications_per_hour !== undefined ? preferences.max_applications_per_hour : 10}
                      onChange={e => setPreferences({...preferences, max_applications_per_hour: parseInt(e.target.value) || 10})}
                      className="w-full px-3 py-2 bg-zinc-950 border border-zinc-900 rounded-lg text-zinc-200 focus:outline-none focus:border-emerald-500 font-mono"
                    />
                  </div>
                </div>

                <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
                  <div>
                    <label className="block text-zinc-400 font-semibold mb-1.5">Remote Workplace Preference</label>
                    <select
                      value={preferences.remote_preference}
                      onChange={e => setPreferences({...preferences, remote_preference: e.target.value})}
                      className="w-full px-3 py-2 bg-zinc-950 border border-zinc-900 rounded-lg text-zinc-250 focus:outline-none focus:border-emerald-500"
                    >
                      <option value="REMOTE">Remote Exclusive</option>
                      <option value="HYBRID">Hybrid Allowed</option>
                      <option value="ONSITE">Onsite Only</option>
                    </select>
                  </div>
                  
                  <div>
                    <label className="block text-zinc-400 font-semibold mb-1.5">Notice Period (Days)</label>
                    <input 
                      type="number" 
                      value={preferences.notice_period_days}
                      onChange={e => setPreferences({...preferences, notice_period_days: parseInt(e.target.value) || 0})}
                      className="w-full px-3 py-2 bg-zinc-950 border border-zinc-900 rounded-lg text-zinc-200 focus:outline-none focus:border-emerald-500 font-mono"
                    />
                  </div>

                  <div>
                    <label className="block text-zinc-400 font-semibold mb-1.5">Experience Target Level</label>
                    <select
                      value={preferences.experience_level}
                      onChange={e => setPreferences({...preferences, experience_level: e.target.value})}
                      className="w-full px-3 py-2 bg-zinc-950 border border-zinc-900 rounded-lg text-zinc-250 focus:outline-none focus:border-emerald-500"
                    >
                      <option value="FRESHER">Fresher / Graduate</option>
                      <option value="JUNIOR">Junior (1-2 yrs)</option>
                      <option value="MID">Mid-Level (3-5 yrs)</option>
                      <option value="SENIOR">Senior (6+ yrs)</option>
                    </select>
                  </div>
                </div>

                <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                  <div>
                    <label className="block text-zinc-400 font-semibold mb-1.5">Annual Salary Expected range (INR LPA)</label>
                    <div className="flex items-center gap-3">
                      <input 
                        type="number" 
                        placeholder="Min INR"
                        value={preferences.min_salary_inr || ""}
                        onChange={e => setPreferences({...preferences, min_salary_inr: parseInt(e.target.value) || 0})}
                        className="w-full px-3 py-2 bg-zinc-950 border border-zinc-900 rounded-lg text-zinc-200 focus:outline-none focus:border-emerald-500 font-mono"
                      />
                      <span className="text-zinc-650 font-mono">to</span>
                      <input 
                        type="number" 
                        placeholder="Preferred LPA"
                        value={preferences.preferred_salary_inr || ""}
                        onChange={e => setPreferences({...preferences, preferred_salary_inr: parseInt(e.target.value) || 0})}
                        className="w-full px-3 py-2 bg-zinc-950 border border-zinc-900 rounded-lg text-zinc-200 focus:outline-none focus:border-emerald-500 font-mono"
                      />
                    </div>
                  </div>

                  <div>
                    <label className="block text-zinc-400 font-semibold mb-1.5">Stipend Expected (For Internships / Month)</label>
                    <div className="flex items-center gap-3">
                      <input 
                        type="number" 
                        placeholder="Min Stipend"
                        value={preferences.min_stipend_inr || ""}
                        onChange={e => setPreferences({...preferences, min_stipend_inr: parseInt(e.target.value) || 0})}
                        className="w-full px-3 py-2 bg-zinc-950 border border-zinc-900 rounded-lg text-zinc-200 focus:outline-none focus:border-emerald-500 font-mono"
                      />
                      <span className="text-zinc-650 font-mono">to</span>
                      <input 
                        type="number" 
                        placeholder="Target"
                        value={preferences.preferred_stipend_inr || ""}
                        onChange={e => setPreferences({...preferences, preferred_stipend_inr: parseInt(e.target.value) || 0})}
                        className="w-full px-3 py-2 bg-zinc-950 border border-zinc-900 rounded-lg text-zinc-200 focus:outline-none focus:border-emerald-500 font-mono"
                      />
                    </div>
                  </div>
                </div>

                {/* Required Skills tags */}
                <div className="space-y-2">
                  <label className="block text-zinc-400 font-semibold mb-1">Must-Have Skills Keywords (Strict filtering)</label>
                  <div className="flex flex-wrap gap-1.5 p-3 bg-zinc-950/40 border border-zinc-900 rounded-xl min-h-[40px] items-center">
                    {preferences.required_skills.map(tag => (
                      <span key={tag} className="flex items-center gap-1 px-2.5 py-0.5 bg-zinc-900 text-zinc-200 rounded border border-zinc-800 font-mono text-[10px]">
                        {tag}
                        <button type="button" onClick={() => removeTag("required_skills", tag)} className="hover:text-red-400 text-zinc-500 cursor-pointer">
                          <X className="w-3 h-3" />
                        </button>
                      </span>
                    ))}
                    <input 
                      type="text"
                      placeholder="Add tag and press Enter"
                      value={reqSkillInput}
                      onChange={e => setReqSkillInput(e.target.value)}
                      onKeyDown={e => {
                        if (e.key === "Enter") {
                          e.preventDefault();
                          addTag("required_skills", reqSkillInput, () => setReqSkillInput(""));
                        }
                      }}
                      className="bg-transparent border-none focus:outline-none text-zinc-200 text-xs px-2 min-w-[150px]"
                    />
                  </div>
                </div>

                {/* Email Tracker Settings */}
                <div className="border-t border-zinc-900 pt-5 space-y-4">
                  <h4 className="font-bold text-xs text-zinc-300 uppercase tracking-wider font-mono">Gmail Integration (Email Monitoring)</h4>
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                    <div>
                      <label className="block text-zinc-400 font-semibold mb-1.5">Gmail App Password</label>
                      <input 
                        type="password" 
                        placeholder="16-character google app password"
                        value={preferences.gmail_app_password || ""}
                        onChange={e => setPreferences({...preferences, gmail_app_password: e.target.value})}
                        className="w-full px-3 py-2 bg-zinc-950 border border-zinc-900 rounded-lg text-zinc-200 focus:outline-none focus:border-emerald-500 font-mono"
                      />
                      <p className="text-[10px] text-zinc-500 mt-1">Required to authenticate IMAP inbox tracking. Use a Google App Password, NOT your main account password.</p>
                    </div>
                    <div className="flex items-center gap-3 mt-6">
                      <label className="flex items-center gap-2 text-zinc-400 font-semibold cursor-pointer">
                        <input 
                          type="checkbox"
                          checked={preferences.email_monitoring_enabled || false}
                          onChange={e => setPreferences({...preferences, email_monitoring_enabled: e.target.checked})}
                          className="rounded border-zinc-900 bg-zinc-950 text-emerald-500 focus:ring-emerald-500 h-4 w-4"
                        />
                        <span>Enable Automated Email Monitoring</span>
                      </label>
                    </div>
                  </div>
                </div>

                <button 
                  type="submit"
                  disabled={isSaving}
                  className="py-2.5 px-4 bg-emerald-600 hover:bg-emerald-500 text-white font-bold rounded-lg transition-colors flex items-center justify-center gap-2 shadow-[0_0_15px_rgba(16,185,129,0.15)] cursor-pointer self-start"
                >
                  <Save className="w-4 h-4" />
                  Save Matching Rules
                </button>

              </form>
            </div>
          )}

          {/* TAB 3: Blacklists & Filters */}
          {activeTab === "blacklists" && (
            <div className="p-1.5 rounded-[1.25rem] bg-zinc-900/30 ring-1 ring-zinc-800/50">
              <form onSubmit={handleSavePreferences} className="bg-[#0b0b0f] rounded-[calc(1.25rem-0.375rem)] p-6 shadow-[inset_0_1px_1px_rgba(255,255,255,0.03)] space-y-6 text-xs">
                
                <h3 className="font-bold text-sm text-zinc-150 uppercase tracking-wide border-b border-zinc-900 pb-3 flex items-center gap-2 font-mono">
                  <ShieldAlert className="w-4 h-4 text-emerald-500" />
                  Target Filters & Blacklists
                </h3>

                {/* Target roles tags */}
                <div className="space-y-2">
                  <label className="block text-zinc-400 font-semibold mb-1">Preferred Job Roles</label>
                  <div className="flex flex-wrap gap-1.5 p-3 bg-zinc-950/40 border border-zinc-900 rounded-xl min-h-[40px] items-center">
                    {preferences.preferred_roles.map(tag => (
                      <span key={tag} className="flex items-center gap-1 px-2.5 py-0.5 bg-zinc-900 text-zinc-200 rounded border border-zinc-800 font-mono text-[10px]">
                        {tag}
                        <button type="button" onClick={() => removeTag("preferred_roles", tag)} className="hover:text-red-400 text-zinc-500 cursor-pointer">
                          <X className="w-3 h-3" />
                        </button>
                      </span>
                    ))}
                    <input 
                      type="text"
                      placeholder="Add role (e.g. AI Engineer)"
                      value={roleInput}
                      onChange={e => setRoleInput(e.target.value)}
                      onKeyDown={e => {
                        if (e.key === "Enter") {
                          e.preventDefault();
                          addTag("preferred_roles", roleInput, () => setRoleInput(""));
                        }
                      }}
                      className="bg-transparent border-none focus:outline-none text-zinc-200 text-xs px-2 min-w-[150px]"
                    />
                  </div>
                </div>

                {/* Target locations tags */}
                <div className="space-y-2">
                  <label className="block text-zinc-400 font-semibold mb-1">Target Office Locations</label>
                  <div className="flex flex-wrap gap-1.5 p-3 bg-zinc-950/40 border border-zinc-900 rounded-xl min-h-[40px] items-center">
                    {preferences.preferred_locations.map(tag => (
                      <span key={tag} className="flex items-center gap-1 px-2.5 py-0.5 bg-zinc-900 text-zinc-200 rounded border border-zinc-800 font-mono text-[10px]">
                        {tag}
                        <button type="button" onClick={() => removeTag("preferred_locations", tag)} className="hover:text-red-400 text-zinc-500 cursor-pointer">
                          <X className="w-3 h-3" />
                        </button>
                      </span>
                    ))}
                    <input 
                      type="text"
                      placeholder="Add city (e.g. Bangalore)"
                      value={locInput}
                      onChange={e => setLocInput(e.target.value)}
                      onKeyDown={e => {
                        if (e.key === "Enter") {
                          e.preventDefault();
                          addTag("preferred_locations", locInput, () => setLocInput(""));
                        }
                      }}
                      className="bg-transparent border-none focus:outline-none text-zinc-200 text-xs px-2 min-w-[150px]"
                    />
                  </div>
                </div>

                {/* Target companies tags */}
                <div className="space-y-2">
                  <label className="block text-zinc-400 font-semibold mb-1">Dream Target Companies</label>
                  <div className="flex flex-wrap gap-1.5 p-3 bg-zinc-950/40 border border-zinc-900 rounded-xl min-h-[40px] items-center">
                    {preferences.preferred_companies.map(tag => (
                      <span key={tag} className="flex items-center gap-1 px-2.5 py-0.5 bg-zinc-900 text-zinc-200 rounded border border-zinc-800 font-mono text-[10px]">
                        {tag}
                        <button type="button" onClick={() => removeTag("preferred_companies", tag)} className="hover:text-red-400 text-zinc-500 cursor-pointer">
                          <X className="w-3 h-3" />
                        </button>
                      </span>
                    ))}
                    <input 
                      type="text"
                      placeholder="Add company name"
                      value={companyInput}
                      onChange={e => setCompanyInput(e.target.value)}
                      onKeyDown={e => {
                        if (e.key === "Enter") {
                          e.preventDefault();
                          addTag("preferred_companies", companyInput, () => setCompanyInput(""));
                        }
                      }}
                      className="bg-transparent border-none focus:outline-none text-zinc-200 text-xs px-2 min-w-[150px]"
                    />
                  </div>
                </div>

                {/* Blacklisted companies tags */}
                <div className="space-y-2">
                  <label className="block text-red-400/80 font-semibold mb-1">Blacklisted Companies (Immediate Skip)</label>
                  <div className="flex flex-wrap gap-1.5 p-3 bg-zinc-950/40 border border-red-900/20 rounded-xl min-h-[40px] items-center">
                    {preferences.blacklisted_companies.map(tag => (
                      <span key={tag} className="flex items-center gap-1 px-2.5 py-0.5 bg-zinc-900 text-red-400 rounded border border-red-900/40 font-mono text-[10px]">
                        {tag}
                        <button type="button" onClick={() => removeTag("blacklisted_companies", tag)} className="hover:text-red-400 text-zinc-500 cursor-pointer">
                          <X className="w-3 h-3" />
                        </button>
                      </span>
                    ))}
                    <input 
                      type="text"
                      placeholder="Add blocked company"
                      value={blacklistCompanyInput}
                      onChange={e => setBlacklistCompanyInput(e.target.value)}
                      onKeyDown={e => {
                        if (e.key === "Enter") {
                          e.preventDefault();
                          addTag("blacklisted_companies", blacklistCompanyInput, () => setBlacklistCompanyInput(""));
                        }
                      }}
                      className="bg-transparent border-none focus:outline-none text-zinc-250 text-xs px-2 min-w-[150px]"
                    />
                  </div>
                </div>

                {/* Blacklisted keywords tags */}
                <div className="space-y-2">
                  <label className="block text-red-400/80 font-semibold mb-1">Blacklisted Description Keywords</label>
                  <div className="flex flex-wrap gap-1.5 p-3 bg-zinc-950/40 border border-red-900/20 rounded-xl min-h-[40px] items-center">
                    {preferences.blacklisted_keywords.map(tag => (
                      <span key={tag} className="flex items-center gap-1 px-2.5 py-0.5 bg-zinc-900 text-red-400 rounded border border-red-900/40 font-mono text-[10px]">
                        {tag}
                        <button type="button" onClick={() => removeTag("blacklisted_keywords", tag)} className="hover:text-red-400 text-zinc-500 cursor-pointer">
                          <X className="w-3 h-3" />
                        </button>
                      </span>
                    ))}
                    <input 
                      type="text"
                      placeholder="Add blocked keyword (e.g. Sales, PHP)"
                      value={blacklistKeywordInput}
                      onChange={e => setBlacklistKeywordInput(e.target.value)}
                      onKeyDown={e => {
                        if (e.key === "Enter") {
                          e.preventDefault();
                          addTag("blacklisted_keywords", blacklistKeywordInput, () => setBlacklistKeywordInput(""));
                        }
                      }}
                      className="bg-transparent border-none focus:outline-none text-zinc-250 text-xs px-2 min-w-[150px]"
                    />
                  </div>
                </div>

                <button 
                  type="submit"
                  disabled={isSaving}
                  className="py-2.5 px-4 bg-emerald-600 hover:bg-emerald-500 text-white font-bold rounded-lg transition-colors flex items-center justify-center gap-2 shadow-[0_0_15px_rgba(16,185,129,0.15)] cursor-pointer self-start"
                >
                  <Save className="w-4 h-4" />
                  Save Filter Rules
                </button>

              </form>
            </div>
          )}

          {/* Search bar helper for list sections */}
          {["education", "experience", "projects", "skills", "achievements"].includes(activeTab) && (
            <div className="flex items-center gap-2.5 p-3 bg-zinc-900/25 border border-zinc-800/60 rounded-2xl">
              <Search className="w-4 h-4 text-zinc-500 shrink-0 ml-1" />
              <input 
                type="text"
                placeholder={`Search records in ${activeTab}...`}
                value={searchQuery}
                onChange={e => setSearchQuery(e.target.value)}
                className="bg-transparent border-none focus:outline-none text-zinc-200 text-xs w-full font-mono"
              />
              {searchQuery && (
                <button onClick={() => setSearchQuery("")} className="text-zinc-500 hover:text-zinc-350 cursor-pointer">
                  <X className="w-3.5 h-3.5" />
                </button>
              )}
            </div>
          )}

          {/* TAB 4: Education History */}
          {activeTab === "education" && (
            <div className="space-y-6">
              
              {/* Form trigger box */}
              <div className="p-1.5 rounded-[1.25rem] bg-zinc-900/30 ring-1 ring-zinc-800/50">
                <div className="bg-[#0b0b0f] rounded-[calc(1.25rem-0.375rem)] p-5 shadow-[inset_0_1px_1px_rgba(255,255,255,0.03)] text-xs">
                  <div className="flex items-center justify-between">
                    <h3 className="font-semibold text-xs text-zinc-200 uppercase tracking-wide flex items-center gap-2 font-mono">
                      <GraduationCap className="w-4 h-4 text-emerald-500" />
                      Academic History
                    </h3>
                    <button 
                      onClick={() => setShowEduForm(!showEduForm)}
                      className="py-1 px-3 bg-zinc-900 border border-zinc-800 text-zinc-300 font-bold rounded-lg hover:bg-zinc-850 transition-colors flex items-center gap-1 cursor-pointer"
                    >
                      <Plus className="w-3.5 h-3.5" />
                      <span>{showEduForm ? "Close Form" : "Add Institution"}</span>
                    </button>
                  </div>

                  {showEduForm && (
                    <form onSubmit={handleAddEducation} className="mt-5 space-y-4 border-t border-zinc-900 pt-5 text-xs animate-fade-in">
                      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                        <div className="md:col-span-2">
                          <label className="block text-zinc-400 mb-1">Institution Name</label>
                          <input 
                            type="text" 
                            required
                            placeholder="e.g. National Institute of Technology Agartala"
                            value={newEdu.institution_name}
                            onChange={e => setNewEdu({...newEdu, institution_name: e.target.value})}
                            className="w-full px-3 py-2 bg-zinc-950 border border-zinc-900 rounded-lg text-zinc-200 focus:outline-none"
                          />
                        </div>
                        <div>
                          <label className="block text-zinc-400 mb-1">Location</label>
                          <input 
                            type="text" 
                            placeholder="e.g. Agartala, Tripura, India"
                            value={newEduLoc}
                            onChange={e => setNewEduLoc(e.target.value)}
                            className="w-full px-3 py-2 bg-zinc-950 border border-zinc-900 rounded-lg text-zinc-250 focus:outline-none"
                          />
                        </div>
                      </div>

                      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                        <div>
                          <label className="block text-zinc-400 mb-1">Degree Title</label>
                          <input 
                            type="text" 
                            required
                            placeholder="e.g. B.Tech Electronics & Communication Engineering"
                            value={newEdu.degree}
                            onChange={e => setNewEdu({...newEdu, degree: e.target.value})}
                            className="w-full px-3 py-2 bg-zinc-950 border border-zinc-900 rounded-lg text-zinc-200 focus:outline-none"
                          />
                        </div>
                        <div>
                          <label className="block text-zinc-400 mb-1">Field of Study</label>
                          <input 
                            type="text" 
                            placeholder="e.g. Electronics & Communication"
                            value={newEdu.field_of_study}
                            onChange={e => setNewEdu({...newEdu, field_of_study: e.target.value})}
                            className="w-full px-3 py-2 bg-zinc-950 border border-zinc-900 rounded-lg text-zinc-200 focus:outline-none"
                          />
                        </div>
                      </div>

                      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
                        <div>
                          <label className="block text-zinc-400 mb-1">Education Type</label>
                          <select 
                            value={newEdu.education_type}
                            onChange={e => setNewEdu({...newEdu, education_type: e.target.value})}
                            className="w-full px-3 py-2 bg-zinc-950 border border-zinc-900 rounded-lg text-zinc-250 focus:outline-none font-semibold"
                          >
                            <option value="BTECH">B.Tech / B.E.</option>
                            <option value="MTECH">M.Tech / M.E.</option>
                            <option value="PHD">Ph.D.</option>
                            <option value="HIGH_SCHOOL">High School</option>
                            <option value="OTHER">Other Graduate</option>
                          </select>
                        </div>
                        <div>
                          <label className="block text-zinc-400 mb-1">CGPA (out of 10.0)</label>
                          <input 
                            type="number" 
                            step="0.01" 
                            placeholder="e.g. 8.75"
                            value={newEdu.cgpa || ""}
                            onChange={e => setNewEdu({...newEdu, cgpa: parseFloat(e.target.value) || undefined})}
                            className="w-full px-3 py-2 bg-zinc-950 border border-zinc-900 rounded-lg text-zinc-200 focus:outline-none font-mono"
                          />
                        </div>
                        <div className="grid grid-cols-2 gap-2 md:col-span-2">
                          <div>
                            <label className="block text-zinc-400 mb-1">Start Year</label>
                            <input 
                              type="number" 
                              placeholder="2022"
                              value={newEdu.start_year || ""}
                              onChange={e => setNewEdu({...newEdu, start_year: parseInt(e.target.value) || undefined})}
                              className="w-full px-3 py-2 bg-zinc-950 border border-zinc-900 rounded-lg text-zinc-200 focus:outline-none font-mono"
                            />
                          </div>
                          <div>
                            <label className="block text-zinc-400 mb-1">End Year</label>
                            <input 
                              type="number" 
                              placeholder="2026"
                              value={newEdu.end_year || ""}
                              onChange={e => setNewEdu({...newEdu, end_year: parseInt(e.target.value) || undefined})}
                              className="w-full px-3 py-2 bg-zinc-950 border border-zinc-900 rounded-lg text-zinc-200 focus:outline-none font-mono"
                            />
                          </div>
                        </div>
                      </div>

                      <button 
                        type="submit"
                        disabled={isSaving}
                        className="py-2 px-4 bg-emerald-600 hover:bg-emerald-500 text-white font-bold rounded-lg transition-colors cursor-pointer"
                      >
                        Add History Entry
                      </button>
                    </form>
                  )}
                </div>
              </div>

              {/* Education items list */}
              <div className="space-y-4">
                {isLoading ? (
                  <SkeletonLoader />
                ) : filteredEdu.length === 0 ? (
                  <div className="p-12 text-center text-zinc-650 font-mono text-xs bg-[#0b0b0f] border border-zinc-900 rounded-2xl flex flex-col items-center justify-center gap-2">
                    <GraduationCap className="w-8 h-8 text-zinc-700" />
                    <span>No matching academic records found.</span>
                  </div>
                ) : (
                  filteredEdu.map(edu => {
                    const parts = edu.institution_name.split(" | ");
                    const instName = parts[0];
                    const locName = parts[1] || "";
                    
                    return (
                      <div key={edu.id} className="p-1.5 rounded-[1.25rem] bg-zinc-900/30 ring-1 ring-zinc-800/50 hover:ring-zinc-700/60 transition-all">
                        <div className="bg-[#0b0b0f] rounded-[calc(1.25rem-0.375rem)] p-5 shadow-[inset_0_1px_1px_rgba(255,255,255,0.03)] flex items-start justify-between text-xs gap-4">
                          <div className="space-y-1">
                            <h4 className="font-bold text-zinc-100 text-sm tracking-wide">{edu.degree}</h4>
                            <p className="text-zinc-300 font-medium">{instName}</p>
                            {locName && <p className="text-zinc-550 italic font-mono text-[10.5px]">{locName}</p>}
                            <div className="flex items-center gap-3 text-[10px] text-zinc-500 font-mono mt-2 uppercase">
                              <span>Type: {edu.education_type}</span>
                              <span>•</span>
                              <span>Years: {edu.start_year || "?"} - {edu.end_year || "Present"}</span>
                              {edu.cgpa && (
                                <>
                                  <span>•</span>
                                  <span className="text-emerald-500 font-bold">CGPA {edu.cgpa}/10</span>
                                </>
                              )}
                            </div>
                          </div>
                          
                          <div className="flex items-center gap-1.5 shrink-0">
                            <button 
                              onClick={() => openEditModal("education", edu)}
                              className="p-2 rounded-lg bg-zinc-900 text-zinc-450 hover:text-emerald-400 hover:bg-zinc-850 transition-colors cursor-pointer border border-zinc-800/40"
                              title="Edit Entry"
                            >
                              <Edit className="w-3.5 h-3.5" />
                            </button>
                            <button 
                              onClick={() => edu.id && triggerDelete("education", edu)}
                              className="p-2 rounded-lg bg-zinc-900 text-zinc-450 hover:text-red-400 hover:bg-zinc-850 transition-colors shrink-0 cursor-pointer border border-zinc-800/40"
                              title="Delete Entry"
                            >
                              <Trash2 className="w-3.5 h-3.5" />
                            </button>
                          </div>
                        </div>
                      </div>
                    );
                  })
                )}
              </div>

            </div>
          )}

          {/* TAB 5: Work Experience */}
          {activeTab === "experience" && (
            <div className="space-y-6">
              
              {/* Form trigger box */}
              <div className="p-1.5 rounded-[1.25rem] bg-zinc-900/30 ring-1 ring-zinc-800/50">
                <div className="bg-[#0b0b0f] rounded-[calc(1.25rem-0.375rem)] p-5 shadow-[inset_0_1px_1px_rgba(255,255,255,0.03)] text-xs">
                  <div className="flex items-center justify-between">
                    <h3 className="font-semibold text-xs text-zinc-200 uppercase tracking-wide flex items-center gap-2 font-mono">
                      <Briefcase className="w-4 h-4 text-emerald-500" />
                      Professional Experience History
                    </h3>
                    <button 
                      onClick={() => setShowExpForm(!showExpForm)}
                      className="py-1 px-3 bg-zinc-900 border border-zinc-800 text-zinc-300 font-bold rounded-lg hover:bg-zinc-850 transition-colors flex items-center gap-1 cursor-pointer"
                    >
                      <Plus className="w-3.5 h-3.5" />
                      <span>{showExpForm ? "Close Form" : "Add Experience"}</span>
                    </button>
                  </div>

                  {showExpForm && (
                    <form onSubmit={handleAddExperience} className="mt-5 space-y-4 border-t border-zinc-900 pt-5 text-xs animate-fade-in">
                      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                        <div>
                          <label className="block text-zinc-400 mb-1">Company Name</label>
                          <input 
                            type="text" 
                            required
                            placeholder="e.g. TechnoHacks EduTech"
                            value={newExp.company_name}
                            onChange={e => setNewExp({...newExp, company_name: e.target.value})}
                            className="w-full px-3 py-2 bg-zinc-950 border border-zinc-900 rounded-lg text-zinc-200 focus:outline-none"
                          />
                        </div>
                        <div>
                          <label className="block text-zinc-400 mb-1">Role Title</label>
                          <input 
                            type="text" 
                            required
                            placeholder="e.g. Machine Learning Intern"
                            value={newExp.role_title}
                            onChange={e => setNewExp({...newExp, role_title: e.target.value})}
                            className="w-full px-3 py-2 bg-zinc-950 border border-zinc-900 rounded-lg text-zinc-200 focus:outline-none"
                          />
                        </div>
                      </div>

                      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                        <div>
                          <label className="block text-zinc-400 mb-1">Employment Type</label>
                          <select 
                            value={newExp.employment_type}
                            onChange={e => setNewExp({...newExp, employment_type: e.target.value})}
                            className="w-full px-3 py-2 bg-zinc-950 border border-zinc-900 rounded-lg text-zinc-250 focus:outline-none font-semibold"
                          >
                            <option value="FULL_TIME">Full Time</option>
                            <option value="INTERNSHIP">Internship</option>
                            <option value="CONTRACT">Contract</option>
                            <option value="PART_TIME">Part Time</option>
                          </select>
                        </div>
                        <div>
                          <label className="block text-zinc-400 mb-1">Location</label>
                          <input 
                            type="text" 
                            placeholder="e.g. Remote"
                            value={newExp.location}
                            onChange={e => setNewExp({...newExp, location: e.target.value})}
                            className="w-full px-3 py-2 bg-zinc-950 border border-zinc-900 rounded-lg text-zinc-200 focus:outline-none"
                          />
                        </div>
                        <div className="flex items-center gap-2 mt-5">
                          <input 
                            type="checkbox"
                            id="exp_is_current"
                            checked={newExp.is_current}
                            onChange={e => setNewExp({...newExp, is_current: e.target.checked})}
                            className="w-3.5 h-3.5 bg-zinc-950 rounded border-zinc-900 text-emerald-600 focus:ring-0 focus:ring-offset-0 cursor-pointer"
                          />
                          <label htmlFor="exp_is_current" className="text-zinc-400 select-none cursor-pointer">Currently work here</label>
                        </div>
                      </div>

                      <div>
                        <label className="block text-zinc-400 mb-1">Description (Core tasks & achievements)</label>
                        <textarea 
                          rows={3}
                          placeholder="Completed Machine Learning internship focused on data preprocessing, model building..."
                          value={newExp.description}
                          onChange={e => setNewExp({...newExp, description: e.target.value})}
                          className="w-full px-3 py-2 bg-zinc-950 border border-zinc-900 rounded-lg text-zinc-200 focus:outline-none leading-relaxed font-mono text-[11px]"
                        />
                      </div>

                      {/* Skills used tags */}
                      <div className="space-y-1.5">
                        <label className="block text-zinc-400 mb-1">Skills Used (Press Enter to commit tag)</label>
                        <div className="flex flex-wrap gap-1 p-2 bg-zinc-950 border border-zinc-900 rounded-lg min-h-[35px] items-center">
                          {newExp.skills_used.map(sk => (
                            <span key={sk} className="flex items-center gap-1 px-1.5 py-0.5 bg-zinc-900 text-zinc-350 rounded font-mono text-[9px] border border-zinc-850">
                              {sk}
                              <button 
                                type="button" 
                                onClick={() => setNewExp({...newExp, skills_used: newExp.skills_used.filter(s => s !== sk)})}
                                className="hover:text-red-400 text-zinc-650 cursor-pointer"
                              >
                                <X className="w-2.5 h-2.5" />
                              </button>
                            </span>
                          ))}
                          <input 
                            type="text"
                            placeholder="Add skill tag"
                            value={expSkillInput}
                            onChange={e => setExpSkillInput(e.target.value)}
                            onKeyDown={e => {
                              if (e.key === "Enter") {
                                e.preventDefault();
                                const trimmed = expSkillInput.trim();
                                if (trimmed && !newExp.skills_used.includes(trimmed)) {
                                  setNewExp({...newExp, skills_used: [...newExp.skills_used, trimmed]});
                                }
                                setExpSkillInput("");
                              }
                            }}
                            className="bg-transparent border-none focus:outline-none text-zinc-200 text-[10px] px-2 min-w-[120px]"
                          />
                        </div>
                      </div>

                      <button 
                        type="submit"
                        disabled={isSaving}
                        className="py-2 px-4 bg-emerald-600 hover:bg-emerald-500 text-white font-bold rounded-lg transition-colors cursor-pointer"
                      >
                        Register Experience History
                      </button>
                    </form>
                  )}
                </div>
              </div>

              {/* Experience items list */}
              <div className="space-y-4">
                {isLoading ? (
                  <SkeletonLoader />
                ) : filteredExp.length === 0 ? (
                  <div className="p-12 text-center text-zinc-655 font-mono text-xs bg-[#0b0b0f] border border-zinc-900 rounded-2xl flex flex-col items-center justify-center gap-2">
                    <Briefcase className="w-8 h-8 text-zinc-700" />
                    <span>No professional experiences matching query.</span>
                  </div>
                ) : (
                  filteredExp.map(exp => (
                    <div key={exp.id} className="p-1.5 rounded-[1.25rem] bg-zinc-900/30 ring-1 ring-zinc-800/50 hover:ring-zinc-700/60 transition-all animate-fade-in">
                      <div className="bg-[#0b0b0f] rounded-[calc(1.25rem-0.375rem)] p-5 shadow-[inset_0_1px_1px_rgba(255,255,255,0.03)] flex items-start justify-between text-xs gap-4">
                        <div className="space-y-1 w-full">
                          <div className="flex items-center justify-between">
                            <h4 className="font-bold text-zinc-150 text-sm tracking-wide">{exp.role_title}</h4>
                            <span className="text-[9px] text-zinc-500 font-mono border border-zinc-850 px-2 py-0.5 rounded-full bg-zinc-950">
                              {exp.employment_type} • {exp.is_current ? "CURRENT" : "PAST"}
                            </span>
                          </div>
                          <p className="text-zinc-350 font-medium">{exp.company_name} • <span className="italic font-mono text-[11px] text-zinc-400">{exp.location}</span></p>
                          
                          {exp.description && (
                            <p className="text-zinc-450 leading-relaxed text-[11px] mt-2.5 bg-zinc-950/20 p-3 rounded-xl border border-zinc-900 font-mono">{exp.description}</p>
                          )}
                          
                          {exp.skills_used && exp.skills_used.length > 0 && (
                            <div className="flex flex-wrap gap-1 mt-3">
                              {exp.skills_used.map((sk, idx) => (
                                <span key={idx} className="text-[9px] bg-zinc-900/50 text-zinc-450 px-2 py-0.5 rounded font-mono border border-zinc-850">{sk}</span>
                              ))}
                            </div>
                          )}
                        </div>

                        <div className="flex items-center gap-1.5 shrink-0 ml-2">
                          <button 
                            onClick={() => openEditModal("experience", exp)}
                            className="p-2 rounded-lg bg-zinc-900 text-zinc-450 hover:text-emerald-400 hover:bg-zinc-855 transition-colors cursor-pointer border border-zinc-800/40"
                            title="Edit Entry"
                          >
                            <Edit className="w-3.5 h-3.5" />
                          </button>
                          <button 
                            onClick={() => exp.id && triggerDelete("experience", exp)}
                            className="p-2 rounded-lg bg-zinc-900 text-zinc-450 hover:text-red-400 hover:bg-zinc-855 transition-colors shrink-0 cursor-pointer border border-zinc-800/40"
                            title="Delete experience entry"
                          >
                            <Trash2 className="w-3.5 h-3.5" />
                          </button>
                        </div>
                      </div>
                    </div>
                  ))
                )}
              </div>

            </div>
          )}

          {/* TAB 6: Projects Details */}
          {activeTab === "projects" && (
            <div className="space-y-6">
              
              {/* Form trigger box */}
              <div className="p-1.5 rounded-[1.25rem] bg-zinc-900/30 ring-1 ring-zinc-800/50">
                <div className="bg-[#0b0b0f] rounded-[calc(1.25rem-0.375rem)] p-5 shadow-[inset_0_1px_1px_rgba(255,255,255,0.03)] text-xs">
                  <div className="flex items-center justify-between">
                    <h3 className="font-semibold text-xs text-zinc-200 uppercase tracking-wide flex items-center gap-2 font-mono">
                      <Code className="w-4 h-4 text-emerald-500" />
                      Candidate Personal Projects
                    </h3>
                    <button 
                      onClick={() => setShowProjForm(!showProjForm)}
                      className="py-1 px-3 bg-zinc-900 border border-zinc-800 text-zinc-300 font-bold rounded-lg hover:bg-zinc-850 transition-colors flex items-center gap-1 cursor-pointer"
                    >
                      <Plus className="w-3.5 h-3.5" />
                      <span>{showProjForm ? "Close Form" : "Add Project"}</span>
                    </button>
                  </div>

                  {showProjForm && (
                    <form onSubmit={handleAddProject} className="mt-5 space-y-4 border-t border-zinc-900 pt-5 text-xs animate-fade-in">
                      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                        <div>
                          <label className="block text-zinc-400 mb-1">Project Name</label>
                          <input 
                            type="text" 
                            required
                            placeholder="e.g. Polymarket AI Trading Agent"
                            value={newProj.project_name}
                            onChange={e => setNewProj({...newProj, project_name: e.target.value})}
                            className="w-full px-3 py-2 bg-zinc-950 border border-zinc-900 rounded-lg text-zinc-200 focus:outline-none"
                          />
                        </div>
                        <div className="grid grid-cols-2 gap-2">
                          <div>
                            <label className="block text-zinc-400 mb-1">Project URL</label>
                            <input 
                              type="url" 
                              placeholder="Live Link"
                              value={newProj.project_url}
                              onChange={e => setNewProj({...newProj, project_url: e.target.value})}
                              className="w-full px-3 py-2 bg-zinc-950 border border-zinc-900 rounded-lg text-zinc-250 focus:outline-none placeholder-zinc-700"
                            />
                          </div>
                          <div>
                            <label className="block text-zinc-400 mb-1">GitHub URL</label>
                            <input 
                              type="url" 
                              placeholder="Code Link"
                              value={newProj.github_url}
                              onChange={e => setNewProj({...newProj, github_url: e.target.value})}
                              className="w-full px-3 py-2 bg-zinc-950 border border-zinc-900 rounded-lg text-zinc-250 focus:outline-none placeholder-zinc-700"
                            />
                          </div>
                        </div>
                      </div>

                      <div>
                        <label className="block text-zinc-400 mb-1">Description</label>
                        <textarea 
                          rows={3}
                          placeholder="Completed AI trading platform for predictions..."
                          value={newProj.description}
                          onChange={e => setNewProj({...newProj, description: e.target.value})}
                          className="w-full px-3 py-2 bg-zinc-950 border border-zinc-900 rounded-lg text-zinc-200 focus:outline-none leading-relaxed font-mono text-[11px]"
                        />
                      </div>

                      {/* Tech stack tags */}
                      <div className="space-y-1.5">
                        <label className="block text-zinc-400 mb-1">Tech Stack (Press Enter to commit tag)</label>
                        <div className="flex flex-wrap gap-1 p-2 bg-zinc-950 border border-zinc-900 rounded-lg min-h-[35px] items-center">
                          {newProj.tech_stack.map(ts => (
                            <span key={ts} className="flex items-center gap-1 px-1.5 py-0.5 bg-zinc-900 text-zinc-350 rounded font-mono text-[9px] border border-zinc-850">
                              {ts}
                              <button 
                                type="button" 
                                onClick={() => setNewProj({...newProj, tech_stack: newProj.tech_stack.filter(s => s !== ts)})}
                                className="hover:text-red-400 text-zinc-650 cursor-pointer"
                              >
                                <X className="w-2.5 h-2.5" />
                              </button>
                            </span>
                          ))}
                          <input 
                            type="text"
                            placeholder="Add technology tag"
                            value={projStackInput}
                            onChange={e => setProjStackInput(e.target.value)}
                            onKeyDown={e => {
                              if (e.key === "Enter") {
                                e.preventDefault();
                                const trimmed = projStackInput.trim();
                                if (trimmed && !newProj.tech_stack.includes(trimmed)) {
                                  setNewProj({...newProj, tech_stack: [...newProj.tech_stack, trimmed]});
                                }
                                setProjStackInput("");
                              }
                            }}
                            className="bg-transparent border-none focus:outline-none text-zinc-200 text-[10px] px-2 min-w-[120px]"
                          />
                        </div>
                      </div>

                      <button 
                        type="submit"
                        disabled={isSaving}
                        className="py-2 px-4 bg-emerald-600 hover:bg-emerald-500 text-white font-bold rounded-lg transition-colors cursor-pointer"
                      >
                        Register Project Details
                      </button>
                    </form>
                  )}
                </div>
              </div>

              {/* Projects list */}
              <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                {isLoading ? (
                  <div className="col-span-2"><SkeletonLoader /></div>
                ) : filteredProj.length === 0 ? (
                  <div className="col-span-2 p-12 text-center text-zinc-650 font-mono text-xs bg-[#0b0b0f] border border-zinc-900 rounded-2xl flex flex-col items-center justify-center gap-2">
                    <Code className="w-8 h-8 text-zinc-700" />
                    <span>No projects match query parameters.</span>
                  </div>
                ) : (
                  filteredProj.map(proj => (
                    <div key={proj.id} className="p-1.5 rounded-[1.25rem] bg-zinc-900/30 ring-1 ring-zinc-800/50 hover:ring-zinc-700/60 transition-all flex flex-col justify-between text-xs animate-fade-in">
                      <div className="bg-[#0b0b0f] rounded-[calc(1.25rem-0.375rem)] p-5 shadow-[inset_0_1px_1px_rgba(255,255,255,0.03)] flex flex-col justify-between h-full gap-4">
                        <div className="space-y-2">
                          <div className="flex items-center justify-between">
                            <h4 className="font-bold text-zinc-150 text-sm truncate">{proj.project_name}</h4>
                            <div className="flex items-center gap-1 shrink-0">
                              <button 
                                onClick={() => openEditModal("project", proj)}
                                className="p-1.5 rounded bg-zinc-900 text-zinc-450 hover:text-emerald-400 hover:bg-zinc-850 transition-colors cursor-pointer border border-zinc-800/40"
                                title="Edit Project"
                              >
                                <Edit className="w-3.5 h-3.5" />
                              </button>
                              <button 
                                onClick={() => proj.id && triggerDelete("project", proj)}
                                className="p-1.5 rounded bg-zinc-900 text-zinc-450 hover:text-red-400 hover:bg-zinc-850 transition-colors shrink-0 cursor-pointer border border-zinc-800/40"
                                title="Delete Project"
                              >
                                <Trash2 className="w-3.5 h-3.5" />
                              </button>
                            </div>
                          </div>
                          
                          {proj.description && (
                            <p className="text-zinc-450 leading-relaxed text-[11px] font-mono bg-zinc-950/20 p-2.5 rounded-lg border border-zinc-900/50">{proj.description}</p>
                          )}
                        </div>

                        <div className="space-y-3">
                          {proj.tech_stack && proj.tech_stack.length > 0 && (
                            <div className="flex flex-wrap gap-1 border-b border-zinc-900/60 pb-3">
                              {proj.tech_stack.map((ts, idx) => (
                                <span key={idx} className="text-[9px] bg-zinc-900/60 text-emerald-400 px-2 py-0.5 rounded font-mono border border-zinc-850/50">{ts}</span>
                              ))}
                            </div>
                          )}

                          <div className="flex items-center gap-3.5 text-[10px] font-bold tracking-wider font-mono uppercase text-zinc-400 pt-1">
                            {proj.project_url && (
                              <a href={proj.project_url} target="_blank" rel="noreferrer" className="hover:text-emerald-450 transition-colors flex items-center gap-1">
                                <Globe className="w-3 h-3" />
                                <span>Live Demo</span>
                              </a>
                            )}
                            {proj.github_url && (
                              <a href={proj.github_url} target="_blank" rel="noreferrer" className="hover:text-emerald-450 transition-colors flex items-center gap-1">
                                <GitBranch className="w-3 h-3" />
                                <span>GitHub</span>
                              </a>
                            )}
                          </div>
                        </div>

                      </div>
                    </div>
                  ))
                )}
              </div>

            </div>
          )}

          {/* TAB 7: Skills Taxonomy */}
          {activeTab === "skills" && (
            <div className="space-y-6">
              
              {/* Skills addition form */}
              <div className="p-1.5 rounded-[1.25rem] bg-zinc-900/30 ring-1 ring-zinc-800/50">
                <form onSubmit={handleAddSkill} className="bg-[#0b0b0f] rounded-[calc(1.25rem-0.375rem)] p-5 shadow-[inset_0_1px_1px_rgba(255,255,255,0.03)] text-xs space-y-4">
                  <h3 className="font-semibold text-xs text-zinc-200 uppercase tracking-wide flex items-center gap-2 font-mono">
                    <BookOpen className="w-4 h-4 text-emerald-500" />
                    Skills Keyword Registry
                  </h3>

                  <div className="grid grid-cols-1 md:grid-cols-4 gap-4 items-end animate-fade-in">
                    <div>
                      <label className="block text-zinc-400 mb-1.5">Skill Name</label>
                      <input 
                        type="text" 
                        required
                        placeholder="e.g. FastAPI, Next.js, PyTorch"
                        value={newSkillName}
                        onChange={e => setNewSkillName(e.target.value)}
                        className="w-full px-3 py-2 bg-zinc-950 border border-zinc-900 rounded-lg text-zinc-250 focus:outline-none"
                      />
                    </div>
                    <div>
                      <label className="block text-zinc-400 mb-1.5">Proficiency Category</label>
                      <select 
                        value={newSkillCategory}
                        onChange={e => setNewSkillCategory(e.target.value)}
                        className="w-full px-3 py-2 bg-zinc-950 border border-zinc-900 rounded-lg text-zinc-250 focus:outline-none font-semibold"
                      >
                        {Object.entries(DB_TO_UI_CATEGORY_MAP).map(([dbVal, uiVal]) => (
                          <option key={dbVal} value={dbVal}>{uiVal}</option>
                        ))}
                      </select>
                    </div>
                    <div>
                      <label className="block text-zinc-400 mb-1.5">Skill Tier</label>
                      <select 
                        value={newSkillProficiency}
                        onChange={e => setNewSkillProficiency(e.target.value)}
                        className="w-full px-3 py-2 bg-zinc-950 border border-zinc-900 rounded-lg text-zinc-250 focus:outline-none font-semibold"
                      >
                        <option value="BEGINNER">Beginner</option>
                        <option value="INTERMEDIATE">Intermediate</option>
                        <option value="ADVANCED">Advanced / Expert</option>
                      </select>
                    </div>
                    <button 
                      type="submit"
                      disabled={isSaving}
                      className="py-2 px-4 bg-emerald-600 hover:bg-emerald-500 text-white font-bold rounded-lg transition-colors flex items-center justify-center gap-1.5 cursor-pointer h-[38px]"
                    >
                      <Plus className="w-4 h-4" />
                      Add Skill
                    </button>
                  </div>

                  <div className="flex items-center gap-2">
                    <input 
                      type="checkbox"
                      id="skill_is_primary"
                      checked={newSkillIsPrimary}
                      onChange={e => setNewSkillIsPrimary(e.target.checked)}
                      className="w-3.5 h-3.5 bg-zinc-950 rounded border-zinc-900 text-emerald-600 focus:ring-0 focus:ring-offset-0 cursor-pointer"
                    />
                    <label htmlFor="skill_is_primary" className="text-zinc-400 select-none cursor-pointer">Mark as primary candidate skill badge</label>
                  </div>

                </form>
              </div>

              {/* Skills list grouped by category: Double-Bezel grids */}
              <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                {isLoading ? (
                  <div className="col-span-2"><SkeletonLoader /></div>
                ) : SKILLS_CATEGORIES.map(category => {
                  const skills = filteredGroupedSkills[category] || [];
                  if (skills.length === 0) return null; // Only show non-empty categories

                  return (
                    <div key={category} className="p-1.5 rounded-[1.25rem] bg-zinc-900/30 ring-1 ring-zinc-800/50 hover:ring-zinc-700/50 transition-all flex flex-col justify-between">
                      <div className="bg-[#0b0b0f] rounded-[calc(1.25rem-0.375rem)] p-5 shadow-[inset_0_1px_1px_rgba(255,255,255,0.03)] h-full space-y-4">
                        <h4 className="font-bold text-zinc-300 text-xs tracking-wider border-b border-zinc-900 pb-2.5 font-mono uppercase text-emerald-500 flex items-center gap-2">
                          <Sparkles className="w-3.5 h-3.5" />
                          {category}
                        </h4>
                        
                        <div className="flex flex-wrap gap-2 pt-1">
                          {skills.map(skill => (
                            <span 
                              key={skill.id}
                              className="inline-flex items-center gap-2 px-2.5 py-1.5 rounded-xl bg-zinc-950 text-zinc-350 font-mono text-[10px] border border-zinc-900/80 transition-colors hover:border-zinc-800"
                            >
                              <span className={skill.is_primary ? "text-emerald-400 font-black shadow-emerald-950/20" : ""}>
                                {skill.skill_name}
                              </span>
                              <span className="text-zinc-750">|</span>
                              <span className="text-[9px] text-zinc-500 uppercase">{(skill.proficiency_level || "UNK").slice(0, 3)}</span>
                              
                              <div className="flex items-center gap-1 shrink-0 ml-1.5">
                                <button 
                                  type="button" 
                                  onClick={() => openEditModal("skill", skill)}
                                  className="hover:text-emerald-400 text-zinc-550 transition-colors cursor-pointer"
                                  title="Edit skill proficiency"
                                >
                                  <Edit className="w-2.5 h-2.5" />
                                </button>
                                <button 
                                  type="button" 
                                  onClick={() => handleDeleteSkill(skill.id, skill.skill_name)}
                                  className="hover:text-red-400 text-zinc-555 transition-colors cursor-pointer"
                                  title="Remove skill"
                                >
                                  <X className="w-2.5 h-2.5" />
                                </button>
                              </div>
                            </span>
                          ))}
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>

            </div>
          )}

          {/* TAB 8: Achievements & Awards (NEW!) */}
          {activeTab === "achievements" && (
            <div className="space-y-6">
              
              {/* Form trigger box */}
              <div className="p-1.5 rounded-[1.25rem] bg-zinc-900/30 ring-1 ring-zinc-800/50">
                <div className="bg-[#0b0b0f] rounded-[calc(1.25rem-0.375rem)] p-5 shadow-[inset_0_1px_1px_rgba(255,255,255,0.03)] text-xs">
                  <div className="flex items-center justify-between">
                    <h3 className="font-semibold text-xs text-zinc-200 uppercase tracking-wide flex items-center gap-2 font-mono">
                      <Trophy className="w-4 h-4 text-emerald-500" />
                      Achievements & Awards
                    </h3>
                    <button 
                      onClick={() => setShowAchForm(!showAchForm)}
                      className="py-1 px-3 bg-zinc-900 border border-zinc-800 text-zinc-300 font-bold rounded-lg hover:bg-zinc-850 transition-colors flex items-center gap-1 cursor-pointer"
                    >
                      <Plus className="w-3.5 h-3.5" />
                      <span>{showAchForm ? "Close Form" : "Add Achievement"}</span>
                    </button>
                  </div>

                  {showAchForm && (
                    <form onSubmit={handleAddAchievement} className="mt-5 space-y-4 border-t border-zinc-900 pt-5 text-xs animate-fade-in">
                      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                        <div className="md:col-span-2">
                          <label className="block text-zinc-400 mb-1">Title</label>
                          <input 
                            type="text" 
                            required
                            placeholder="e.g. JEE Mains 2022"
                            value={newAch.title}
                            onChange={e => setNewAch({...newAch, title: e.target.value})}
                            className="w-full px-3 py-2 bg-zinc-950 border border-zinc-900 rounded-lg text-zinc-200 focus:outline-none"
                          />
                        </div>
                        <div>
                          <label className="block text-zinc-400 mb-1">Year</label>
                          <input 
                            type="number" 
                            placeholder="e.g. 2022"
                            value={newAchYear}
                            onChange={e => setNewAchYear(e.target.value)}
                            className="w-full px-3 py-2 bg-zinc-950 border border-zinc-900 rounded-lg text-zinc-200 focus:outline-none font-mono"
                          />
                        </div>
                      </div>

                      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                        <div>
                          <label className="block text-zinc-400 mb-1">Issuer/Publisher</label>
                          <input 
                            type="text" 
                            placeholder="e.g. NTA (National Testing Agency)"
                            value={newAch.issuer}
                            onChange={e => setNewAch({...newAch, issuer: e.target.value})}
                            className="w-full px-3 py-2 bg-zinc-950 border border-zinc-900 rounded-lg text-zinc-250 focus:outline-none"
                          />
                        </div>
                        <div>
                          <label className="block text-zinc-400 mb-1">Reference URL</label>
                          <input 
                            type="url" 
                            placeholder="https://..."
                            value={newAch.url}
                            onChange={e => setNewAch({...newAch, url: e.target.value})}
                            className="w-full px-3 py-2 bg-zinc-950 border border-zinc-900 rounded-lg text-zinc-250 focus:outline-none placeholder-zinc-700"
                          />
                        </div>
                      </div>

                      <div>
                        <label className="block text-zinc-400 mb-1">Description</label>
                        <textarea 
                          rows={3}
                          placeholder="Top 3.7 Percentile score out of 900,000 candidates..."
                          value={newAch.description}
                          onChange={e => setNewAch({...newAch, description: e.target.value})}
                          className="w-full px-3 py-2 bg-zinc-950 border border-zinc-900 rounded-lg text-zinc-250 focus:outline-none leading-relaxed font-mono text-[11px]"
                        />
                      </div>

                      <button 
                        type="submit"
                        disabled={isSaving}
                        className="py-2 px-4 bg-emerald-600 hover:bg-emerald-500 text-white font-bold rounded-lg transition-colors cursor-pointer"
                      >
                        Add Achievement
                      </button>
                    </form>
                  )}
                </div>
              </div>

              {/* Achievements items list */}
              <div className="space-y-4">
                {isLoading ? (
                  <SkeletonLoader />
                ) : filteredAch.length === 0 ? (
                  <div className="p-12 text-center text-zinc-655 font-mono text-xs bg-[#0b0b0f] border border-zinc-900 rounded-2xl flex flex-col items-center justify-center gap-2">
                    <Trophy className="w-8 h-8 text-zinc-700" />
                    <span>No achievements parsed or manual entries found.</span>
                  </div>
                ) : (
                  filteredAch.map(ach => {
                    const year = getYearStr(ach.date_achieved);
                    return (
                      <div key={ach.id} className="p-1.5 rounded-[1.25rem] bg-zinc-900/30 ring-1 ring-zinc-800/50 hover:ring-zinc-700/60 transition-all animate-fade-in">
                        <div className="bg-[#0b0b0f] rounded-[calc(1.25rem-0.375rem)] p-5 shadow-[inset_0_1px_1px_rgba(255,255,255,0.03)] flex items-start justify-between text-xs gap-4">
                          <div className="space-y-1 w-full">
                            <div className="flex items-center justify-between">
                              <h4 className="font-bold text-zinc-150 text-sm tracking-wide">{ach.title}</h4>
                              {year && (
                                <span className="text-[10px] text-emerald-500 font-mono font-bold border border-emerald-950 px-2.5 py-0.5 rounded-full bg-emerald-950/20">
                                  Year: {year}
                                </span>
                              )}
                            </div>
                            {ach.issuer && <p className="text-zinc-350 font-medium font-mono text-[11px]">{ach.issuer}</p>}
                            
                            {ach.description && (
                              <p className="text-zinc-455 leading-relaxed text-[11px] mt-2.5 bg-zinc-950/20 p-3 rounded-xl border border-zinc-900 font-mono">{ach.description}</p>
                            )}
                            
                            {ach.url && (
                              <a href={ach.url} target="_blank" rel="noreferrer" className="hover:text-emerald-400 transition-colors flex items-center gap-1 text-[10px] font-mono mt-3 uppercase text-zinc-400">
                                <ExternalLink className="w-3.5 h-3.5" />
                                <span>Reference URL</span>
                              </a>
                            )}
                          </div>

                          <div className="flex items-center gap-1.5 shrink-0 ml-2">
                            <button 
                              onClick={() => openEditModal("achievement", ach)}
                              className="p-2 rounded-lg bg-zinc-900 text-zinc-450 hover:text-emerald-400 hover:bg-zinc-850 transition-colors cursor-pointer border border-zinc-800/40"
                              title="Edit Entry"
                            >
                              <Edit className="w-3.5 h-3.5" />
                            </button>
                            <button 
                              onClick={() => ach.id && triggerDelete("achievement", ach)}
                              className="p-2 rounded-lg bg-zinc-900 text-zinc-450 hover:text-red-400 hover:bg-zinc-850 transition-colors shrink-0 cursor-pointer border border-zinc-800/40"
                              title="Delete Entry"
                            >
                              <Trash2 className="w-3.5 h-3.5" />
                            </button>
                          </div>
                        </div>
                      </div>
                    );
                  })
                )}
              </div>

            </div>
          )}

        </div>

      </div>

      {/* FLOAT OVERLAY MODALS */}

      {/* 1. EDIT MODAL */}
      {editType && editItem && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-zinc-950/80 backdrop-blur-md animate-fade-in">
          <div className="p-1.5 rounded-[1.25rem] bg-zinc-900/60 ring-1 ring-zinc-800 w-full max-w-xl shadow-2xl">
            <div className="bg-[#0b0b0f] rounded-[calc(1.25rem-0.375rem)] p-6 shadow-[inset_0_1px_1px_rgba(255,255,255,0.03)] space-y-5 text-xs text-zinc-200">
              
              <div className="flex items-center justify-between border-b border-zinc-900 pb-3">
                <h3 className="text-sm font-bold uppercase tracking-wider text-emerald-400 font-mono">
                  Edit {editType.charAt(0).toUpperCase() + editType.slice(1)} Details
                </h3>
                <button onClick={() => { setEditType(null); setEditItem(null); }} className="text-zinc-500 hover:text-zinc-200 cursor-pointer">
                  <X className="w-4 h-4" />
                </button>
              </div>

              <form onSubmit={handleSaveEdit} className="space-y-4">
                
                {/* Education Modal Fields */}
                {editType === "education" && (
                  <div className="space-y-4">
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                      <div>
                        <label className="block text-zinc-400 mb-1">Institution Name</label>
                        <input 
                          type="text" 
                          required
                          value={editEduInst}
                          onChange={e => setEditEduInst(e.target.value)}
                          className="w-full px-3 py-2 bg-zinc-950 border border-zinc-900 rounded-lg text-zinc-200 focus:outline-none"
                        />
                      </div>
                      <div>
                        <label className="block text-zinc-400 mb-1">Location</label>
                        <input 
                          type="text" 
                          value={editEduLoc}
                          onChange={e => setEditEduLoc(e.target.value)}
                          className="w-full px-3 py-2 bg-zinc-950 border border-zinc-900 rounded-lg text-zinc-200 focus:outline-none"
                        />
                      </div>
                    </div>

                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                      <div>
                        <label className="block text-zinc-400 mb-1">Degree Title</label>
                        <input 
                          type="text" 
                          required
                          value={editItem.degree || ""}
                          onChange={e => setEditItem({ ...editItem, degree: e.target.value })}
                          className="w-full px-3 py-2 bg-zinc-950 border border-zinc-900 rounded-lg text-zinc-200 focus:outline-none"
                        />
                      </div>
                      <div>
                        <label className="block text-zinc-400 mb-1">Field of Study</label>
                        <input 
                          type="text" 
                          value={editItem.field_of_study || ""}
                          onChange={e => setEditItem({ ...editItem, field_of_study: e.target.value })}
                          className="w-full px-3 py-2 bg-zinc-950 border border-zinc-900 rounded-lg text-zinc-200 focus:outline-none"
                        />
                      </div>
                    </div>

                    <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
                      <div>
                        <label className="block text-zinc-400 mb-1">Type</label>
                        <select 
                          value={editItem.education_type || "BTECH"}
                          onChange={e => setEditItem({ ...editItem, education_type: e.target.value })}
                          className="w-full px-3 py-2 bg-zinc-950 border border-zinc-900 rounded-lg text-zinc-200 focus:outline-none"
                        >
                          <option value="BTECH">B.Tech / B.E.</option>
                          <option value="MTECH">M.Tech / M.E.</option>
                          <option value="PHD">Ph.D.</option>
                          <option value="HIGH_SCHOOL">High School</option>
                          <option value="OTHER">Other</option>
                        </select>
                      </div>
                      <div>
                        <label className="block text-zinc-400 mb-1">CGPA</label>
                        <input 
                          type="number" 
                          step="0.01" 
                          value={editItem.cgpa || ""}
                          onChange={e => setEditItem({ ...editItem, cgpa: parseFloat(e.target.value) || undefined })}
                          className="w-full px-3 py-2 bg-zinc-950 border border-zinc-900 rounded-lg text-zinc-200 focus:outline-none font-mono"
                        />
                      </div>
                      <div>
                        <label className="block text-zinc-400 mb-1">Start Year</label>
                        <input 
                          type="number" 
                          value={editItem.start_year || ""}
                          onChange={e => setEditItem({ ...editItem, start_year: parseInt(e.target.value) || undefined })}
                          className="w-full px-3 py-2 bg-zinc-950 border border-zinc-900 rounded-lg text-zinc-200 focus:outline-none font-mono"
                        />
                      </div>
                      <div>
                        <label className="block text-zinc-400 mb-1">End Year</label>
                        <input 
                          type="number" 
                          value={editItem.end_year || ""}
                          onChange={e => setEditItem({ ...editItem, end_year: parseInt(e.target.value) || undefined })}
                          className="w-full px-3 py-2 bg-zinc-950 border border-zinc-900 rounded-lg text-zinc-200 focus:outline-none font-mono"
                        />
                      </div>
                    </div>
                  </div>
                )}

                {/* Experience Modal Fields */}
                {editType === "experience" && (
                  <div className="space-y-4">
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                      <div>
                        <label className="block text-zinc-400 mb-1">Company Name</label>
                        <input 
                          type="text" 
                          required
                          value={editItem.company_name || ""}
                          onChange={e => setEditItem({ ...editItem, company_name: e.target.value })}
                          className="w-full px-3 py-2 bg-zinc-950 border border-zinc-900 rounded-lg text-zinc-200 focus:outline-none"
                        />
                      </div>
                      <div>
                        <label className="block text-zinc-400 mb-1">Role Title</label>
                        <input 
                          type="text" 
                          required
                          value={editItem.role_title || ""}
                          onChange={e => setEditItem({ ...editItem, role_title: e.target.value })}
                          className="w-full px-3 py-2 bg-zinc-950 border border-zinc-900 rounded-lg text-zinc-200 focus:outline-none"
                        />
                      </div>
                    </div>

                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                      <div>
                        <label className="block text-zinc-400 mb-1">Location</label>
                        <input 
                          type="text" 
                          value={editItem.location || ""}
                          onChange={e => setEditItem({ ...editItem, location: e.target.value })}
                          className="w-full px-3 py-2 bg-zinc-950 border border-zinc-900 rounded-lg text-zinc-200 focus:outline-none"
                        />
                      </div>
                      <div>
                        <label className="block text-zinc-400 mb-1">Employment Type</label>
                        <select 
                          value={editItem.employment_type || "FULL_TIME"}
                          onChange={e => setEditItem({ ...editItem, employment_type: e.target.value })}
                          className="w-full px-3 py-2 bg-zinc-950 border border-zinc-900 rounded-lg text-zinc-200 focus:outline-none font-semibold"
                        >
                          <option value="FULL_TIME">Full Time</option>
                          <option value="INTERNSHIP">Internship</option>
                          <option value="CONTRACT">Contract</option>
                          <option value="PART_TIME">Part Time</option>
                        </select>
                      </div>
                    </div>

                    <div>
                      <label className="block text-zinc-400 mb-1">Description</label>
                      <textarea 
                        rows={3}
                        value={editItem.description || ""}
                        onChange={e => setEditItem({ ...editItem, description: e.target.value })}
                        className="w-full px-3 py-2 bg-zinc-950 border border-zinc-900 rounded-lg text-zinc-200 focus:outline-none leading-relaxed font-mono"
                      />
                    </div>

                    <div>
                      <label className="block text-zinc-400 mb-1">Skills Used (comma-separated)</label>
                      <input 
                        type="text" 
                        value={editExpSkills}
                        onChange={e => setEditExpSkills(e.target.value)}
                        className="w-full px-3 py-2 bg-zinc-950 border border-zinc-900 rounded-lg text-zinc-200 focus:outline-none font-mono"
                      />
                    </div>
                  </div>
                )}

                {/* Project Modal Fields */}
                {editType === "project" && (
                  <div className="space-y-4">
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                      <div>
                        <label className="block text-zinc-400 mb-1">Project Name</label>
                        <input 
                          type="text" 
                          required
                          value={editItem.project_name || ""}
                          onChange={e => setEditItem({ ...editItem, project_name: e.target.value })}
                          className="w-full px-3 py-2 bg-zinc-950 border border-zinc-900 rounded-lg text-zinc-200 focus:outline-none"
                        />
                      </div>
                      <div className="grid grid-cols-2 gap-2">
                        <div>
                          <label className="block text-zinc-400 mb-1">Project URL</label>
                          <input 
                            type="url" 
                            value={editItem.project_url || ""}
                            onChange={e => setEditItem({ ...editItem, project_url: e.target.value })}
                            className="w-full px-3 py-2 bg-zinc-950 border border-zinc-900 rounded-lg text-zinc-200 focus:outline-none font-mono"
                          />
                        </div>
                        <div>
                          <label className="block text-zinc-400 mb-1">GitHub URL</label>
                          <input 
                            type="url" 
                            value={editItem.github_url || ""}
                            onChange={e => setEditItem({ ...editItem, github_url: e.target.value })}
                            className="w-full px-3 py-2 bg-zinc-950 border border-zinc-900 rounded-lg text-zinc-200 focus:outline-none font-mono"
                          />
                        </div>
                      </div>
                    </div>

                    <div>
                      <label className="block text-zinc-400 mb-1">Description</label>
                      <textarea 
                        rows={3}
                        value={editItem.description || ""}
                        onChange={e => setEditItem({ ...editItem, description: e.target.value })}
                        className="w-full px-3 py-2 bg-zinc-950 border border-zinc-900 rounded-lg text-zinc-200 focus:outline-none leading-relaxed font-mono"
                      />
                    </div>

                    <div>
                      <label className="block text-zinc-400 mb-1">Tech Stack (comma-separated)</label>
                      <input 
                        type="text" 
                        value={editProjStack}
                        onChange={e => setEditProjStack(e.target.value)}
                        className="w-full px-3 py-2 bg-zinc-950 border border-zinc-900 rounded-lg text-zinc-200 focus:outline-none font-mono"
                      />
                    </div>
                  </div>
                )}

                {/* Skill Modal Fields */}
                {editType === "skill" && (
                  <div className="space-y-4">
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                      <div>
                        <label className="block text-zinc-400 mb-1">Skill Name</label>
                        <input 
                          type="text" 
                          required
                          value={editItem.skill_name || ""}
                          onChange={e => setEditItem({ ...editItem, skill_name: e.target.value })}
                          className="w-full px-3 py-2 bg-zinc-950 border border-zinc-900 rounded-lg text-zinc-250 focus:outline-none focus:border-emerald-500 font-semibold"
                        />
                      </div>
                      <div>
                        <label className="block text-zinc-400 mb-1">Proficiency Category</label>
                        <select 
                          value={editItem.category || "Programming Languages"}
                          onChange={e => setEditItem({ ...editItem, category: e.target.value })}
                          className="w-full px-3 py-2 bg-zinc-950 border border-zinc-900 rounded-lg text-zinc-250 focus:outline-none font-semibold"
                        >
                          {Object.entries(DB_TO_UI_CATEGORY_MAP).map(([dbVal, uiVal]) => (
                            <option key={dbVal} value={dbVal}>{uiVal}</option>
                          ))}
                        </select>
                      </div>
                    </div>

                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                      <div>
                        <label className="block text-zinc-400 mb-1">Proficiency Tier</label>
                        <select 
                          value={editItem.proficiency_level || "INTERMEDIATE"}
                          onChange={e => setEditItem({ ...editItem, proficiency_level: e.target.value })}
                          className="w-full px-3 py-2 bg-zinc-950 border border-zinc-900 rounded-lg text-zinc-250 focus:outline-none font-semibold"
                        >
                          <option value="BEGINNER">Beginner</option>
                          <option value="INTERMEDIATE">Intermediate</option>
                          <option value="ADVANCED">Advanced / Expert</option>
                        </select>
                      </div>
                      <div className="flex items-center gap-2 mt-5">
                        <input 
                          type="checkbox"
                          id="edit_skill_primary"
                          checked={editItem.is_primary || false}
                          onChange={e => setEditItem({ ...editItem, is_primary: e.target.checked })}
                          className="w-3.5 h-3.5 bg-zinc-950 rounded border-zinc-900 text-emerald-600 focus:ring-0 cursor-pointer"
                        />
                        <label htmlFor="edit_skill_primary" className="text-zinc-400 select-none cursor-pointer">Primary skill badge</label>
                      </div>
                    </div>
                  </div>
                )}

                {/* Achievement Modal Fields */}
                {editType === "achievement" && (
                  <div className="space-y-4">
                    <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                      <div className="md:col-span-2">
                        <label className="block text-zinc-400 mb-1">Title</label>
                        <input 
                          type="text" 
                          required
                          value={editItem.title || ""}
                          onChange={e => setEditItem({ ...editItem, title: e.target.value })}
                          className="w-full px-3 py-2 bg-zinc-950 border border-zinc-900 rounded-lg text-zinc-250 focus:outline-none"
                        />
                      </div>
                      <div>
                        <label className="block text-zinc-400 mb-1">Year</label>
                        <input 
                          type="number" 
                          value={editAchYear}
                          onChange={e => setEditAchYear(e.target.value)}
                          className="w-full px-3 py-2 bg-zinc-950 border border-zinc-900 rounded-lg text-zinc-200 focus:outline-none font-mono"
                        />
                      </div>
                    </div>

                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                      <div>
                        <label className="block text-zinc-400 mb-1">Issuer/Publisher</label>
                        <input 
                          type="text" 
                          value={editItem.issuer || ""}
                          onChange={e => setEditItem({ ...editItem, issuer: e.target.value })}
                          className="w-full px-3 py-2 bg-zinc-950 border border-zinc-900 rounded-lg text-zinc-250 focus:outline-none"
                        />
                      </div>
                      <div>
                        <label className="block text-zinc-400 mb-1">Reference URL</label>
                        <input 
                          type="url" 
                          value={editItem.url || ""}
                          onChange={e => setEditItem({ ...editItem, url: e.target.value })}
                          className="w-full px-3 py-2 bg-zinc-950 border border-zinc-900 rounded-lg text-zinc-250 focus:outline-none font-mono"
                        />
                      </div>
                    </div>

                    <div>
                      <label className="block text-zinc-400 mb-1">Description</label>
                      <textarea 
                        rows={3}
                        value={editItem.description || ""}
                        onChange={e => setEditItem({ ...editItem, description: e.target.value })}
                        className="w-full px-3 py-2 bg-zinc-950 border border-zinc-900 rounded-lg text-zinc-250 focus:outline-none leading-relaxed font-mono"
                      />
                    </div>
                  </div>
                )}

                {/* Modal actions */}
                <div className="flex items-center justify-end gap-3 pt-3 border-t border-zinc-900">
                  <button 
                    type="button" 
                    onClick={() => { setEditType(null); setEditItem(null); }}
                    className="py-2 px-4 bg-zinc-900 hover:bg-zinc-850 text-zinc-400 font-semibold rounded-lg transition-colors cursor-pointer"
                  >
                    Cancel
                  </button>
                  <button 
                    type="submit" 
                    disabled={isSaving}
                    className="py-2 px-4 bg-emerald-600 hover:bg-emerald-500 text-white font-bold rounded-lg transition-all cursor-pointer shadow-[0_0_12px_rgba(16,185,129,0.15)]"
                  >
                    Save Changes
                  </button>
                </div>

              </form>

            </div>
          </div>
        </div>
      )}

      {/* 2. DELETE CONFIRMATION DIALOG */}
      {deleteConfirmType && deleteConfirmItem && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-zinc-950/80 backdrop-blur-md animate-fade-in">
          <div className="p-1.5 rounded-[1.25rem] bg-zinc-900/60 ring-1 ring-zinc-800 w-full max-w-sm shadow-2xl">
            <div className="bg-[#0b0b0f] rounded-[calc(1.25rem-0.375rem)] p-6 shadow-[inset_0_1px_1px_rgba(255,255,255,0.03)] space-y-5 text-xs text-zinc-200">
              
              <div className="flex items-center gap-2.5 text-red-500 font-mono font-bold uppercase tracking-wide">
                <AlertCircle className="w-5 h-5 shrink-0" />
                <span>Confirm Deletion</span>
              </div>

              <p className="text-zinc-400 leading-relaxed font-mono">
                Are you sure you want to permanently delete this {deleteConfirmType} record? This action cannot be undone.
              </p>

              <div className="flex items-center justify-end gap-3 pt-3 border-t border-zinc-900">
                <button 
                  type="button" 
                  onClick={() => { setDeleteConfirmType(null); setDeleteConfirmItem(null); }}
                  className="py-2 px-4 bg-zinc-900 hover:bg-zinc-850 text-zinc-450 font-semibold rounded-lg transition-colors cursor-pointer"
                >
                  Cancel
                </button>
                <button 
                  type="button" 
                  onClick={handleConfirmDelete}
                  disabled={isSaving}
                  className="py-2 px-4 bg-red-650 hover:bg-red-550 text-white font-bold rounded-lg transition-all cursor-pointer shadow-[0_0_12px_rgba(220,38,38,0.15)] animate-pulse"
                >
                  Confirm Delete
                </button>
              </div>

            </div>
          </div>
        </div>
      )}

      {/* 3. RESTORE PREVIEW MODAL */}
      {showRestoreModal && backupPreview && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-zinc-950/80 backdrop-blur-md animate-fade-in">
          <div className="p-1.5 rounded-[1.25rem] bg-zinc-900/60 ring-1 ring-zinc-800 w-full max-w-md shadow-2xl">
            <div className="bg-[#0b0b0f] rounded-[calc(1.25rem-0.375rem)] p-6 shadow-[inset_0_1px_1px_rgba(255,255,255,0.03)] space-y-5 text-xs text-zinc-200">
              
              <div className="flex items-center justify-between border-b border-zinc-900 pb-3">
                <h3 className="text-sm font-bold uppercase tracking-wider text-amber-400 font-mono flex items-center gap-2">
                  <Archive className="w-4 h-4 text-amber-500" />
                  <span>Restore Preview</span>
                </h3>
                <button 
                  onClick={() => { setShowRestoreModal(false); setBackupFile(null); setBackupPreview(null); }} 
                  className="text-zinc-500 hover:text-zinc-200 cursor-pointer"
                >
                  <X className="w-4 h-4" />
                </button>
              </div>

              <div className="space-y-4">
                <div className="p-3 bg-amber-950/10 border border-amber-900/30 rounded-xl space-y-1">
                  <div className="flex items-center gap-2 text-amber-500 font-mono font-bold text-[10px] uppercase tracking-wider">
                    <ShieldCheck className="w-4 h-4" />
                    <span>Merge-Only Restore Mode</span>
                  </div>
                  <p className="text-zinc-400 leading-relaxed text-[11px] font-mono">
                    This backup will be merged into your current profile. Existing records will be updated with missing info, and new records will be added. <strong>No data will be deleted or overwritten.</strong>
                  </p>
                </div>

                <div className="grid grid-cols-2 gap-2 text-zinc-400 font-mono text-[11px] bg-zinc-950/40 p-3 rounded-xl border border-zinc-900">
                  <div>
                    <span className="text-zinc-500">Backup Date:</span>
                    <div className="text-zinc-350 font-bold mt-0.5">
                      {backupPreview.exported_at && backupPreview.exported_at !== "unknown" 
                        ? new Date(backupPreview.exported_at).toLocaleString() 
                        : "Unknown Date"}
                    </div>
                  </div>
                  <div>
                    <span className="text-zinc-500">Backup Version:</span>
                    <div className="text-zinc-350 font-bold mt-0.5">
                      v{backupPreview.version || "1.0"}
                    </div>
                  </div>
                </div>

                <div className="space-y-2">
                  <h4 className="font-mono text-zinc-400 uppercase tracking-wider text-[10px] font-bold">Records to Import:</h4>
                  <div className="grid grid-cols-2 gap-2">
                    <div className="flex items-center justify-between p-2.5 bg-zinc-900/30 rounded-lg border border-zinc-800/40 font-mono text-xs">
                      <span className="flex items-center gap-1.5 text-zinc-400">
                        <GraduationCap className="w-3.5 h-3.5 text-zinc-500" />
                        <span>Education</span>
                      </span>
                      <span className="font-bold text-zinc-200">{backupPreview.counts?.education || 0}</span>
                    </div>

                    <div className="flex items-center justify-between p-2.5 bg-zinc-900/30 rounded-lg border border-zinc-800/40 font-mono text-xs">
                      <span className="flex items-center gap-1.5 text-zinc-400">
                        <Briefcase className="w-3.5 h-3.5 text-zinc-500" />
                        <span>Experience</span>
                      </span>
                      <span className="font-bold text-zinc-200">{backupPreview.counts?.experience || 0}</span>
                    </div>

                    <div className="flex items-center justify-between p-2.5 bg-zinc-900/30 rounded-lg border border-zinc-800/40 font-mono text-xs">
                      <span className="flex items-center gap-1.5 text-zinc-400">
                        <Code className="w-3.5 h-3.5 text-zinc-500" />
                        <span>Projects</span>
                      </span>
                      <span className="font-bold text-zinc-200">{backupPreview.counts?.projects || 0}</span>
                    </div>

                    <div className="flex items-center justify-between p-2.5 bg-zinc-900/30 rounded-lg border border-zinc-800/40 font-mono text-xs">
                      <span className="flex items-center gap-1.5 text-zinc-400">
                        <Sliders className="w-3.5 h-3.5 text-zinc-500" />
                        <span>Skills</span>
                      </span>
                      <span className="font-bold text-zinc-200">{backupPreview.counts?.skills || 0}</span>
                    </div>

                    <div className="flex items-center justify-between p-2.5 bg-zinc-900/30 rounded-lg border border-zinc-800/40 font-mono text-xs">
                      <span className="flex items-center gap-1.5 text-zinc-400">
                        <Trophy className="w-3.5 h-3.5 text-zinc-500" />
                        <span>Achievements</span>
                      </span>
                      <span className="font-bold text-zinc-200">{backupPreview.counts?.achievements || 0}</span>
                    </div>

                    <div className="flex items-center justify-between p-2.5 bg-zinc-900/30 rounded-lg border border-zinc-800/40 font-mono text-xs">
                      <span className="flex items-center gap-1.5 text-zinc-400">
                        <FileJson className="w-3.5 h-3.5 text-zinc-500" />
                        <span>Resumes</span>
                      </span>
                      <span className="font-bold text-zinc-200">{backupPreview.counts?.resumes || 0}</span>
                    </div>
                  </div>
                </div>
              </div>

              <div className="flex items-center justify-end gap-3 pt-3 border-t border-zinc-900">
                <button 
                  type="button" 
                  onClick={() => { setShowRestoreModal(false); setBackupFile(null); setBackupPreview(null); }}
                  className="py-2 px-4 bg-zinc-900 hover:bg-zinc-850 text-zinc-450 hover:text-zinc-200 font-semibold rounded-lg transition-colors cursor-pointer border border-zinc-800/40 font-mono"
                  disabled={isRestoring}
                >
                  Cancel
                </button>
                <button 
                  type="button" 
                  onClick={handleConfirmRestore}
                  disabled={isRestoring}
                  className="py-2 px-5 bg-amber-600 hover:bg-amber-500 text-white font-bold rounded-lg transition-all cursor-pointer shadow-[0_0_12px_rgba(245,158,11,0.15)] flex items-center justify-center gap-2 font-mono uppercase tracking-wide disabled:opacity-50"
                >
                  {isRestoring ? (
                    <>
                      <Loader2 className="w-4 h-4 animate-spin text-white" />
                      <span>Restoring...</span>
                    </>
                  ) : (
                    <>
                      <RotateCcw className="w-4 h-4" />
                      <span>Confirm Merge</span>
                    </>
                  )}
                </button>
              </div>

            </div>
          </div>
        </div>
      )}

    </div>
  );
}
