import type { Metadata } from "next";
import { Chat } from "@/components/Chat";
import { getSession, load } from "@/lib/server";
import type { Library } from "@/lib/types";

export const metadata: Metadata = { title: "Ask" };

export default async function AskPage() {
  const { session } = await getSession();
  const library = await load<Library>("/documents");
  const locked = library ? Object.values(library.locked).reduce((a, b) => a + (b ?? 0), 0) : 0;
  const scope = library ? { pages: library.documents.length, chunks: library.chunks, locked } : null;
  return <Chat session={session} scope={scope} />;
}
