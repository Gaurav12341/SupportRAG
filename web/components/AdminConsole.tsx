"use client";
import { Check, Copy, KeyRound, Plus } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useCallback, useEffect, useState, type FormEvent } from "react";
import { api, ApiError } from "@/lib/client";
import { ago, stamp } from "@/lib/format";
import { PRODUCT_NAME, PRODUCTS, type AdminUser, type AuditEntry, type Product } from "@/lib/types";

const EASE_OUT = [0.23, 1, 0.32, 1] as const;
const ALPHABET = "abcdefghijkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"; // no look-alikes (0/O, 1/l/I)

function generatePassword(length = 16) {
  const bytes = crypto.getRandomValues(new Uint8Array(length));
  return Array.from(bytes, (b) => ALPHABET[b % ALPHABET.length]).join("");
}

const ACTION: Record<string, (e: AuditEntry) => string> = {
  grant: (e) => `granted ${PRODUCT_NAME[e.product as Product] ?? e.product} to ${e.user_id}`,
  revoke: (e) => `revoked ${PRODUCT_NAME[e.product as Product] ?? e.product} from ${e.user_id}`,
  "add_user:member": (e) => `added ${e.user_id} as a member`,
  "add_user:admin": (e) => `added ${e.user_id} as an admin`,
  bootstrap_admin: (e) => `set up ${e.user_id} as the first admin`,
};
const describe = (e: AuditEntry) => (ACTION[e.action] ?? ((x: AuditEntry) => `${x.action} ${x.user_id}`))(e);

export function AdminConsole({ me, initialUsers, initialAudit, gated }: { me: string; initialUsers: AdminUser[]; initialAudit: AuditEntry[]; gated: Record<Product, number> | null }) {
  const [users, setUsers] = useState(initialUsers);
  const [audit, setAudit] = useState(initialAudit);
  const [rowError, setRowError] = useState<Record<string, string>>({});
  const [saved, setSaved] = useState<string | null>(null);
  const [now, setNow] = useState<number | null>(null);
  useEffect(() => setNow(Date.now()), [audit]);

  const refreshAudit = useCallback(async () => {
    try { setAudit((await api<{ entries: AuditEntry[] }>("admin/audit")).entries); } catch { /* the list just stays as it was */ }
  }, []);

  async function toggle(u: AdminUser, product: Product) {
    const had = u.licenses.includes(product);
    const set = (licenses: Product[]) => setUsers((all) => all.map((x) => (x.user === u.user ? { ...x, licenses } : x)));
    set(had ? u.licenses.filter((p) => p !== product) : [...u.licenses, product]);
    setRowError((e) => ({ ...e, [u.user]: "" }));
    try {
      const r = await api<{ licenses: Product[] }>(`admin/users/${encodeURIComponent(u.user)}/licenses/${product}`, had ? "DELETE" : "PUT");
      set(r.licenses);
      setSaved(u.user);
      window.setTimeout(() => setSaved((s) => (s === u.user ? null : s)), 1600);
      void refreshAudit();
    } catch (e) {
      set(u.licenses);
      setRowError((x) => ({ ...x, [u.user]: e instanceof ApiError ? e.message : "Could not save." }));
    }
  }

  // ----- add a user -----
  const [name, setName] = useState("");
  const [role, setRole] = useState<"member" | "admin">("member");
  const [password, setPassword] = useState("");
  const [formError, setFormError] = useState("");
  const [busy, setBusy] = useState(false);
  const [created, setCreated] = useState<{ user: string; password: string } | null>(null);
  const [copied, setCopied] = useState(false);
  useEffect(() => setPassword(generatePassword()), []);

  async function add(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setFormError("");
    try {
      const made = await api<{ user: string; role: "member" | "admin"; licenses: Product[] }>("admin/users", "POST", { user: name.trim(), password, role });
      setUsers((all) => [...all, { ...made, created_at: Date.now() / 1000, created_by: me }].sort((a, b) => a.user.localeCompare(b.user)));
      setCreated({ user: made.user, password });
      setName("");
      setPassword(generatePassword());
      void refreshAudit();
    } catch (err) {
      setFormError(err instanceof ApiError ? err.message : "Could not create the user.");
    } finally {
      setBusy(false);
    }
  }

  async function copy(text: string) {
    try { await navigator.clipboard.writeText(text); setCopied(true); window.setTimeout(() => setCopied(false), 1500); } catch { /* clipboard blocked: the password stays visible */ }
  }

  const licensed = users.filter((u) => u.role === "member" && u.licenses.length).length;

  return (
    <>
      <div className="title-row">
        <div>
          <h1>Users and licenses</h1>
          <p className="subline">
            {users.length} {users.length === 1 ? "user" : "users"}; {licensed} {licensed === 1 ? "member holds" : "members hold"} at least one license. A license lets a member
            read the internal and restricted pages of one product. Changes apply on that user&apos;s next request.
          </p>
        </div>
      </div>

      <div className="admin-grid">
        <div className="stack">
        <section className="card table-card" aria-label="Users">
          <table className="users">
            <thead>
              <tr>
                <th scope="col">User</th>
                <th scope="col">Role</th>
                {PRODUCTS.map((p) => <th scope="col" key={p} className="col-product">{PRODUCT_NAME[p]}</th>)}
              </tr>
            </thead>
            <tbody>
              <AnimatePresence initial={false}>
                {users.map((u) => (
                  <motion.tr
                    key={u.user}
                    initial={{ opacity: 0, transform: "translateY(8px)" }}
                    animate={{ opacity: 1, transform: "translateY(0px)" }}
                    exit={{ opacity: 0 }}
                    transition={{ duration: 0.2, ease: EASE_OUT }}
                  >
                    <th scope="row" className="user-cell">
                      <span className="avatar" data-hue={u.user.charCodeAt(0) % 6} aria-hidden="true">{u.user[0].toUpperCase()}</span>
                      <span className="user-meta">
                        <span className="user-line">
                          {u.user}{u.user === me && <span className="muted"> (you)</span>}
                          <span className="saved small" data-show={saved === u.user} aria-hidden={saved !== u.user}><Check size={12} strokeWidth={2} aria-hidden="true" /> Saved</span>
                        </span>
                        {rowError[u.user] && <span className="row-error small" role="alert">{rowError[u.user]}</span>}
                      </span>
                    </th>
                    <td data-label="Role"><span className="pill" data-role={u.role}>{u.role === "admin" ? "Admin" : "Member"}</span></td>
                    {u.role === "admin" ? (
                      <td colSpan={PRODUCTS.length} className="all-access muted">Reads every document</td>
                    ) : (
                      PRODUCTS.map((p) => (
                        <td key={p} className="col-product" data-label={PRODUCT_NAME[p]}>
                          <button
                            role="switch" aria-checked={u.licenses.includes(p)} className="switch"
                            aria-label={`${PRODUCT_NAME[p]} license for ${u.user}`}
                            onClick={() => void toggle(u, p)}
                          />
                        </td>
                      ))
                    )}
                  </motion.tr>
                ))}
              </AnimatePresence>
            </tbody>
          </table>
        </section>
          {gated && (
            <section className="card pad coverage" aria-labelledby="cov-h">
              <h2 id="cov-h">What a license unlocks</h2>
              <p className="muted small">Internal and restricted pages are readable only with the product&apos;s license. Public pages are open to everyone. Access levels are simulated.</p>
              <table className="plain">
                <thead><tr><th scope="col">Product</th><th scope="col" className="num">Pages behind a license</th><th scope="col" className="num">Members licensed</th></tr></thead>
                <tbody>
                  {PRODUCTS.map((p) => (
                    <tr key={p}>
                      <td>{PRODUCT_NAME[p]}</td>
                      <td className="num">{gated[p]}</td>
                      <td className="num">{users.filter((u) => u.role === "member" && u.licenses.includes(p)).length}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </section>
          )}
        </div>

        <div className="admin-side">
          <section className="card pad" aria-labelledby="add-h">
            <h2 id="add-h">Add a user</h2>
            <p className="muted small">Set a temporary password and hand it over. It is stored only as a salted, peppered hash and cannot be shown again.</p>
            <form className="form" onSubmit={add}>
              <label className="field">
                <span>User name</span>
                <input value={name} onChange={(e) => setName(e.target.value)} autoComplete="off" autoCapitalize="none" spellCheck={false} placeholder="for example carol" required />
              </label>
              <label className="field">
                <span>Role</span>
                <select value={role} onChange={(e) => setRole(e.target.value as "member" | "admin")}>
                  <option value="member">Member (licenses decide what they read)</option>
                  <option value="admin">Admin (reads everything, manages users)</option>
                </select>
              </label>
              <label className="field">
                <span>Temporary password</span>
                <span className="input-join">
                  <input className="mono" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="off" spellCheck={false} minLength={10} required />
                  <button type="button" className="input-action" onClick={() => setPassword(generatePassword())} aria-label="Generate another password"><KeyRound size={16} strokeWidth={1.5} /></button>
                </span>
              </label>
              <p className="form-error" role="alert" data-show={!!formError}>{formError}</p>
              <button className="btn btn-primary btn-block" disabled={busy || !name.trim() || password.length < 10}>
                <Plus size={16} strokeWidth={1.5} aria-hidden="true" /> {busy ? "Adding" : "Add user"}
              </button>
            </form>
            <AnimatePresence>
              {created && (
                <motion.div
                  className="created" role="status"
                  initial={{ opacity: 0, transform: "translateY(6px)" }} animate={{ opacity: 1, transform: "translateY(0px)" }} exit={{ opacity: 0 }}
                  transition={{ duration: 0.2, ease: EASE_OUT }}
                >
                  <p><strong>{created.user}</strong> can sign in now. Copy the password before you leave; it is not stored.</p>
                  <span className="input-join">
                    <input className="mono" readOnly value={created.password} aria-label={`Password for ${created.user}`} onFocus={(e) => e.currentTarget.select()} />
                    <button type="button" className="input-action" onClick={() => void copy(created.password)} aria-label="Copy password">
                      {copied ? <Check size={16} strokeWidth={1.75} /> : <Copy size={16} strokeWidth={1.5} />}
                    </button>
                  </span>
                  <button className="btn btn-secondary btn-sm" onClick={() => setCreated(null)}>Done</button>
                </motion.div>
              )}
            </AnimatePresence>
          </section>

          <section className="card pad" aria-labelledby="audit-h">
            <h2 id="audit-h">Recent changes</h2>
            {audit.length === 0 ? (
              <div className="empty-frame">No changes yet.</div>
            ) : (
              <ul className="audit">
                <AnimatePresence initial={false}>
                  {audit.slice(0, 6).map((e) => (
                    <motion.li
                      key={`${e.at}-${e.action}-${e.user_id}-${e.product}`} layout="position"
                      initial={{ opacity: 0, transform: "translateY(-6px)" }} animate={{ opacity: 1, transform: "translateY(0px)" }}
                      transition={{ duration: 0.2, ease: EASE_OUT }}
                    >
                      <span><strong>{e.actor}</strong> {describe(e)}</span>
                      <time className="muted small" dateTime={new Date(e.at * 1000).toISOString()} title={stamp(e.at)} suppressHydrationWarning>
                        {now ? ago(e.at, now) : ""}
                      </time>
                    </motion.li>
                  ))}
                </AnimatePresence>
              </ul>
            )}
          </section>
        </div>
      </div>
    </>
  );
}
