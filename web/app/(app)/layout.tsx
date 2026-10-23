import { redirect } from "next/navigation";
import { Rail, TopBar } from "@/components/Shell";
import { getSession } from "@/lib/server";

export default async function AppLayout({ children }: { children: React.ReactNode }) {
  const { session, expired, down } = await getSession();
  if (expired) redirect("/api/session/expired");
  return (
    <div className="app">
      <Rail role={session.role} />
      <div className="main">
        <TopBar session={session} />
        {down && (
          <p className="notice" role="status">
            The API did not answer, so you are seen as signed out. Start it with <code>uvicorn src.api:app --port 8000</code>.
          </p>
        )}
        <main className="canvas">{children}</main>
      </div>
    </div>
  );
}
