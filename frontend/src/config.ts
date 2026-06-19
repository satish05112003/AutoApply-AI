// Centralized environment configuration for AutoApply AI Next.js application

const cleanEnvVar = (value: string | undefined): string | null => {
  if (!value) return null;
  // Remove BOM, quotes, and whitespace
  return value.replace(/^\uFEFF/, "").trim().replace(/^["']|["']$/g, "");
};

// 1. Resolve and Clean API base URL
const rawApiUrl = process.env.NEXT_PUBLIC_API_URL;
const cleanedApiUrl = cleanEnvVar(rawApiUrl);

export const API_BASE = cleanedApiUrl || "http://localhost:8000/api/v1";

if (!rawApiUrl) {
  console.warn(`[Config Warning] NEXT_PUBLIC_API_URL is not set. Using default: ${API_BASE}`);
} else {
  console.log(`[Config] Resolved API Base: ${API_BASE}`);
}

// 2. Resolve and Clean WS URL, or dynamically generate from API_BASE if not provided
const rawWsUrl = process.env.NEXT_PUBLIC_WS_URL;
const cleanedWsUrl = cleanEnvVar(rawWsUrl);

const getWsBase = (): string => {
  if (cleanedWsUrl) {
    return cleanedWsUrl;
  }

  try {
    const url = new URL(API_BASE);
    const wsProtocol = url.protocol === "https:" ? "wss:" : "ws:";
    // Construct the websocket endpoint at the same host & port
    return `${wsProtocol}//${url.host}`;
  } catch (err) {
    console.error("[Config Error] Failed to dynamically construct WebSocket URL from API_BASE. Fallback to ws://localhost:8000");
    return "ws://localhost:8000";
  }
};

export const WS_BASE = getWsBase();

console.log(`[Config] Resolved WebSocket Base: ${WS_BASE}`);
