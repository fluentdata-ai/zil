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
