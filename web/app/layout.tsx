import type { Metadata, Viewport } from "next";
import { GeistMono } from "geist/font/mono";
import { GeistSans } from "geist/font/sans";
import { MotionConfig } from "motion/react";
import "./globals.css";

export const metadata: Metadata = {
  title: { default: "SupportRAG", template: "%s · SupportRAG" },
  description: "Support answers that cite the docs, or say there is no documented fix.",
};
export const viewport: Viewport = { themeColor: "#f2f4f7" };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${GeistSans.variable} ${GeistMono.variable}`}>
      <body>
        <MotionConfig reducedMotion="user">{children}</MotionConfig>
      </body>
    </html>
  );
}
