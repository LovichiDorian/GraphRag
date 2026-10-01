import { GeistMono } from "geist/font/mono";
import { GeistSans } from "geist/font/sans";
import type { Metadata, Viewport } from "next";
import type { ReactNode } from "react";
import { THEME_COLORS, THEME_SCRIPT } from "@/lib/theme-script";
import "./globals.css";

const SITE = "https://graphrag.dorianlovichi.com";
const DESCRIPTION =
  "Ask anything about Dorian Lovichi — full-stack software engineer (applied AI & DevOps). An agentic GraphRAG over his CV and GitHub answers with citations and lights up the evidence in a 3D knowledge graph.";

export const metadata: Metadata = {
  metadataBase: new URL(SITE),
  title: { default: "Dorian Lovichi — Ask my career graph", template: "%s · Dorian Lovichi" },
  description: DESCRIPTION,
  applicationName: "Dorian Lovichi Career Graph",
  authors: [{ name: "Dorian Lovichi", url: "https://dorianlovichi.com" }],
  keywords: [
    "Dorian Lovichi",
    "GraphRAG",
    "Full-Stack Engineer",
    "AI Engineer",
    "Knowledge Graph",
    "Neo4j",
    "Kubernetes",
    "Résumé",
  ],
  openGraph: {
    type: "website",
    url: SITE,
    title: "Dorian Lovichi — Don't read my CV. Query it.",
    description: DESCRIPTION,
    siteName: "Dorian Lovichi",
  },
  twitter: {
    card: "summary_large_image",
    title: "Dorian Lovichi — Ask my career graph",
    description: DESCRIPTION,
  },
  robots: { index: true, follow: true },
};

export const viewport: Viewport = {
  themeColor: THEME_COLORS.light,
  colorScheme: "light",
  width: "device-width",
  initialScale: 1,
};

const personJsonLd = {
  "@context": "https://schema.org",
  "@type": "Person",
  name: "Dorian Lovichi",
  jobTitle: "Full-Stack Software Engineer — Applied AI & DevOps",
  url: SITE,
  email: "mailto:dorian@dorianlovichi.com",
  address: {
    "@type": "PostalAddress",
    addressLocality: "San Diego",
    addressRegion: "CA",
    addressCountry: "US",
  },
  sameAs: [
    "https://github.com/LovichiDorian",
    "https://linkedin.com/in/dorian-lovichi",
    "https://dorianlovichi.com",
  ],
  alumniOf: [{ "@type": "CollegeOrUniversity", name: "Università di Corsica" }],
  knowsAbout: [
    "GraphRAG",
    "LLMs",
    "AI agents",
    "TypeScript",
    "Python",
    "React",
    "Angular",
    "Kubernetes",
    "Docker",
  ],
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    // The theme script may set data-theme before hydration.
    <html lang="en" className={`${GeistSans.variable} ${GeistMono.variable}`} suppressHydrationWarning>
      <head>
        <script
          // biome-ignore lint/security/noDangerouslySetInnerHtml: static script, restores the saved theme before paint
          dangerouslySetInnerHTML={{ __html: THEME_SCRIPT }}
        />
      </head>
      <body className="font-sans">
        {children}
        <script
          type="application/ld+json"
          // biome-ignore lint/security/noDangerouslySetInnerHtml: static, trusted JSON-LD
          dangerouslySetInnerHTML={{ __html: JSON.stringify(personJsonLd) }}
        />
      </body>
    </html>
  );
}
