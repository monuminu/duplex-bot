"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect } from "react";
import { Bot, LogOut, Mic, Sparkles } from "lucide-react";

import { Button } from "@/components/ui/button";
import { useAuth } from "@/hooks/use-auth";
import { cn } from "@/lib/utils";

const NAV = [
  { label: "Voice Agents", href: "/voice-agents", icon: Bot },
  { label: "Playground", href: "/playground", icon: Sparkles },
];

export function AppShell({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const { user, tenant, loading, logout } = useAuth();

  useEffect(() => {
    if (!loading && !user) router.replace("/login");
  }, [loading, user, router]);

  if (loading || !user) {
    return (
      <div className="flex min-h-screen items-center justify-center text-sm text-slate-500">
        Loading workspace…
      </div>
    );
  }

  return (
    <div className="flex min-h-screen w-full text-slate-900">
      <aside className="sticky top-0 hidden h-screen w-64 shrink-0 flex-col border-r border-[var(--border)] bg-white/85 p-4 backdrop-blur-sm lg:flex">
        <Link href="/voice-agents" className="mb-7 flex items-center gap-3 px-1 py-2">
          <div className="flex size-9 items-center justify-center rounded-xl bg-[var(--accent)] text-white shadow-[0_6px_16px_-6px_rgba(79,70,229,0.6)]">
            <Mic className="size-4" />
          </div>
          <span className="display text-[1.05rem] text-slate-900">VoiceAgent</span>
        </Link>

        <div className="mb-2 px-3 text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-400">
          Workspace
        </div>
        <nav className="space-y-1">
          {NAV.map((item) => {
            const active = pathname.startsWith(item.href);
            return (
              <Link
                key={item.href}
                href={item.href}
                className={cn(
                  "flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-left text-sm font-medium text-slate-500 transition hover:bg-slate-100 hover:text-slate-900",
                  active &&
                    "bg-[var(--accent-soft)] text-[var(--accent-hover)] shadow-[inset_2px_0_0_var(--accent)] hover:bg-[var(--accent-soft)] hover:text-[var(--accent-hover)]",
                )}
              >
                <item.icon className={cn("size-4 shrink-0", active ? "text-[var(--accent)]" : "text-slate-400")} />
                <span className="truncate">{item.label}</span>
              </Link>
            );
          })}
        </nav>

        <div className="mt-auto space-y-3">
          <div className="rounded-xl border border-[var(--border)] bg-[var(--surface-muted)] p-3">
            <div className="text-[10px] font-semibold uppercase tracking-[0.12em] text-slate-400">Workspace</div>
            <div className="mt-1 truncate text-sm font-semibold text-slate-900">
              {tenant?.name || "My Workspace"}
            </div>
            <div className="mt-0.5 truncate text-xs text-slate-500">{user.email}</div>
          </div>
          <Button variant="secondary" className="w-full" onClick={logout}>
            <LogOut className="size-4" />
            Sign out
          </Button>
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-14 items-center justify-between gap-3 border-b border-[var(--border)] bg-white/85 px-4 backdrop-blur lg:hidden">
          <Link href="/voice-agents" className="flex items-center gap-2">
            <div className="flex size-8 items-center justify-center rounded-lg bg-[var(--accent)] text-white">
              <Mic className="size-4" />
            </div>
            <span className="display text-sm text-slate-900">VoiceAgent</span>
          </Link>
          <div className="flex items-center gap-2">
            {NAV.map((item) => (
              <Link
                key={item.href}
                href={item.href}
                className={cn(
                  "rounded-lg px-2.5 py-1.5 text-xs font-medium text-slate-500 transition hover:bg-slate-100 hover:text-slate-900",
                  pathname.startsWith(item.href) && "bg-[var(--accent-soft)] text-[var(--accent-hover)]",
                )}
              >
                {item.label}
              </Link>
            ))}
            <Button variant="ghost" size="icon" onClick={logout} aria-label="Sign out">
              <LogOut className="size-4" />
            </Button>
          </div>
        </header>

        <div className="min-w-0 flex-1">{children}</div>
      </div>
    </div>
  );
}
