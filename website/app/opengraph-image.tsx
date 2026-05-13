import { ImageResponse } from "next/og";

export const runtime = "edge";
export const alt = "Zil - A framework for production AI agents";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

export default async function Image() {
  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          flexDirection: "column",
          justifyContent: "center",
          alignItems: "flex-start",
          padding: "80px 100px",
          background: "#0a0a0c",
          position: "relative",
          overflow: "hidden",
        }}
      >
        {/* Subtle gradient overlay */}
        <div
          style={{
            position: "absolute",
            top: "-200px",
            right: "-200px",
            width: "800px",
            height: "800px",
            borderRadius: "50%",
            background:
              "radial-gradient(circle, rgba(232,200,122,0.08) 0%, transparent 70%)",
          }}
        />

        {/* Accent dot */}
        <div
          style={{
            width: "16px",
            height: "16px",
            borderRadius: "50%",
            background: "#e8c87a",
            boxShadow: "0 0 20px rgba(232,200,122,0.5)",
            marginBottom: "32px",
          }}
        />

        {/* Wordmark */}
        <div
          style={{
            fontSize: "120px",
            fontWeight: 300,
            fontStyle: "italic",
            color: "#f4f4f7",
            letterSpacing: "-0.03em",
            lineHeight: 1,
            marginBottom: "24px",
          }}
        >
          Zil
        </div>

        {/* Tagline */}
        <div
          style={{
            fontSize: "36px",
            fontWeight: 300,
            color: "#b8b8c2",
            letterSpacing: "-0.01em",
            lineHeight: 1.3,
            maxWidth: "700px",
            marginBottom: "48px",
          }}
        >
          A framework for production AI agents
        </div>

        {/* Pillars line */}
        <div
          style={{
            display: "flex",
            gap: "24px",
            alignItems: "center",
          }}
        >
          {[
            "Governance",
            "Security",
            "Data",
            "Observability",
            "Evaluation",
            "Cost",
            "Architecture",
          ].map((pillar) => (
            <div
              key={pillar}
              style={{
                fontSize: "13px",
                fontWeight: 500,
                color: "#8a8a96",
                letterSpacing: "0.12em",
                textTransform: "uppercase" as const,
              }}
            >
              {pillar}
            </div>
          ))}
        </div>

        {/* Bottom bar */}
        <div
          style={{
            position: "absolute",
            bottom: "60px",
            left: "100px",
            right: "100px",
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            borderTop: "1px solid #22222a",
            paddingTop: "24px",
          }}
        >
          <div
            style={{
              fontSize: "14px",
              fontWeight: 500,
              color: "#5a5a66",
              letterSpacing: "0.08em",
              textTransform: "uppercase" as const,
            }}
          >
            getzil.dev
          </div>
          <div
            style={{
              fontSize: "14px",
              fontWeight: 500,
              color: "#e8c87a",
              letterSpacing: "0.08em",
              textTransform: "uppercase" as const,
            }}
          >
            Open Source &middot; Apache 2.0
          </div>
          <div
            style={{
              fontSize: "14px",
              fontWeight: 500,
              color: "#5a5a66",
              letterSpacing: "0.08em",
              textTransform: "uppercase" as const,
            }}
          >
            by FluentData
          </div>
        </div>
      </div>
    ),
    { ...size }
  );
}
