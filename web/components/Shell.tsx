"use client";
import { ChartColumn, FileText, LogOut, MessageSquare, ShieldCheck } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { session as sessionApi } from "@/lib/client";
import { PRODUCT_NAME, type Session } from "@/lib/types";
import { Mark } from "./Mark";

const ICON = { size: 18, strokeWidth: 1.5, "aria-hidden": true } as const;

/** The icon rail (a bottom bar on a phone). Every icon has an accessible name and a tooltip. */
export function Rail({ role }: { role: Session["role"] }) {
  const path = usePathname();
  const items = [
    { href: "/", label: "Ask", icon: <MessageSquare {...ICON} /> },
    { href: "/documents", label: "Documents", icon: <FileText {...ICON} /> },
    { href: "/evaluation", label: "Evaluation", icon: <ChartColumn {...ICON} /> },
    ...(role === "admin" ? [{ href: "/admin", label: "Users", icon: <ShieldCheck {...ICON} /> }] : []),
  ];
  return (
    <nav className="rail" aria-label="Main">
      <Link href="/" className="rail-mark" aria-label="SupportRAG home" data-tip="SupportRAG">
        <Mark />
      </Link>
      <ul>
        {items.map((it) => {
          const here = it.href === "/" ? path === "/" : path.startsWith(it.href);
          return (
            <li key={it.href}>
              <Link href={it.href} aria-current={here ? "page" : undefined} aria-label={it.label} data-tip={it.label}>
                {it.icon}
                <span className="rail-label">{it.label}</span>
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}

const scopeText = (s: Session) =>
  s.role === "admin" ? "Admin, reads every document" : s.role === "member" ? `Member, ${s.licenses.length} ${s.licenses.length === 1 ? "license" : "licenses"}` : "Public documents only";

export function TopBar({ session }: { session: Session }) {
  return (
    <header className="topbar">
      <div className="scope">
        <span className="wordmark">SupportRAG</span>
        <span className="scope-pill" data-role={session.role}>
          {scopeText(session)}
        </span>
      </div>
      {session.user ? <UserMenu session={session} /> : <Link href="/login" className="btn btn-primary btn-sm">Sign in</Link>}
    </header>
  );
}

function UserMenu({ session }: { session: Session }) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  const router = useRouter();

  useEffect(() => {
    if (!open) return;
    const away = (e: MouseEvent) => !box.current?.contains(e.target as Node) && setOpen(false);
    const esc = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", away);
    document.addEventListener("keydown", esc);
    return () => {
      document.removeEventListener("mousedown", away);
      document.removeEventListener("keydown", esc);
    };
  }, [open]);

  async function signOut() {
    setBusy(true);
    try {
      await sessionApi.signOut();
    } finally {
      router.replace("/login");
      router.refresh();
    }
  }

  return (
    <div className="menu-wrap" ref={box}>
      <button className="user-chip" aria-haspopup="menu" aria-expanded={open} onClick={() => setOpen((o) => !o)}>
        <span className="avatar" data-hue={session.user!.charCodeAt(0) % 6} aria-hidden="true">{session.user![0].toUpperCase()}</span>
        <span className="user-name">{session.user}</span>
      </button>
      <div className="menu" role="menu" data-open={open} aria-hidden={!open}>
        <div className="menu-head">
          <strong>{session.user}</strong>
          <span>{session.role === "admin" ? "Admin" : "Member"}</span>
        </div>
        <ul className="menu-licenses" aria-label="Licenses">
          {session.role === "admin" ? <li>All products</li> : session.licenses.length ? session.licenses.map((p) => <li key={p}>{PRODUCT_NAME[p]}</li>) : <li className="muted">No licenses yet</li>}
        </ul>
        <button className="menu-item" role="menuitem" onClick={signOut} disabled={busy}>
          <LogOut size={16} strokeWidth={1.5} aria-hidden="true" /> Sign out
        </button>
      </div>
    </div>
  );
}
