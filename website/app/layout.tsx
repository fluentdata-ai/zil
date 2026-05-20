import type { Metadata } from "next";
import { Analytics } from "@vercel/analytics/next";
import "./globals.css";

export const metadata: Metadata = {
  metadataBase: new URL("https://getzil.dev"),
  title: "Zil — A framework for production AI agents",
  description:
    "Zil is an open-source CLI and Python SDK for validating, packaging, and deploying production AI agents. Composes with ADK, MCP, DeepEval, and OpenTelemetry. By FluentData.",
  keywords: [
    "AI agents",
    "agentic AI",
    "agent framework",
    "agent CLI",
    "AgentOps",
    "MCP",
    "ADK",
    "FluentData",
    "Zil",
    "production AI",
  ],
  authors: [{ name: "FluentData", url: "https://fluentdata.ai" }],
  creator: "FluentData",
  openGraph: {
    title: "Zil — A framework for production AI agents",
    description:
      "An open-source CLI and SDK for validating, packaging, and deploying production AI agents.",
    url: "https://getzil.dev",
    siteName: "Zil",
    type: "website",
    images: [{ url: "/opengraph-image", width: 1200, height: 630 }],
  },
  twitter: {
    card: "summary_large_image",
    title: "Zil — A framework for production AI agents",
    description:
      "An open-source CLI and SDK for validating, packaging, and deploying production AI agents.",
    images: ["/opengraph-image"],
  },
  robots: { index: true, follow: true },
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <head>
        <link rel="icon" href="/favicon.svg" type="image/svg+xml" />
        <link rel="apple-touch-icon" href="/favicon.svg" />
        <link rel="agent-info" href="/agent.txt" type="text/plain" />
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link
          rel="preconnect"
          href="https://fonts.gstatic.com"
          crossOrigin="anonymous"
        />
        <link
          href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,300;9..144,400;9..144,500;9..144,600;9..144,700&family=JetBrains+Mono:wght@400;500;700&family=Inter:wght@300;400;500;600;700&display=swap"
          rel="stylesheet"
        />
      </head>
      <body>
        {children}
        <Analytics />
      </body>
    </html>
  );
}
