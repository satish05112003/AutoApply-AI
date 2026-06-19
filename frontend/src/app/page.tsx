"use client";

import React, { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import { useStore } from "@/store/useStore";
import { API_BASE } from "@/config";
import { Lock, Mail, User, Shield, Terminal } from "lucide-react";

export default function AuthPage() {
  const router = useRouter();
  const { login, token } = useStore();
  const [isRegister, setIsRegister] = useState(false);
  const [email, setEmail] = useState("candidate@autoapply.ai");
  const [password, setPassword] = useState("password123");
  const [name, setName] = useState("Satis");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (token) {
      router.push("/dashboard");
    }
  }, [token, router]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError("");

    if (isRegister) {
      try {
        const endpoint = `${API_BASE}/auth/register`;
        console.log(`[AuthPage] Sending register request to ${endpoint}`, { email, full_name: name });
        const res = await fetch(endpoint, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ email, password, full_name: name })
        });
        console.log(`[AuthPage] Register response status: ${res.status}`);
        if (res.status === 201) {
          console.log(`[AuthPage] Registration successful. Logging in...`);
          const success = await login(email, password);
          if (success) router.push("/dashboard");
        } else {
          const detail = await res.json();
          console.error(`[AuthPage] Registration failed details:`, detail);
          setError(detail.detail || "Registration failed.");
        }
      } catch (err) {
        console.error(`[AuthPage] Registration network error:`, err);
        setError("Network error. Make sure the backend is running.");
      }
    } else {
      const success = await login(email, password);
      if (success) {
        router.push("/dashboard");
      } else {
        setError("Invalid email or password.");
      }
    }
    setLoading(false);
  };

  return (
    <div className="relative min-h-screen flex items-center justify-center bg-[#09090b] text-[#f4f4f5] overflow-hidden p-6">
      {/* Background cyber grid & glow effects */}
      <div className="absolute inset-0 bg-[linear-gradient(to_right,#0f0f12_1px,transparent_1px),linear-gradient(to_bottom,#0f0f12_1px,transparent_1px)] bg-[size:4rem_4rem] [mask-image:radial-gradient(ellipse_60%_50%_at_50%_50%,#000_70%,transparent_100%)]" />
      <div className="absolute top-1/4 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[500px] h-[500px] bg-[#22c55e]/10 rounded-full blur-[120px] pointer-events-none" />

      <div className="relative w-full max-w-md bg-[#0f0f13]/80 backdrop-blur-xl border border-zinc-800/80 rounded-2xl p-8 shadow-[0_0_50px_-12px_rgba(34,197,94,0.15)] transition-all duration-300">
        
        {/* Header */}
        <div className="text-center mb-8">
          <div className="inline-flex items-center justify-center p-3 rounded-xl bg-zinc-900 border border-zinc-800 text-emerald-500 mb-4 shadow-[0_0_20px_rgba(52,211,153,0.1)]">
            <Terminal className="w-8 h-8" />
          </div>
          <h1 className="text-2xl font-bold tracking-tight">AutoApply AI</h1>
          <p className="text-sm text-zinc-400 mt-1.5">Autonomous job application pipeline</p>
        </div>

        {/* Error notification */}
        {error && (
          <div className="mb-6 p-4 bg-red-950/30 border border-red-800/50 rounded-xl text-red-400 text-sm flex items-center gap-3">
            <Shield className="w-4 h-4 shrink-0" />
            <span>{error}</span>
          </div>
        )}

        {/* Form */}
        <form onSubmit={handleSubmit} className="space-y-5">
          {isRegister && (
            <div className="space-y-1.5">
              <label className="text-xs font-semibold text-zinc-400 uppercase tracking-wider">Full Name</label>
              <div className="relative">
                <User className="absolute left-3.5 top-1/2 -translate-y-1/2 w-4 h-4 text-zinc-500" />
                <input
                  type="text"
                  required
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  className="w-full pl-10 pr-4 py-3 bg-zinc-950/80 border border-zinc-800 rounded-xl text-sm focus:outline-none focus:border-emerald-500 transition-colors"
                  placeholder="Enter full name"
                />
              </div>
            </div>
          )}

          <div className="space-y-1.5">
            <label className="text-xs font-semibold text-zinc-400 uppercase tracking-wider">Email Address</label>
            <div className="relative">
              <Mail className="absolute left-3.5 top-1/2 -translate-y-1/2 w-4 h-4 text-zinc-500" />
              <input
                type="email"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                className="w-full pl-10 pr-4 py-3 bg-zinc-950/80 border border-zinc-800 rounded-xl text-sm focus:outline-none focus:border-emerald-500 transition-colors"
                placeholder="developer@example.com"
              />
            </div>
          </div>

          <div className="space-y-1.5">
            <label className="text-xs font-semibold text-zinc-400 uppercase tracking-wider">Password</label>
            <div className="relative">
              <Lock className="absolute left-3.5 top-1/2 -translate-y-1/2 w-4 h-4 text-zinc-500" />
              <input
                type="password"
                required
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="w-full pl-10 pr-4 py-3 bg-zinc-950/80 border border-zinc-800 rounded-xl text-sm focus:outline-none focus:border-emerald-500 transition-colors"
                placeholder="••••••••"
              />
            </div>
          </div>

          <button
            type="submit"
            disabled={loading}
            className="w-full py-3 px-4 bg-emerald-600 hover:bg-emerald-500 text-emerald-50 font-medium rounded-xl text-sm transition-all focus:outline-none shadow-[0_0_20px_rgba(16,185,129,0.2)] disabled:opacity-50 flex items-center justify-center gap-2"
          >
            {loading ? "Authenticating..." : isRegister ? "Create Account" : "Access Workspace"}
          </button>
        </form>

        {/* Toggle auth mode */}
        <div className="text-center mt-6 text-sm">
          <span className="text-zinc-500">
            {isRegister ? "Already configured?" : "First time configuring?"}
          </span>{" "}
          <button
            onClick={() => setIsRegister(!isRegister)}
            className="text-emerald-500 hover:underline font-medium focus:outline-none"
          >
            {isRegister ? "Sign in instead" : "Create candidate profile"}
          </button>
        </div>

      </div>
    </div>
  );
}
