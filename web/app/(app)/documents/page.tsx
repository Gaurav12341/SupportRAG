import type { Metadata } from "next";
import { DocsExplorer } from "@/components/DocsExplorer";
import { int } from "@/lib/format";
import { getSession, load } from "@/lib/server";
import type { Library } from "@/lib/types";

export const metadata: Metadata = { title: "Documents" };

export default async function DocumentsPage() {
  const { session } = await getSession();
  const library = await load<Library>("/documents");
  const locked = library ? Object.values(library.locked).reduce((a, b) => a + (b ?? 0), 0) : 0;
  return (
    <>
      <div className="title-row">
        <div>
          <h1>Documents</h1>
          <p className="subline">
            {library
              ? `${int(library.documents.length)} pages (${int(library.chunks)} passages) are searched for this account${locked ? `; ${int(locked)} more are locked` : ""}. Access levels are simulated on public documentation.`
              : "The document list could not be loaded."}
          </p>
        </div>
      </div>
      {library ? <DocsExplorer library={library} session={session} /> : <div className="empty-frame">Could not load the documents. Check that the API is running, then reload.</div>}
    </>
  );
}
