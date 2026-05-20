import Link from "next/link";
import Image from "next/image";
import styles from "./page.module.css";

const steps = [
  {
    num: "01",
    name: "zil init",
    body: "Scaffold a complete agent project — manifest, identity, adapters, evals, guardrails, Dockerfile, CI pipeline. Choose your LLM provider and MCP preset.",
  },
  {
    num: "02",
    name: "zil validate",
    body: "Check manifest schema, file references, env var declarations, MCP server config, and guardrail structure. Catch misconfigurations before they reach production.",
  },
  {
    num: "03",
    name: "zil audit",
    body: "Security scan: prompt injection resilience, PII leakage, indirect injection surface, guardrail coverage scoring. Actionable findings, not compliance theater.",
  },
  {
    num: "04",
    name: "zil eval",
    body: "Run evaluation suites with LLM-as-judge metrics — answer relevancy, faithfulness, contextual recall. Gate promotions on quality thresholds.",
  },
  {
    num: "05",
    name: "zil pack",
    body: "Build a signed .zil archive: manifest, agent code, MCP tools, SBOM, eval results — one portable artifact. Cosign signature and SLSA provenance included.",
  },
  {
    num: "06",
    name: "zil push",
    body: "Push the archive to any OCI-compatible registry — Google Artifact Registry, GHCR, ECR, Docker Hub. Same tooling you already use for containers.",
  },
  {
    num: "07",
    name: "zil deploy",
    body: "Deploy to Cloud Run from source or from a registry artifact. MCP server host dependencies, env vars, and tracing — handled automatically.",
  },
];

export default function Home() {
  return (
    <main>
      {/* ============ TOP NAV ============ */}
      <nav className="topNav">
        <Link href="/" className="topNavBrand">
          <span className="topNavBrandDot" />
          Zil
        </Link>
        <div className="topNavLinks">
          <Link href="/docs" className="topNavLink">
            <span>Docs</span>
          </Link>
          <a
            href="https://join.slack.com/t/zilorg/shared_invite/zt-3xye83sw1-cU3H1Hb_yFbmyBBgbt5VGQ"
            target="_blank"
            rel="noopener noreferrer"
            className="topNavLink"
          >
            <svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg"><path d="M5.042 15.165a2.528 2.528 0 0 1-2.52 2.523A2.528 2.528 0 0 1 0 15.165a2.527 2.527 0 0 1 2.522-2.52h2.52v2.52zm1.271 0a2.527 2.527 0 0 1 2.521-2.52 2.527 2.527 0 0 1 2.521 2.52v6.313A2.528 2.528 0 0 1 8.834 24a2.528 2.528 0 0 1-2.521-2.522v-6.313zM8.834 5.042a2.528 2.528 0 0 1-2.521-2.52A2.528 2.528 0 0 1 8.834 0a2.528 2.528 0 0 1 2.521 2.522v2.52H8.834zm0 1.271a2.528 2.528 0 0 1 2.521 2.521 2.528 2.528 0 0 1-2.521 2.521H2.522A2.528 2.528 0 0 1 0 8.834a2.528 2.528 0 0 1 2.522-2.521h6.312zm10.122 2.521a2.528 2.528 0 0 1 2.522-2.521A2.528 2.528 0 0 1 24 8.834a2.528 2.528 0 0 1-2.522 2.521h-2.522V8.834zm-1.268 0a2.528 2.528 0 0 1-2.523 2.521 2.527 2.527 0 0 1-2.52-2.521V2.522A2.527 2.527 0 0 1 15.165 0a2.528 2.528 0 0 1 2.523 2.522v6.312zm-2.523 10.122a2.528 2.528 0 0 1 2.523 2.522A2.528 2.528 0 0 1 15.165 24a2.527 2.527 0 0 1-2.52-2.522v-2.522h2.52zm0-1.268a2.527 2.527 0 0 1-2.52-2.523 2.526 2.526 0 0 1 2.52-2.52h6.313A2.527 2.527 0 0 1 24 15.165a2.528 2.528 0 0 1-2.522 2.523h-6.313z"/></svg>
            <span>Slack</span>
          </a>
          <a
            href="https://github.com/fluentdata-co/zil"
            target="_blank"
            rel="noopener noreferrer"
            className="topNavStar"
          >
            <svg viewBox="0 0 16 16" xmlns="http://www.w3.org/2000/svg"><path d="M8 .2l2.5 5 5.5.8-4 3.9.9 5.4L8 12.6l-4.9 2.7.9-5.4-4-3.9 5.5-.8z"/></svg>
            <span>Star</span>
            <svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg" style={{width: 14, height: 14}}><path d="M12 0c-6.626 0-12 5.373-12 12 0 5.302 3.438 9.8 8.207 11.387.599.111.793-.261.793-.577v-2.234c-3.338.726-4.033-1.416-4.033-1.416-.546-1.387-1.333-1.756-1.333-1.756-1.089-.745.083-.729.083-.729 1.205.084 1.839 1.237 1.839 1.237 1.07 1.834 2.807 1.304 3.492.997.107-.775.418-1.305.762-1.604-2.665-.305-5.467-1.334-5.467-5.931 0-1.311.469-2.381 1.236-3.221-.124-.303-.535-1.524.117-3.176 0 0 1.008-.322 3.301 1.23.957-.266 1.983-.399 3.003-.404 1.02.005 2.047.138 3.006.404 2.291-1.552 3.297-1.23 3.297-1.23.653 1.653.242 2.874.118 3.176.77.84 1.235 1.911 1.235 3.221 0 4.609-2.807 5.624-5.479 5.921.43.372.823 1.102.823 2.222v3.293c0 .319.192.694.801.576 4.765-1.589 8.199-6.086 8.199-11.386 0-6.627-5.373-12-12-12z"/></svg>
          </a>
        </div>
      </nav>

      {/* ============ HERO ============ */}
      <section className={styles.hero}>
        <div className={styles.heroGrid}>
          <span className={`eyebrow rise rise-delay-1 ${styles.heroEyebrow}`}>
            <span className={styles.dotMarker} />
            OPEN SOURCE · APACHE 2.0
          </span>

          <h1 className={`rise rise-delay-2 ${styles.heroTitle}`}>
            <span className={styles.heroLine}>A framework for</span>
            <span className={styles.heroLine}>
              <em className="italic-display">production</em>
            </span>
            <span className={styles.heroLine}>AI agents.</span>
          </h1>

          <p className={`lead rise rise-delay-3 ${styles.heroLead}`}>
            <span className={styles.zilWord}>Zil</span> is an open-source CLI and
            Python SDK for validating, packaging, and deploying AI agents.
            Open source. Composable. Deploys anywhere.
          </p>

          <div className={`rise rise-delay-4 ${styles.heroCtas}`}>
            <Link href="/docs/getting-started" className="btn btn-primary">
              Get Started <span className="btn-arrow">→</span>
            </Link>
            <Link href="/docs" className="btn">
              Documentation
            </Link>
            <a
              href="https://join.slack.com/t/zilorg/shared_invite/zt-3xye83sw1-cU3H1Hb_yFbmyBBgbt5VGQ"
              target="_blank"
              rel="noopener noreferrer"
              className="btn"
            >
              Join Slack <span className="btn-arrow">→</span>
            </a>
          </div>

          <div className={`rise rise-delay-5 ${styles.heroMeta}`}>
            <div className={styles.metaItem}>
              <span className="eyebrow-muted">Etymology</span>
              <span className={styles.metaValue}>
                Ag → silver → <em>zilver</em> → Zil
              </span>
            </div>
            <div className={styles.metaItem}>
              <span className="eyebrow-muted">Composes with</span>
              <span className={styles.metaValue}>ADK · MCP · DeepEval · OpenTelemetry</span>
            </div>
            <div className={styles.metaItem}>
              <span className="eyebrow-muted">Status</span>
              <span className={styles.metaValue}>v0.1 · Early preview</span>
            </div>
          </div>
        </div>

        {/* Decorative — large silvery wordmark */}
        <div aria-hidden="true" className={styles.heroWordmark}>
          ZIL
        </div>
      </section>

      <div className="divider" />

      {/* ============ WHY ZIL ============ */}
      <section id="why">
        <div className="container">
          <div className={styles.twoCol}>
            <div className={styles.colLeft}>
              <span className="eyebrow">01 — Why Zil</span>
              <h2 className={styles.sectionTitle}>
                There is no standard way to <em className="italic-display">ship</em> an AI agent.
              </h2>
            </div>
            <div className={styles.colRight}>
              <p className="lead">
                Most agent projects jump from notebook to production with no
                manifest, no eval gate, no signed artifact, and no security
                audit. The agent works in a demo — then breaks in ways that
                compound once real users, real data, and real tools are involved.
              </p>
              <p>
                Zil fills this gap. A declarative manifest (<code>manifest.yaml</code>)
                defines your agent&apos;s identity, adapters, tools, evals, and
                environment. A CLI validates, audits, evaluates, packages, and
                deploys — so every agent ships as a signed, portable{" "}
                <code>.zil</code> archive through a repeatable pipeline.
              </p>
            </div>
          </div>
        </div>
      </section>

      <div className="divider" />

      {/* ============ CLI WORKFLOW ============ */}
      <section className={styles.pillars}>
        <div className="container">
          <div className={styles.pillarsHeader}>
            <span className="eyebrow">02 — The CLI</span>
            <h2 className={styles.sectionTitle}>
              One CLI. Seven commands.{" "}
              <em className="italic-display">Init to deployed.</em>
            </h2>
            <p className="lead">
              Each command does one thing well. Together they form a complete
              pipeline from project scaffolding to production deployment.
            </p>
          </div>

          <ol className={styles.pillarList}>
            {steps.map((s) => (
              <li key={s.num} className={styles.pillarItem}>
                <div className={styles.pillarNum}>{s.num}</div>
                <div className={styles.pillarBody}>
                  <h3 className={styles.pillarName}>
                    <code>{s.name}</code>
                  </h3>
                  <p className={styles.pillarText}>{s.body}</p>
                </div>
              </li>
            ))}
          </ol>
        </div>
      </section>

      <div className="divider" />

      {/* ============ PACKAGE FORMAT ============ */}
      <section className={styles.codeSection}>
        <div className="container">
          <div className={styles.codeWrapper}>
            <div className={styles.codeIntro}>
              <span className="eyebrow">03 — The artifact</span>
              <h2 className={styles.sectionTitle}>
                <span className="mark">.zil</span> — a signed, portable agent bundle.
              </h2>
              <p className="lead">
                Every agent ships as a single signed archive containing its
                manifest, identity, adapters, MCP tools, evaluation results,
                and SBOM — packaged together, versioned together, deployed
                anywhere.
              </p>
              <div className={styles.codeStats}>
                <div className={styles.codeStat}>
                  <span className="eyebrow-muted">Signed by</span>
                  <span className={styles.codeStatValue}>cosign / Sigstore</span>
                </div>
                <div className={styles.codeStat}>
                  <span className="eyebrow-muted">Provenance</span>
                  <span className={styles.codeStatValue}>SLSA Level 3</span>
                </div>
                <div className={styles.codeStat}>
                  <span className="eyebrow-muted">Distribution</span>
                  <span className={styles.codeStatValue}>OCI registry</span>
                </div>
                <div className={styles.codeStat}>
                  <span className="eyebrow-muted">Deployable to</span>
                  <span className={styles.codeStatValue}>Cloud Run + more</span>
                </div>
              </div>
            </div>

            <pre className={styles.code}>
              <code>
                <span className={styles.codeComment}>
                  # my-agent-1.0.0.zil
                </span>
                {"\n"}
                <span className={styles.codeKey}>apiVersion:</span>{" "}
                <span className={styles.codeValue}>zil/v1</span>
                {"\n"}
                <span className={styles.codeKey}>kind:</span>{" "}
                <span className={styles.codeValue}>Agent</span>
                {"\n"}
                <span className={styles.codeKey}>metadata:</span>
                {"\n  "}
                <span className={styles.codeKey}>name:</span>{" "}
                <span className={styles.codeValue}>my-agent</span>
                {"\n  "}
                <span className={styles.codeKey}>version:</span>{" "}
                <span className={styles.codeValue}>1.0.0</span>
                {"\n"}
                {"\n"}
                <span className={styles.codeKey}>spec:</span>
                {"\n  "}
                <span className={styles.codeKey}>runtime:</span>
                {"\n    "}
                <span className={styles.codeKey}>framework:</span>{" "}
                <span className={styles.codeValue}>adk</span>
                {"\n    "}
                <span className={styles.codeKey}>language:</span>{" "}
                <span className={styles.codeValue}>python</span>
                {"\n    "}
                <span className={styles.codeKey}>llm:</span>
                {"\n      "}
                <span className={styles.codeKey}>adapter:</span>{" "}
                <span className={styles.codeRef}>./adapters/llm.yaml</span>
                {"\n  "}
                <span className={styles.codeKey}>identity:</span>{" "}
                <span className={styles.codeRef}>./identity</span>
                {"\n  "}
                <span className={styles.codeKey}>evals:</span>{" "}
                <span className={styles.codeRef}>./evals</span>
                {"\n  "}
                <span className={styles.codeKey}>tools:</span>{" "}
                <span className={styles.codeRef}>./tools</span>
                {"\n  "}
                <span className={styles.codeKey}>observability:</span>{" "}
                <span className={styles.codeRef}>./observability</span>
                {"\n  "}
                <span className={styles.codeKey}>env:</span>
                {"\n    "}
                <span className={styles.codeComment}>
                  # declared, validated, injected at deploy
                </span>
                {"\n"}
                {"\n"}
                <span className={styles.codeComment}>
                  # bundled attestations
                </span>
                {"\n"}
                <span className={styles.codeAccent}>SBOM.cyclonedx.json</span>
                {"\n"}
                <span className={styles.codeAccent}>EVAL_RESULTS.json</span>
                {"\n"}
                <span className={styles.codeAccent}>BUILD_META.json</span>
              </code>
            </pre>
          </div>
        </div>
      </section>

      <div className="divider" />

      {/* ============ FROM FLUENTDATA ============ */}
      <section className={styles.aboutSection}>
        <div className="container-narrow">
          <span className="eyebrow">04 — Provenance</span>
          <h2 className={styles.sectionTitle}>
            Built by <em className="italic-display">FluentData</em>.
          </h2>
          <p className="lead">
            Zil is built and maintained by FluentData. Born from real
            production agent work, open-sourced under Apache 2.0. We build
            production AI agents for clients — Zil is the toolchain we use.
          </p>

          <div className={styles.aboutCtas}>
            <a
              href="https://fluentdata.ai"
              target="_blank"
              rel="noopener noreferrer"
              className="btn"
            >
              About FluentData <span className="btn-arrow">↗</span>
            </a>
            <a
              href="mailto:hello@fluentdata.ai?subject=Zil%20-%20interested"
              className="btn"
            >
              Get in touch <span className="btn-arrow">→</span>
            </a>
          </div>
        </div>
      </section>

      <div className="divider" />

      {/* ============ FOOTER ============ */}
      <footer className={styles.footer}>
        <div className="container">
          <div className={styles.footerGrid}>
            <div className={styles.footerBrand}>
              <span className={styles.footerWordmark}>Zil</span>
              <p className={styles.footerTagline}>
                A framework for production AI agents.
              </p>
              <p className={styles.footerCredit}>
                Maintained by FluentData. Licensed openly.
              </p>
              <div className={styles.footerLogo}>
                <Image
                  src="/fluentdata-logo/MasterLogo_Mono_Positive.png"
                  alt="FluentData"
                  width={140}
                  height={47}
                  style={{ objectFit: 'contain' }}
                />
              </div>
            </div>

            <div className={styles.footerCol}>
              <span className="eyebrow-muted">Product</span>
              <ul className={styles.footerList}>
                <li>
                  <Link href="/docs">Documentation</Link>
                </li>
                <li>
                  <Link href="/docs/cli">CLI Reference</Link>
                </li>
                <li>
                  <Link href="/docs/getting-started">Get Started</Link>
                </li>
                <li>
                  <Link href="/agent.txt">agent.txt</Link>
                </li>
              </ul>
            </div>

            <div className={styles.footerCol}>
              <span className="eyebrow-muted">Composes with</span>
              <ul className={styles.footerList}>
                <li>
                  <a
                    href="https://google.github.io/adk-docs/"
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    Google ADK ↗
                  </a>
                </li>
                <li>
                  <a
                    href="https://modelcontextprotocol.io"
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    Model Context Protocol ↗
                  </a>
                </li>
                <li>
                  <a
                    href="https://opentelemetry.io"
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    OpenTelemetry ↗
                  </a>
                </li>
                <li>
                  <a
                    href="https://github.com/confident-ai/deepeval"
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    DeepEval ↗
                  </a>
                </li>
              </ul>
            </div>

            <div className={styles.footerCol}>
              <span className="eyebrow-muted">Community</span>
              <ul className={styles.footerList}>
                <li>
                  <a
                    href="https://join.slack.com/t/zilorg/shared_invite/zt-3xye83sw1-cU3H1Hb_yFbmyBBgbt5VGQ"
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    Slack ↗
                  </a>
                </li>
                <li>
                  <a
                    href="https://github.com/fluentdata-co/zil"
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    GitHub ↗
                  </a>
                </li>
                <li>
                  <a
                    href="https://github.com/fluentdata-co/zil/discussions"
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    Discussions ↗
                  </a>
                </li>
              </ul>
            </div>

            <div className={styles.footerCol}>
              <span className="eyebrow-muted">Contact</span>
              <ul className={styles.footerList}>
                <li>
                  <a href="mailto:hello@fluentdata.ai">hello@fluentdata.ai</a>
                </li>
                <li>
                  <a
                    href="https://fluentdata.ai"
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    fluentdata.ai ↗
                  </a>
                </li>
              </ul>
            </div>
          </div>

          <div className={styles.footerBottom}>
            <span className={styles.footerCopy}>
              © 2026 FluentData. Open source, Apache 2.0.
            </span>
            <span className={styles.footerVersion}>
              <span className="mark">getzil.dev</span> · v0.1
            </span>
          </div>
        </div>
      </footer>
    </main>
  );
}
