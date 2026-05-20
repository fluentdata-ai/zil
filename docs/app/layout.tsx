import { Footer, Layout, Navbar } from "nextra-theme-docs";
import { Banner, Head } from "nextra/components";
import { getPageMap } from "nextra/page-map";
import type { Metadata } from "next";
import type { ReactNode } from "react";
import { Analytics } from "@vercel/analytics/next";
import "nextra-theme-docs/style.css";

export const metadata: Metadata = {
  title: {
    default: "Zil Documentation",
    template: "%s — Zil Docs",
  },
  description:
    "Documentation for the Zil framework — build, validate, package, and deploy production AI agents.",
  metadataBase: new URL("https://getzil.dev/docs"),
};

const navbar = (
  <Navbar
    logo={
      <span style={{ display: "flex", alignItems: "center", gap: 8, fontWeight: 700, fontSize: 18 }}>
        <svg width="14" height="14" viewBox="0 0 32 32" xmlns="http://www.w3.org/2000/svg">
          <circle cx="16" cy="16" r="6" fill="#e8c87a" />
        </svg>
        zil<span style={{ fontWeight: 400, opacity: 0.5 }}>/docs</span>
        <span style={{ fontSize: 10, fontWeight: 600, letterSpacing: "0.05em", textTransform: "uppercase", padding: "2px 6px", borderRadius: 4, background: "rgba(232,200,122,0.15)", color: "#b8860b", marginLeft: 4 }}>v0.1 draft</span>
      </span>
    }
    projectLink="https://github.com/fluentdata-co/zil"
    chatLink="https://join.slack.com/t/zilorg/shared_invite/zt-3xye83sw1-cU3H1Hb_yFbmyBBgbt5VGQ"
    chatIcon={<svg viewBox="0 0 24 24" fill="currentColor" width="24" height="24" xmlns="http://www.w3.org/2000/svg"><path d="M5.042 15.165a2.528 2.528 0 0 1-2.52 2.523A2.528 2.528 0 0 1 0 15.165a2.527 2.527 0 0 1 2.522-2.52h2.52v2.52zm1.271 0a2.527 2.527 0 0 1 2.521-2.52 2.527 2.527 0 0 1 2.521 2.52v6.313A2.528 2.528 0 0 1 8.834 24a2.528 2.528 0 0 1-2.521-2.522v-6.313zM8.834 5.042a2.528 2.528 0 0 1-2.521-2.52A2.528 2.528 0 0 1 8.834 0a2.528 2.528 0 0 1 2.521 2.522v2.52H8.834zm0 1.271a2.528 2.528 0 0 1 2.521 2.521 2.528 2.528 0 0 1-2.521 2.521H2.522A2.528 2.528 0 0 1 0 8.834a2.528 2.528 0 0 1 2.522-2.521h6.312zm10.122 2.521a2.528 2.528 0 0 1 2.522-2.521A2.528 2.528 0 0 1 24 8.834a2.528 2.528 0 0 1-2.522 2.521h-2.522V8.834zm-1.268 0a2.528 2.528 0 0 1-2.523 2.521 2.527 2.527 0 0 1-2.52-2.521V2.522A2.527 2.527 0 0 1 15.165 0a2.528 2.528 0 0 1 2.523 2.522v6.312zm-2.523 10.122a2.528 2.528 0 0 1 2.523 2.522A2.528 2.528 0 0 1 15.165 24a2.527 2.527 0 0 1-2.52-2.522v-2.522h2.52zm0-1.268a2.527 2.527 0 0 1-2.52-2.523 2.526 2.526 0 0 1 2.52-2.52h6.313A2.527 2.527 0 0 1 24 15.165a2.528 2.528 0 0 1-2.522 2.523h-6.313z"/></svg>}
  />
);

const banner = (
  <Banner storageKey="zil-v01-banner">
    ⚠️ v0.1 — Early preview. APIs and schema may change.
  </Banner>
);

const footer = (
  <Footer className="flex-col items-center md:items-start">
    <div style={{ display: "flex", alignItems: "center", gap: 24, flexWrap: "wrap" }}>
      <a
        href="https://fluentdata.ai"
        target="_blank"
        rel="noopener noreferrer"
        style={{ display: "flex", alignItems: "center", gap: 6 }}
      >
        Powered by
        <img
          src="/fluentdata-logo/MasterLogo_Mono_Positive.png"
          alt="FluentData"
          height={20}
          className="fd-logo-dark"
        />
        <img
          src="/fluentdata-logo/MasterLogo_Mono_Negative.png"
          alt="FluentData"
          height={20}
          className="fd-logo-light"
        />
      </a>
      <span style={{ color: "var(--nx-colors-gray-500)", fontSize: 13 }}>·</span>
      <a
        href="https://join.slack.com/t/zilorg/shared_invite/zt-3xye83sw1-cU3H1Hb_yFbmyBBgbt5VGQ"
        target="_blank"
        rel="noopener noreferrer"
        style={{ fontSize: 13, opacity: 0.7 }}
      >
        Community Slack
      </a>
      <span style={{ color: "var(--nx-colors-gray-500)", fontSize: 13 }}>·</span>
      <a
        href="https://github.com/fluentdata-co/zil/discussions"
        target="_blank"
        rel="noopener noreferrer"
        style={{ fontSize: 13, opacity: 0.7 }}
      >
        Discussions
      </a>
    </div>
  </Footer>
);

export default async function RootLayout({
  children,
}: {
  children: ReactNode;
}) {
  return (
    <html lang="en" dir="ltr" suppressHydrationWarning>
      <Head>
        <link rel="icon" href="/favicon.svg" type="image/svg+xml" />
        <style>{`
          .fd-logo-light, .fd-logo-dark { height: 20px; width: auto; }
          .fd-logo-dark { display: none; }
          .dark .fd-logo-light { display: none; }
          .dark .fd-logo-dark { display: inline; }
        `}</style>
      </Head>
      <body>
        <Layout
          banner={banner}
          navbar={navbar}
          pageMap={await getPageMap()}
          docsRepositoryBase="https://github.com/fluentdata-co/zil/tree/main/docs"
          editLink="Edit this page on GitHub"
          sidebar={{ defaultMenuCollapseLevel: 1 }}
          footer={footer}
        >
          {children}
        </Layout>
        <Analytics />
      </body>
    </html>
  );
}
