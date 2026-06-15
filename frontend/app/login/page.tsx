"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { Loader2, Mic } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { useAuth } from "@/hooks/use-auth";
import { fetchAuthConfig } from "@/lib/api";

type Mode = "login" | "signup";

export default function LoginPage() {
  const router = useRouter();
  const { user, loading, login, signup } = useAuth();
  const [mode, setMode] = useState<Mode>("login");
  const [allowSignup, setAllowSignup] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [fullName, setFullName] = useState("");
  const [company, setCompany] = useState("");

  useEffect(() => {
    if (!loading && user) router.replace("/voice-agents");
  }, [loading, user, router]);

  useEffect(() => {
    fetchAuthConfig()
      .then((cfg) => {
        setAllowSignup(cfg.allow_signup);
        // If signups are open and there is no session, default to signup so the
        // very first operator lands on account creation.
        if (cfg.allow_signup) setMode("signup");
      })
      .catch(() => setAllowSignup(true));
  }, []);

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    setSubmitting(true);
    try {
      if (mode === "signup") {
        await signup({
          email,
          password,
          full_name: fullName || undefined,
          company_name: company || undefined,
        });
        toast.success("Workspace created");
      } else {
        await login(email, password);
        toast.success("Signed in");
      }
      router.replace("/voice-agents");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Authentication failed");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="flex min-h-screen items-center justify-center px-4 py-10 text-slate-900">
      <div className="w-full max-w-md rise-in">
        <div className="mb-8 flex flex-col items-center text-center">
          <div className="mb-4 flex size-14 items-center justify-center rounded-2xl bg-[var(--accent)] text-white shadow-[0_12px_30px_-10px_rgba(79,70,229,0.65)]">
            <Mic className="size-7" />
          </div>
          <h1 className="display text-[1.6rem] text-slate-900">VoiceAgent</h1>
          <p className="mt-2 text-sm text-slate-500">
            Build full-duplex voice agents for your business.
          </p>
        </div>

        <div className="surface-raised rounded-2xl p-6">
          <div className="mb-6 grid grid-cols-2 gap-1 rounded-xl border border-[var(--border)] bg-[var(--surface-muted)] p-1">
            <TabButton active={mode === "login"} onClick={() => setMode("login")}>
              Sign in
            </TabButton>
            <TabButton
              active={mode === "signup"}
              onClick={() => allowSignup && setMode("signup")}
              disabled={!allowSignup}
            >
              Create account
            </TabButton>
          </div>

          <form onSubmit={onSubmit} className="space-y-4">
            {mode === "signup" ? (
              <>
                <Field label="Your name">
                  <input
                    className="auth-input"
                    value={fullName}
                    onChange={(e) => setFullName(e.target.value)}
                    placeholder="Jane Doe"
                    autoComplete="name"
                  />
                </Field>
                <Field label="Company / workspace name">
                  <input
                    className="auth-input"
                    value={company}
                    onChange={(e) => setCompany(e.target.value)}
                    placeholder="Acme Naval Services"
                    autoComplete="organization"
                  />
                </Field>
              </>
            ) : null}
            <Field label="Email">
              <input
                className="auth-input"
                type="email"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="you@company.com"
                autoComplete="email"
              />
            </Field>
            <Field label="Password">
              <input
                className="auth-input"
                type="password"
                required
                minLength={mode === "signup" ? 8 : 1}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder={mode === "signup" ? "At least 8 characters" : "Your password"}
                autoComplete={mode === "signup" ? "new-password" : "current-password"}
              />
            </Field>

            <Button type="submit" className="w-full" disabled={submitting}>
              {submitting ? <Loader2 className="size-4 animate-spin" /> : null}
              {mode === "signup" ? "Create workspace" : "Sign in"}
            </Button>
          </form>

          {!allowSignup && mode === "login" ? (
            <p className="mt-4 text-center text-xs text-slate-400">
              Public sign-ups are disabled on this instance.
            </p>
          ) : null}
        </div>
      </div>

      <style jsx global>{`
        .auth-input {
          height: 2.6rem;
          width: 100%;
          border-radius: 0.625rem;
          border: 1px solid var(--border-strong);
          background: #ffffff;
          padding: 0 0.75rem;
          font-size: 0.875rem;
          color: #0f172a;
          outline: none;
          box-shadow: var(--shadow-xs);
          transition: border-color 0.15s, box-shadow 0.15s;
        }
        .auth-input::placeholder {
          color: #94a3b8;
        }
        .auth-input:focus {
          border-color: var(--accent);
          box-shadow: 0 0 0 3px var(--accent-ring);
        }
      `}</style>
    </main>
  );
}

function TabButton({
  active,
  onClick,
  disabled,
  children,
}: {
  active: boolean;
  onClick: () => void;
  disabled?: boolean;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className={[
        "rounded-lg px-3 py-2 text-sm font-semibold transition",
        active ? "bg-white text-[var(--accent-hover)] shadow-[var(--shadow-xs)]" : "text-slate-500 hover:text-slate-900",
        disabled ? "cursor-not-allowed opacity-40" : "",
      ].join(" ")}
    >
      {children}
    </button>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="mb-2 block text-xs font-medium text-slate-600">{label}</span>
      {children}
    </label>
  );
}
