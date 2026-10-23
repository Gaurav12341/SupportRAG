import type { Metadata } from "next";
import { redirect } from "next/navigation";
import { AdminConsole } from "@/components/AdminConsole";
import { getSession, load } from "@/lib/server";
import { PRODUCTS, type AdminUser, type AuditEntry, type Library, type Product } from "@/lib/types";

export const metadata: Metadata = { title: "Users and licenses" };

export default async function AdminPage() {
  const { session } = await getSession();
  if (session.role !== "admin") redirect("/");
  const [users, audit, library] = await Promise.all([
    load<{ users: AdminUser[] }>("/admin/users"),
    load<{ entries: AuditEntry[] }>("/admin/audit"),
    load<Library>("/documents"), // an admin reads every page, so this is the whole corpus
  ]);
  if (!users) return <div className="empty-frame">Could not load the users. Check that the API and MongoDB are running, then reload.</div>;
  const gated = Object.fromEntries(PRODUCTS.map((p) => [p, (library?.documents ?? []).filter((d) => d.product === p && d.access_level !== "public").length])) as Record<Product, number>;
  return <AdminConsole me={session.user!} initialUsers={users.users} initialAudit={audit?.entries ?? []} gated={library ? gated : null} />;
}
