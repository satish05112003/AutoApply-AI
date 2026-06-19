import { create } from "zustand";
import { API_BASE } from "@/config";

interface AppState {
  token: string | null;
  user: any | null;
  applications: any[];
  stats: {
    shortlisted: number;
    applied: number;
    failed: number;
    avg_match_score: number;
    success_rate: number;
    status_distribution: Record<string, number>;
  };
  logs: string[];
  sheetsStatus: {
    linked: boolean;
    spreadsheet_url: string | null;
    spreadsheet_id: string | null;
    last_sync_time: string | null;
  };
  agentStatus: {
    discovery_running: boolean;
    auto_apply_running: boolean;
    email_monitoring_running: boolean;
    agent_mode: string;
    agent_enabled: boolean;
  } | null;
  
  // Actions
  setToken: (token: string | null) => void;
  setUser: (user: any | null) => void;
  login: (email: string, password_plain: string) => Promise<boolean>;
  logout: () => void;
  fetchProfile: () => Promise<void>;
  fetchApplications: () => Promise<void>;
  fetchStats: () => Promise<void>;
  approveApplication: (id: string) => Promise<boolean>;
  rejectApplication: (id: string) => Promise<boolean>;
  updateApplicationAnswers: (id: string, payload: { generated_answers?: any; cover_letter?: string }) => Promise<boolean>;
  fetchSheetsStatus: () => Promise<void>;
  initializeSheets: () => Promise<boolean>;
  fetchAgentStatus: () => Promise<void>;
  startDiscovery: () => Promise<boolean>;
  stopDiscovery: () => Promise<boolean>;
  startAutoApply: () => Promise<boolean>;
  stopAutoApply: () => Promise<boolean>;
  startEmailMonitoring: () => Promise<boolean>;
  stopEmailMonitoring: () => Promise<boolean>;
  syncSheets: () => Promise<boolean>;
  refreshJobs: () => Promise<boolean>;
  addLogLine: (message: string) => void;
  clearLogs: () => void;
}

export const useStore = create<AppState>((set, get) => ({
  token: typeof window !== "undefined" ? localStorage.getItem("token") : null,
  user: null,
  applications: [],
  stats: {
    shortlisted: 0,
    applied: 0,
    failed: 0,
    avg_match_score: 0,
    success_rate: 0,
    status_distribution: {}
  },
  logs: [
    "[System] Agent pipeline listening for events...",
    "[System] Connect your Google sheet to activate tracking sync."
  ],
  sheetsStatus: {
    linked: false,
    spreadsheet_url: null,
    spreadsheet_id: null,
    last_sync_time: null
  },
  agentStatus: null,

  setToken: (token) => {
    if (token) localStorage.setItem("token", token);
    else localStorage.removeItem("token");
    set({ token });
  },
  
  setUser: (user) => set({ user }),

  login: async (email, password) => {
    const endpoint = `${API_BASE}/auth/login`;
    console.log(`[Store Debug] Initiating login request to ${endpoint}`, { email });
    try {
      const res = await fetch(endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, password })
      });
      
      console.log(`[Store Debug] Login response status: ${res.status}`);
      
      if (res.status === 200) {
        const data = await res.json();
        console.log(`[Store Debug] Login successful. Saving token and fetching profile...`);
        get().setToken(data.access_token);
        await get().fetchProfile();
        return true;
      } else {
        try {
          const errBody = await res.json();
          console.error(`[Store Debug] Login failed. Response body:`, errBody);
        } catch (_) {
          console.error(`[Store Debug] Login failed. Could not parse response body.`);
        }
        return false;
      }
    } catch (e) {
      console.error(`[Store Debug] Network or unexpected error during login:`, e);
      return false;
    }
  },

  logout: () => {
    console.log(`[Store Debug] Initiating logout, clearing local state`);
    get().setToken(null);
    set({ user: null, applications: [], logs: [] });
  },

  fetchProfile: async () => {
    const token = get().token;
    if (!token) {
      console.warn(`[Store Debug] fetchProfile called but no auth token found.`);
      return;
    }
    const endpoint = `${API_BASE}/auth/me`;
    console.log(`[Store Debug] Fetching profile from ${endpoint}`);
    try {
      const res = await fetch(endpoint, {
        headers: { "Authorization": `Bearer ${token}` }
      });
      
      console.log(`[Store Debug] fetchProfile response status: ${res.status}`);
      
      if (res.status === 200) {
        const user = await res.json();
        console.log(`[Store Debug] fetchProfile successful. User:`, user);
        set({ user });
      } else {
        console.warn(`[Store Debug] fetchProfile returned non-200. Logging out candidate.`);
        try {
          const errBody = await res.json();
          console.warn(`[Store Debug] error response body:`, errBody);
        } catch (_) {}
        get().logout();
      }
    } catch (e) {
      console.error(`[Store Debug] Network error fetching user profile:`, e);
    }
  },

  fetchApplications: async () => {
    const token = get().token;
    if (!token) return;
    try {
      const res = await fetch(`${API_BASE}/applications`, {
        headers: { "Authorization": `Bearer ${token}` }
      });
      if (res.status === 200) {
        const apps = await res.json();
        set({ applications: apps });
      }
    } catch (e) {
      console.error(e);
    }
  },

  fetchStats: async () => {
    const token = get().token;
    if (!token) return;
    try {
      const res = await fetch(`${API_BASE}/analytics/overview`, {
        headers: { "Authorization": `Bearer ${token}` }
      });
      if (res.status === 200) {
        const stats = await res.json();
        set({ stats });
      }
    } catch (e) {
      console.error(e);
    }
  },

  approveApplication: async (id) => {
    const token = get().token;
    if (!token) return false;
    try {
      const res = await fetch(`${API_BASE}/applications/${id}/approve`, {
        method: "POST",
        headers: { "Authorization": `Bearer ${token}` }
      });
      if (res.status === 200) {
        await get().fetchApplications();
        get().addLogLine(`[User] Approved submission execution for app ID: ${id}`);
        return true;
      }
      return false;
    } catch (e) {
      console.error(e);
      return false;
    }
  },

  rejectApplication: async (id) => {
    const token = get().token;
    if (!token) return false;
    try {
      const res = await fetch(`${API_BASE}/applications/${id}/reject`, {
        method: "POST",
        headers: { "Authorization": `Bearer ${token}` }
      });
      if (res.status === 200) {
        await get().fetchApplications();
        get().addLogLine(`[User] Dismissed application ID: ${id}`);
        return true;
      }
      return false;
    } catch (e) {
      console.error(e);
      return false;
    }
  },

  updateApplicationAnswers: async (id, payload) => {
    const token = get().token;
    if (!token) return false;
    try {
      const res = await fetch(`${API_BASE}/applications/${id}/answers`, {
        method: "PUT",
        headers: { 
          "Authorization": `Bearer ${token}`,
          "Content-Type": "application/json"
        },
        body: JSON.stringify(payload)
      });
      if (res.status === 200) {
        await get().fetchApplications();
        get().addLogLine(`[User] Updated answers/cover letter for application ID: ${id}`);
        return true;
      }
      return false;
    } catch (e) {
      console.error(e);
      return false;
    }
  },

  fetchSheetsStatus: async () => {
    const token = get().token;
    if (!token) return;
    try {
      const res = await fetch(`${API_BASE}/sheets/status`, {
        headers: { "Authorization": `Bearer ${token}` }
      });
      if (res.status === 200) {
        const data = await res.json();
        set({ sheetsStatus: data });
      }
    } catch (e) {
      console.error(e);
    }
  },

  initializeSheets: async () => {
    const token = get().token;
    if (!token) return false;
    try {
      const res = await fetch(`${API_BASE}/sheets/initialize`, {
        method: "POST",
        headers: { "Authorization": `Bearer ${token}` }
      });
      if (res.status === 200) {
        await get().fetchSheetsStatus();
        return true;
      }
      return false;
    } catch (e) {
      console.error(e);
      return false;
    }
  },

  fetchAgentStatus: async () => {
    const token = get().token;
    if (!token) return;
    try {
      const res = await fetch(`${API_BASE}/agents/status`, {
        headers: { "Authorization": `Bearer ${token}` }
      });
      if (res.status === 200) {
        const data = await res.json();
        set({ agentStatus: data });
      }
    } catch (e) {
      console.error(e);
    }
  },

  startDiscovery: async () => {
    const token = get().token;
    if (!token) return false;
    try {
      const res = await fetch(`${API_BASE}/agents/discovery/start`, {
        method: "POST",
        headers: { "Authorization": `Bearer ${token}` }
      });
      if (res.status === 200) {
        await get().fetchAgentStatus();
        get().addLogLine("[User] Started Job Discovery daemon.");
        return true;
      }
      return false;
    } catch (e) {
      console.error(e);
      return false;
    }
  },

  stopDiscovery: async () => {
    const token = get().token;
    if (!token) return false;
    try {
      const res = await fetch(`${API_BASE}/agents/discovery/stop`, {
        method: "POST",
        headers: { "Authorization": `Bearer ${token}` }
      });
      if (res.status === 200) {
        await get().fetchAgentStatus();
        get().addLogLine("[User] Stopped Job Discovery daemon.");
        return true;
      }
      return false;
    } catch (e) {
      console.error(e);
      return false;
    }
  },

  startAutoApply: async () => {
    const token = get().token;
    if (!token) return false;
    try {
      const res = await fetch(`${API_BASE}/agents/autoapply/start`, {
        method: "POST",
        headers: { "Authorization": `Bearer ${token}` }
      });
      if (res.status === 200) {
        await get().fetchAgentStatus();
        get().addLogLine("[User] Enabled Full-Auto Apply mode.");
        return true;
      }
      return false;
    } catch (e) {
      console.error(e);
      return false;
    }
  },

  stopAutoApply: async () => {
    const token = get().token;
    if (!token) return false;
    try {
      const res = await fetch(`${API_BASE}/agents/autoapply/stop`, {
        method: "POST",
        headers: { "Authorization": `Bearer ${token}` }
      });
      if (res.status === 200) {
        await get().fetchAgentStatus();
        get().addLogLine("[User] Disabled Full-Auto Apply mode (switched to Human Approval).");
        return true;
      }
      return false;
    } catch (e) {
      console.error(e);
      return false;
    }
  },

  startEmailMonitoring: async () => {
    const token = get().token;
    if (!token) return false;
    try {
      const res = await fetch(`${API_BASE}/agents/email-monitoring/start`, {
        method: "POST",
        headers: { "Authorization": `Bearer ${token}` }
      });
      if (res.status === 200) {
        await get().fetchAgentStatus();
        get().addLogLine("[User] Enabled Gmail Email monitoring.");
        return true;
      } else {
        const data = await res.json();
        get().addLogLine(`[Error] Failed to enable email monitoring: ${data.detail || "Unknown error"}`);
        return false;
      }
    } catch (e) {
      console.error(e);
      return false;
    }
  },

  stopEmailMonitoring: async () => {
    const token = get().token;
    if (!token) return false;
    try {
      const res = await fetch(`${API_BASE}/agents/email-monitoring/stop`, {
        method: "POST",
        headers: { "Authorization": `Bearer ${token}` }
      });
      if (res.status === 200) {
        await get().fetchAgentStatus();
        get().addLogLine("[User] Disabled Gmail Email monitoring.");
        return true;
      }
      return false;
    } catch (e) {
      console.error(e);
      return false;
    }
  },

  syncSheets: async () => {
    const token = get().token;
    if (!token) return false;
    try {
      const res = await fetch(`${API_BASE}/agents/sync-sheets`, {
        method: "POST",
        headers: { "Authorization": `Bearer ${token}` }
      });
      if (res.status === 200) {
        const data = await res.json();
        get().addLogLine(`[User] Sheets sync triggered. Processed ${data.processed_events} pending events.`);
        await get().fetchSheetsStatus();
        return true;
      }
      return false;
    } catch (e) {
      console.error(e);
      return false;
    }
  },

  refreshJobs: async () => {
    const token = get().token;
    if (!token) return false;
    try {
      const res = await fetch(`${API_BASE}/agents/refresh-jobs`, {
        method: "POST",
        headers: { "Authorization": `Bearer ${token}` }
      });
      if (res.status === 200) {
        get().addLogLine("[User] Job discovery crawl refresh triggered.");
        return true;
      }
      return false;
    } catch (e) {
      console.error(e);
      return false;
    }
  },

  addLogLine: (message) => {
    set((state) => {
      const time = new Date().toLocaleTimeString();
      return { logs: [...state.logs.slice(-200), `[${time}] ${message}`] };
    });
  },

  clearLogs: () => set({ logs: [] })
}));
