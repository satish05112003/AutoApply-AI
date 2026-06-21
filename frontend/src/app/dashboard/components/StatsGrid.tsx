"use client";

import React from "react";
import { useStore } from "@/store/useStore";
import { 
  TrendingUp, 
  CheckCircle2, 
  AlertTriangle, 
  Award, 
  Percent,
  Clock,
  RefreshCw,
  Zap,
  Activity
} from "lucide-react";

export default function StatsGrid() {
  const { stats } = useStore();

  const primaryCards = [
    {
      title: "Shortlisted",
      value: stats?.shortlisted ?? 0,
      suffix: "roles",
      colorClass: "text-emerald-400 border-emerald-950/30 bg-emerald-950/5 hover:bg-emerald-950/10 hover:shadow-[0_0_20px_rgba(16,185,129,0.08)]",
      glowColor: "bg-emerald-500",
      icon: <TrendingUp className="w-4 h-4 text-emerald-400" />,
      desc: "Pending agent submission"
    },
    {
      title: "Submitted",
      value: stats?.applied ?? 0,
      suffix: "apps",
      colorClass: "text-blue-400 border-blue-950/30 bg-blue-950/5 hover:bg-blue-950/10 hover:shadow-[0_0_20px_rgba(59,130,246,0.08)]",
      glowColor: "bg-blue-500",
      icon: <CheckCircle2 className="w-4 h-4 text-blue-400" />,
      desc: "Completed submissions"
    },
    {
      title: "Failed Runs",
      value: stats?.failed ?? 0,
      suffix: "errors",
      colorClass: "text-red-400 border-red-950/30 bg-red-950/5 hover:bg-red-950/10 hover:shadow-[0_0_20px_rgba(239,68,68,0.08)]",
      glowColor: "bg-red-500",
      icon: <AlertTriangle className="w-4 h-4 text-red-400" />,
      desc: "Requires manual review"
    },
    {
      title: "Success Rate",
      value: stats?.success_rate ?? (
        stats?.applied ? Math.round((stats.applied / ((stats.applied + stats.failed) || 1)) * 100) : 0
      ),
      suffix: "%",
      colorClass: "text-teal-400 border-teal-950/30 bg-teal-950/5 hover:bg-teal-950/10 hover:shadow-[0_0_20px_rgba(20,184,166,0.08)]",
      glowColor: "bg-teal-500",
      icon: <Percent className="w-4 h-4 text-teal-400" />,
      desc: "Submission completion ratio"
    },
    {
      title: "Avg Match",
      value: stats?.avg_match_score ? Math.round(stats.avg_match_score) : 0,
      suffix: "%",
      colorClass: "text-amber-400 border-amber-950/30 bg-amber-950/5 hover:bg-amber-950/10 hover:shadow-[0_0_20px_rgba(245,158,11,0.08)]",
      glowColor: "bg-amber-500",
      icon: <Award className="w-4 h-4 text-amber-400" />,
      desc: "Discovered profile fit rating"
    }
  ];

  const operationalCards = [
    {
      title: "Apps/Hr Throughput",
      value: stats?.apps_per_hour ?? 0,
      suffix: "run/h",
      icon: <Zap className="w-3.5 h-3.5 text-indigo-400" />,
      desc: "Applications processed per hour"
    },
    {
      title: "Subs/Hr Completion",
      value: stats?.subs_per_hour ?? 0,
      suffix: "sub/h",
      icon: <Activity className="w-3.5 h-3.5 text-purple-400" />,
      desc: "Successful submissions per hour"
    },
    {
      title: "Awaiting Retry",
      value: stats?.awaiting_retry ?? 0,
      suffix: "apps",
      icon: <RefreshCw className="w-3.5 h-3.5 text-orange-400" />,
      desc: "Applications scheduled for retry"
    },
    {
      title: "Avg App Duration",
      value: stats?.avg_duration_min ?? 0,
      suffix: "mins",
      icon: <Clock className="w-3.5 h-3.5 text-pink-400" />,
      desc: "Time taken to complete an application"
    },
    {
      title: "CAPTCHA Rate",
      value: stats?.captcha_rate ?? 0,
      suffix: "%",
      icon: <AlertTriangle className="w-3.5 h-3.5 text-yellow-500" />,
      desc: "Rate limit/CAPTCHA block frequency"
    }
  ];

  const platformRates = stats?.platform_rates || {};

  return (
    <div className="space-y-6">
      {/* Primary KPI Grid */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
        {primaryCards.map((c, idx) => (
          <div 
            key={idx} 
            className="premium-card p-5 flex flex-col justify-between h-full min-h-[120px] transition-all relative overflow-hidden group"
          >
            {/* Subtle glow on hover */}
            <div className={`absolute top-0 right-0 w-20 h-20 rounded-full blur-[35px] opacity-[0.02] transition-opacity group-hover:opacity-[0.07] ${c.glowColor}`} />
            
            <div className="flex items-center justify-between">
              <span className="text-[10px] text-zinc-500 font-bold uppercase tracking-wider font-mono">
                {c.title}
              </span>
              <div className="p-1 rounded-md bg-zinc-950/80 border border-zinc-900/40">
                {c.icon}
              </div>
            </div>

            <div className="flex flex-col mt-4">
              <div className="flex items-baseline gap-1">
                <span className="text-2xl font-semibold tracking-tight text-white font-sans">
                  {c.value}
                </span>
                <span className="text-[9px] text-zinc-500 font-mono uppercase">
                  {c.suffix}
                </span>
              </div>
              <span className="text-[10px] text-zinc-400 font-sans mt-0.5">
                {c.desc}
              </span>
            </div>
          </div>
        ))}
      </div>

      {/* Operational Visibility Sub-grid */}
      <div className="premium-card p-5 space-y-4">
        <div className="flex items-center justify-between pb-1">
          <span className="text-[10px] text-zinc-400 font-bold uppercase tracking-wider font-mono flex items-center gap-1.5">
            <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse" />
            Operational Health & Performance Center
          </span>
        </div>

        <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
          {operationalCards.map((oc, idx) => (
            <div key={idx} className="p-4 bg-zinc-950/30 rounded-lg border border-zinc-900/50 flex flex-col justify-between min-h-[85px] hover:border-zinc-800 transition-all">
              <div className="flex items-center justify-between">
                <span className="text-[9px] text-zinc-500 font-bold uppercase tracking-wider font-mono">{oc.title}</span>
                <div className="p-0.5 rounded bg-zinc-900/60 border border-zinc-850/40">{oc.icon}</div>
              </div>
              <div className="mt-3 flex items-baseline gap-1">
                <span className="text-xl font-bold font-sans text-zinc-200">{oc.value}</span>
                <span className="text-[8px] text-zinc-500 font-mono uppercase">{oc.suffix}</span>
              </div>
            </div>
          ))}
        </div>

        {/* Platform specific rates badges */}
        {Object.keys(platformRates).length > 0 && (
          <div className="pt-2 border-t border-zinc-900/40 flex flex-wrap items-center gap-3">
            <span className="text-[9px] text-zinc-550 font-mono uppercase font-semibold">Success Rates:</span>
            {Object.entries(platformRates).map(([platform, rate]) => (
              <span key={platform} className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded bg-zinc-950 border border-zinc-900/60 text-[9px] font-mono text-zinc-400">
                <span className="capitalize">{platform}</span>: <strong className="text-emerald-400">{rate}%</strong>
              </span>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
