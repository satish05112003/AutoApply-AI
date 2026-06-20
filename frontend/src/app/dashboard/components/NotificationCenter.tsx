"use client";

import React, { useEffect, useState } from "react";
import { useStore } from "@/store/useStore";
import { Bell, Check, Trash2, Calendar, ShieldCheck, MailWarning, BellOff } from "lucide-react";

export default function NotificationCenter() {
  const { 
    notifications, 
    fetchNotifications, 
    markNotificationRead, 
    markAllNotificationsRead 
  } = useStore();
  
  const [isOpen, setIsOpen] = useState(false);

  useEffect(() => {
    fetchNotifications();
    // Poll notifications every 15 seconds
    const intv = setInterval(() => {
      fetchNotifications();
    }, 15000);
    return () => clearInterval(intv);
  }, []);

  const unreadCount = notifications.filter(n => !n.is_read).length;

  const handleMarkRead = async (id: string, e: React.MouseEvent) => {
    e.stopPropagation();
    await markNotificationRead(id);
  };

  const handleMarkAllRead = async () => {
    await markAllNotificationsRead();
  };

  const getIcon = (type: string) => {
    switch (type) {
      case "EMAIL_MATCH":
      case "INTERVIEW":
        return <Calendar className="w-3.5 h-3.5 text-purple-400" />;
      case "APPLICATION_SUBMITTED":
        return <ShieldCheck className="w-3.5 h-3.5 text-emerald-400" />;
      case "SUBMISSION_FAILED":
        return <MailWarning className="w-3.5 h-3.5 text-red-400" />;
      default:
        return <Bell className="w-3.5 h-3.5 text-blue-400" />;
    }
  };

  return (
    <div className="relative">
      <button 
        onClick={() => setIsOpen(!isOpen)}
        className="relative p-2 rounded-xl bg-zinc-900 border border-zinc-800 text-zinc-400 hover:text-zinc-200 transition-all cursor-pointer"
        title="Notifications"
      >
        <Bell className="w-4 h-4" />
        {unreadCount > 0 && (
          <span className="absolute -top-1 -right-1 flex h-4 w-4 items-center justify-center rounded-full bg-red-600 text-[8px] font-bold text-white ring-2 ring-[#0b0b0f] animate-pulse">
            {unreadCount}
          </span>
        )}
      </button>

      {isOpen && (
        <>
          <div 
            className="fixed inset-0 z-10" 
            onClick={() => setIsOpen(false)}
          />
          
          <div className="absolute right-0 mt-2 w-80 bg-[#0d0d11] border border-zinc-800 rounded-2xl shadow-2xl overflow-hidden z-20 animate-fade-in font-mono text-[10px]">
            <div className="px-4 py-3 border-b border-zinc-900 flex items-center justify-between bg-zinc-950/60">
              <span className="font-bold text-zinc-300">Notifications</span>
              {unreadCount > 0 && (
                <button 
                  onClick={handleMarkAllRead}
                  className="text-[9px] text-emerald-400 hover:text-emerald-300 font-bold transition-colors cursor-pointer"
                >
                  Mark all read
                </button>
              )}
            </div>

            <div className="max-h-72 overflow-y-auto divide-y divide-zinc-900/60 scrollbar-thin">
              {notifications.length === 0 ? (
                <div className="py-8 flex flex-col items-center justify-center gap-2 text-zinc-500 italic">
                  <BellOff className="w-5 h-5 text-zinc-650" />
                  <span>No recent alerts</span>
                </div>
              ) : (
                notifications.map((n) => (
                  <div 
                    key={n.id} 
                    className={`p-3.5 flex items-start gap-3 transition-colors ${
                      n.is_read ? "bg-transparent opacity-60" : "bg-emerald-950/5 hover:bg-emerald-950/10"
                    }`}
                  >
                    <div className="p-1.5 rounded-lg bg-zinc-900/80 border border-zinc-850 shrink-0 mt-0.5">
                      {getIcon(n.notification_type)}
                    </div>
                    <div className="flex-1 min-w-0 space-y-1 text-xs">
                      <div className="flex items-start justify-between gap-2">
                        <span className={`font-semibold text-[10.5px] truncate font-sans ${n.is_read ? "text-zinc-400" : "text-zinc-200"}`}>
                          {n.title || n.notification_type.replace(/_/g, " ")}
                        </span>
                        {!n.is_read && (
                          <button
                            onClick={(e) => handleMarkRead(n.id, e)}
                            className="shrink-0 text-zinc-500 hover:text-emerald-400 p-0.5 rounded transition-all cursor-pointer"
                            title="Mark as read"
                          >
                            <Check className="w-3.5 h-3.5" />
                          </button>
                        )}
                      </div>
                      <p className="text-[10px] text-zinc-400 font-sans leading-normal line-clamp-3">
                        {n.body}
                      </p>
                      <div className="text-[8.5px] text-zinc-650">
                        {new Date(n.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })} • {new Date(n.created_at).toLocaleDateString([], { month: 'short', day: 'numeric' })}
                      </div>
                    </div>
                  </div>
                ))
              )}
            </div>
          </div>
        </>
      )}
    </div>
  );
}
