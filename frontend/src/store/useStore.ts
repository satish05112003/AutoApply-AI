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
    apps_per_hour?: number;
    subs_per_hour?: number;
    awaiting_retry?: number;
    avg_duration_min?: number;
    captcha_rate?: number;
    platform_rates?: Record<string, number>;
    failure_rate?: number;
    linkedin_jobs_found?: number;
    naukri_jobs_found?: number;
    indeed_jobs_found?: number;
    applications_submitted?: number;
    applications_failed?: number;
    applications_skipped?: number;
    duplicate_jobs_prevented?: number;
    jobs_applied_today?: number;
  };
  logs: string[];
  notifications: any[];
  sheetsStatus: {
    linked: boolean;
    spreadsheet_url: string | null;
    spreadsheet_id: string | null;
    last_sync_time: string | null;
  };
  googleIntegration: {
    connected: boolean;
    provisioned: boolean;
    google_email: string | null;
    spreadsheet_id: string | null;
    spreadsheet_url: string | null;
    last_sync_at: string | null;
    configured: boolean;
  };
  agentStatus: {
    discovery_running: boolean;
    auto_apply_running: boolean;
    email_monitoring_running: boolean;
    agent_mode: string;
    agent_enabled: boolean;
    redis_connected?: boolean;
  } | null;
  systemHealth: {
    status: string;
    services: {
      postgres: string;
      redis: string;
      celery: string;
      qdrant: string;
    };
    celery_metrics: {
      active_workers: number;
      queue_size: number;
    };
    candidate_stats: {
      active_applications: number;
      submitted_today: number;
    };
    queues?: Record<string, number>;
    workers?: Record<string, string>;
  } | null;
  platformSessions: Record<string, boolean>;
  automationEnabled: boolean;
  
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
  fetchSystemHealth: () => Promise<void>;
  fetchSystemEvents: () => Promise<void>;
  startDiscovery: () => Promise<boolean>;
  stopDiscovery: () => Promise<boolean>;
  startAutoApply: () => Promise<boolean>;
  stopAutoApply: () => Promise<boolean>;
  startEmailMonitoring: () => Promise<boolean>;
  stopEmailMonitoring: () => Promise<boolean>;
  syncSheets: () => Promise<boolean>;
  fetchGoogleIntegrationStatus: () => Promise<void>;
  connectGoogleSheets: () => Promise<void>;
  disconnectGoogleSheets: () => Promise<boolean>;
  manualSyncGoogleSheets: () => Promise<boolean>;
  refreshJobs: () => Promise<boolean>;
  fetchNotifications: () => Promise<void>;
  markNotificationRead: (id: string) => Promise<boolean>;
  markAllNotificationsRead: () => Promise<boolean>;
  retryApplication: (id: string) => Promise<boolean>;
  updateApplicationStatus: (id: string, status: string) => Promise<boolean>;
  purgeQueues: () => Promise<boolean>;
  fetchPlatformSessions: () => Promise<void>;
  connectPlatform: (platform: string) => Promise<boolean>;
  addLogLine: (message: string) => void;
  clearLogs: () => void;
  fetchAutomationStatus: () => Promise<void>;
  startAutomation: () => Promise<boolean>;
  stopAutomation: () => Promise<boolean>;
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
    status_distribution: {},
    apps_per_hour: 0,
    subs_per_hour: 0,
    awaiting_retry: 0,
    avg_duration_min: 0,
    captcha_rate: 0,
    platform_rates: {},
    failure_rate: 0,
    linkedin_jobs_found: 0,
    naukri_jobs_found: 0,
    indeed_jobs_found: 0,
    applications_submitted: 0,
    applications_failed: 0,
    applications_skipped: 0,
    duplicate_jobs_prevented: 0,
    jobs_applied_today: 0
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
  googleIntegration: {
    connected: false,
    provisioned: false,
    google_email: null,
    spreadsheet_id: null,
    spreadsheet_url: null,
    last_sync_at: null,
    configured: false,
  },
  agentStatus: null,
  systemHealth: null,
  notifications: [],
  platformSessions: {
    linkedin: false,
    indeed: false,
    naukri: false,
    unstop: false
  },
  automationEnabled: false,

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
      // Prefer new OAuth integration status endpoint
      const res = await fetch(`${API_BASE}/integrations/google/status`, {
        headers: { "Authorization": `Bearer ${token}` }
      });
      if (res.status === 200) {
        const data = await res.json();
        set({
          googleIntegration: data,
          // Keep legacy sheetsStatus compatible with old UI parts
          sheetsStatus: {
            linked: data.connected && data.provisioned,
            spreadsheet_url: data.spreadsheet_url,
            spreadsheet_id: data.spreadsheet_id,
            last_sync_time: data.last_sync_at,
          }
        });
      }
    } catch (e) {
      console.error(e);
    }
  },

  initializeSheets: async () => {
    const token = get().token;
    if (!token) return false;
    // Legacy: try old endpoint for backward compat
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

  fetchGoogleIntegrationStatus: async () => {
    await get().fetchSheetsStatus();
  },

  connectGoogleSheets: async () => {
    const token = get().token;
    if (!token) return;
    try {
      const res = await fetch(`${API_BASE}/integrations/google/connect`, {
        headers: { "Authorization": `Bearer ${token}` }
      });
      if (res.status === 200) {
        const data = await res.json();
        if (data.authorization_url) {
          window.location.href = data.authorization_url;
        }
      } else {
        console.error("Failed to get Google OAuth URL", await res.text());
      }
    } catch (e) {
      console.error(e);
    }
  },

  disconnectGoogleSheets: async () => {
    const token = get().token;
    if (!token) return false;
    try {
      const res = await fetch(`${API_BASE}/integrations/google/disconnect`, {
        method: "DELETE",
        headers: { "Authorization": `Bearer ${token}` }
      });
      if (res.status === 200) {
        set({
          googleIntegration: {
            connected: false, provisioned: false, google_email: null,
            spreadsheet_id: null, spreadsheet_url: null, last_sync_at: null, configured: true
          },
          sheetsStatus: { linked: false, spreadsheet_url: null, spreadsheet_id: null, last_sync_time: null }
        });
        get().addLogLine("[User] Disconnected Google Sheets integration.");
        return true;
      }
      return false;
    } catch (e) {
      console.error(e);
      return false;
    }
  },

  manualSyncGoogleSheets: async () => {
    const token = get().token;
    if (!token) return false;
    try {
      const res = await fetch(`${API_BASE}/integrations/google/sync`, {
        method: "POST",
        headers: { "Authorization": `Bearer ${token}` }
      });
      if (res.status === 200) {
        get().addLogLine("[User] Google Sheets sync enqueued.");
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

  fetchSystemHealth: async () => {
    const token = get().token;
    if (!token) return;
    try {
      const res = await fetch(`${API_BASE}/system/health`, {
        headers: { "Authorization": `Bearer ${token}` }
      });
      if (res.status === 200) {
        const data = await res.json();
        set({ systemHealth: data });
      }
    } catch (e) {
      console.error(e);
    }
  },

  fetchSystemEvents: async () => {
    const token = get().token;
    if (!token) return;
    try {
      const res = await fetch(`${API_BASE}/system/events`, {
        headers: { "Authorization": `Bearer ${token}` }
      });
      if (res.status === 200) {
        const events = await res.json();
        const formattedLogs = events.map((ev: any) => {
          const time = new Date(ev.timestamp).toLocaleTimeString();
          return `[${time}] ${ev.message}`;
        });
        set({ logs: formattedLogs });
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

  fetchNotifications: async () => {
    const token = get().token;
    if (!token) return;
    try {
      const res = await fetch(`${API_BASE}/notifications`, {
        headers: { "Authorization": `Bearer ${token}` }
      });
      if (res.status === 200) {
        const notifications = await res.json();
        set({ notifications });
      }
    } catch (e) {
      console.error(e);
    }
  },

  markNotificationRead: async (id) => {
    const token = get().token;
    if (!token) return false;
    try {
      const res = await fetch(`${API_BASE}/notifications/${id}/read`, {
        method: "POST",
        headers: { "Authorization": `Bearer ${token}` }
      });
      if (res.status === 200) {
        await get().fetchNotifications();
        return true;
      }
      return false;
    } catch (e) {
      console.error(e);
      return false;
    }
  },

  markAllNotificationsRead: async () => {
    const token = get().token;
    if (!token) return false;
    try {
      const res = await fetch(`${API_BASE}/notifications/mark-read`, {
        method: "POST",
        headers: { "Authorization": `Bearer ${token}` }
      });
      if (res.status === 200) {
        await get().fetchNotifications();
        return true;
      }
      return false;
    } catch (e) {
      console.error(e);
      return false;
    }
  },

  retryApplication: async (id) => {
    const token = get().token;
    if (!token) return false;
    try {
      const res = await fetch(`${API_BASE}/applications/${id}/retry`, {
        method: "POST",
        headers: { "Authorization": `Bearer ${token}` }
      });
      if (res.status === 200) {
        await get().fetchApplications();
        get().addLogLine(`[User] Initiated manual submission retry for app ID: ${id}`);
        return true;
      }
      return false;
    } catch (e) {
      console.error(e);
      return false;
    }
  },

  updateApplicationStatus: async (id, status) => {
    const token = get().token;
    if (!token) return false;
    try {
      const res = await fetch(`${API_BASE}/applications/${id}/status`, {
        method: "PUT",
        headers: { 
          "Authorization": `Bearer ${token}`,
          "Content-Type": "application/json"
        },
        body: JSON.stringify({ status })
      });
      if (res.status === 200) {
        await get().fetchApplications();
        get().addLogLine(`[User] Transitioned application ID ${id} to status: ${status}`);
        return true;
      }
      return false;
    } catch (e) {
      console.error(e);
      return false;
    }
  },

  purgeQueues: async () => {
    const token = get().token;
    if (!token) return false;
    try {
      const res = await fetch(`${API_BASE}/system/queues/purge`, {
        method: "POST",
        headers: { "Authorization": `Bearer ${token}` }
      });
      if (res.status === 200) {
        get().addLogLine("[User] Purged background Celery queues.");
        await get().fetchSystemHealth();
        return true;
      }
      return false;
    } catch (e) {
      console.error(e);
      return false;
    }
  },

  fetchPlatformSessions: async () => {
    const token = get().token;
    if (!token) return;
    try {
      const res = await fetch(`${API_BASE}/system/browser/sessions`, {
        headers: { "Authorization": `Bearer ${token}` }
      });
      if (res.status === 200) {
        const platformSessions = await res.json();
        set({ platformSessions });
      }
    } catch (e) {
      console.error("[Store] Error fetching platform sessions:", e);
    }
  },

  connectPlatform: async (platform: string) => {
    const token = get().token;
    if (!token) return false;
    try {
      get().addLogLine(`[User] Launching login session window for ${platform}...`);
      const res = await fetch(`${API_BASE}/system/browser/login?source=${platform}`, {
        method: "POST",
        headers: { "Authorization": `Bearer ${token}` }
      });
      if (res.status === 200) {
        const data = await res.json();
        if (data.status === "success") {
          get().addLogLine(`[System] Platform ${platform} login succeeded.`);
          await get().fetchPlatformSessions();
          return true;
        } else {
          get().addLogLine(`[Warning] Platform ${platform} login: ${data.message}`);
          return false;
        }
      }
      return false;
    } catch (e) {
      console.error(e);
      get().addLogLine(`[Error] Platform ${platform} login failed.`);
      return false;
    }
  },

  addLogLine: (message) => {
    set((state) => {
      const time = new Date().toLocaleTimeString();
      return { logs: [...state.logs.slice(-200), `[${time}] ${message}`] };
    });
  },

  clearLogs: () => set({ logs: [] }),

  fetchAutomationStatus: async () => {
    const token = get().token;
    if (!token) return;
    try {
      const res = await fetch(`${API_BASE}/system/automation-status`, {
        headers: { "Authorization": `Bearer ${token}` }
      });
      if (res.status === 200) {
        const data = await res.json();
        set({ automationEnabled: data.enabled === true });
      }
    } catch (e) {
      console.error("[Store] Failed to fetch automation status:", e);
    }
  },

  startAutomation: async () => {
    const token = get().token;
    if (!token) return false;
    try {
      const res = await fetch(`${API_BASE}/system/automation/start`, {
        method: "POST",
        headers: { "Authorization": `Bearer ${token}` }
      });
      if (res.status === 200) {
        const data = await res.json();
        set({ automationEnabled: data.enabled === true });
        get().addLogLine("[System] ⚡ Automation engine STARTED. Crawlers and agents are now active.");
        return true;
      }
      return false;
    } catch (e) {
      console.error("[Store] Failed to start automation:", e);
      return false;
    }
  },

  stopAutomation: async () => {
    const token = get().token;
    if (!token) return false;
    try {
      const res = await fetch(`${API_BASE}/system/automation/stop`, {
        method: "POST",
        headers: { "Authorization": `Bearer ${token}` }
      });
      if (res.status === 200) {
        const data = await res.json();
        set({ automationEnabled: data.enabled === true });
        get().addLogLine("[System] 🔴 Automation engine STOPPED. System is now fully idle.");
        return true;
      }
      return false;
    } catch (e) {
      console.error("[Store] Failed to stop automation:", e);
      return false;
    }
  },
}));

