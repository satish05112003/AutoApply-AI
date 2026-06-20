"use client";

import React from "react";
import { useStore } from "@/store/useStore";
import { 
  TrendingUp, 
  CheckCircle2, 
  AlertTriangle, 
  Award, 
  Percent 
} from "lucide-react";

export default function StatsGrid() {
  const { stats } = useStore();

  const cards = [
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
      desc: "Requires manual review/retry"
    },
    {
      title: "Success Rate",
      value: stats?.success_rate ? Math.round(stats.success_rate) : (
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

  return (
    <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
      {cards.map((c, idx) => (
        <div 
          key={idx} 
          className={`relative overflow-hidden group p-1.5 rounded-[1.25rem] border border-zinc-900 transition-all duration-300 transform hover:-translate-y-1 ${c.colorClass}`}
        >
          {/* Subtle background glow */}
          <div className={`absolute top-0 right-0 w-24 h-24 rounded-full blur-[40px] opacity-10 transition-opacity group-hover:opacity-20 ${c.glowColor}`} />
          
          <div className="bg-[#07070a]/90 rounded-[calc(1.25rem-0.375rem)] p-4.5 flex flex-col justify-between h-full min-h-[110px] shadow-[inset_0_1px_1px_rgba(255,255,255,0.02)]">
            <div className="flex items-center justify-between">
              <span className="text-[10px] text-zinc-500 font-bold uppercase tracking-widest font-mono">
                {c.title}
              </span>
              <div className="p-1 rounded-lg bg-zinc-950/50 border border-zinc-900/60">
                {c.icon}
              </div>
            </div>

            <div className="flex flex-col mt-4">
              <div className="flex items-baseline gap-1.5">
                <span className="text-3xl font-bold font-mono tracking-tight text-zinc-150">
                  {c.value}
                </span>
                <span className="text-[9px] text-zinc-500 font-semibold font-mono uppercase tracking-wider">
                  {c.suffix}
                </span>
              </div>
              <span className="text-[9px] text-zinc-500 font-sans mt-1 line-clamp-1">
                {c.desc}
              </span>
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}
