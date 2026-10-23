"use client";
import { Eye, EyeOff } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";
import { session } from "@/lib/client";

export function LoginForm() {
  const router = useRouter();
  const [user, setUser] = useState("");
  const [password, setPassword] = useState("");
  const [show, setShow] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      await session.signIn(user.trim(), password);
      router.replace("/");
      router.refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Sign in failed.");
      setPassword("");
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="form" noValidate>
      <label className="field">
        <span>User</span>
        <input value={user} onChange={(e) => setUser(e.target.value)} autoComplete="username" autoCapitalize="none" spellCheck={false} required autoFocus />
      </label>
      <label className="field">
        <span>Password</span>
        <span className="input-join">
          <input type={show ? "text" : "password"} value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" required />
          <button type="button" className="input-action" onClick={() => setShow((s) => !s)} aria-label={show ? "Hide password" : "Show password"} aria-pressed={show}>
            {show ? <EyeOff size={16} strokeWidth={1.5} /> : <Eye size={16} strokeWidth={1.5} />}
          </button>
        </span>
      </label>
      <p className="form-error" role="alert" data-show={!!error}>{error}</p>
      <button className="btn btn-primary btn-block" disabled={busy || !user || !password}>
        {busy ? "Signing in" : "Sign in"}
      </button>
      <Link href="/" className="btn btn-secondary btn-block">Continue without signing in</Link>
    </form>
  );
}
