import Link from "next/link";
import Image from "next/image";
import styles from "./page.module.css";
import NotifyDialog from "./components/NotifyDialog";

const pillars = [
  {
    num: "01",
    name: "Governance & Lifecycle",
    body: "Who owns each agent, how it changes, when it retires, and how humans stay in the loop. Every agent has a registry entry, a named owner, an approval workflow, and a defined oversight UX.",
  },
  {
    num: "02",
    name: "Security & Adversarial Hardness",
    body: "Prompt injection, tool-use abuse, memory poisoning, A2A spoofing, and supply chain risk. A repeatable threat model and red-team playbook for the agent attack surface.",
  },
  {
    num: "03",
    name: "Data & Memory Protection",
    body: "Memory is data. Data has laws. Right-to-forget cascades, residency mapping, semantic context as systems of action — the agent-scale data layer treated as infrastructure, not afterthought.",
  },
  {
    num: "04",
    name: "Observability & Reliability",
    body: "OpenTelemetry agent spans, reasoning traces, drift detection, crash recovery, idempotency. Long-running agents treated as a distinct architectural pattern with its own engineering practices.",
  },
  {
    num: "05",
    name: "Evaluation & Quality",
    body: "Pre-deployment suites, multi-turn evaluation, tool-use correctness, planning quality, eval-in-production. Every promotion gated. Every production signal becomes a future test case.",
  },
  {
    num: "06",
    name: "Cost & Resource Governance",
    body: "Token budgets at multiple granularities, model routing by task complexity, multi-provider fallback. The unit economics that determine whether agent programs survive scale.",
  },
  {
    num: "07",
    name: "Architecture & Packaging",
    body: "Agents as portable, signed, versioned artifacts. Multi-agent orchestration as a first-class concern. The .zil package format separates what ships from how it runs.",
  },
];

const principles = [
  {
    word: "Open",
    body: "Composes with MCP, A2A, and emerging open standards from the Linux Foundation Agentic AI Foundation. Zil is the layer above — packaging, runtime, lifecycle.",
  },
  {
    word: "Portable",
    body: "Adapter pattern for every external dependency. Switch LLM providers, vector backends, or vendors with a configuration change. No code rewrite.",
  },
  {
    word: "Compliance-grade",
    body: "Designed for regulated industries from day one. Audit trails, data residency, right-to-forget cascades, signed artifacts, SLSA provenance — the discipline regulators expect.",
  },
  {
    word: "Practitioner-led",
    body: "Refined through real engagements. Every primitive in the framework solves a specific failure mode that practitioners have actually hit in production.",
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
            BY FLUENTDATA · v0.1
          </span>

          <h1 className={`rise rise-delay-2 ${styles.heroTitle}`}>
            <span className={styles.heroLine}>A framework for</span>
            <span className={styles.heroLine}>
              <em className="italic-display">production</em>
            </span>
            <span className={styles.heroLine}>AI agents.</span>
          </h1>

          <p className={`lead rise rise-delay-3 ${styles.heroLead}`}>
            <span className={styles.zilWord}>Zil</span> is an open methodology for
            building, packaging, and operating AI agents at enterprise scale.
            Seven pillars, one signed artifact, deployable anywhere.
          </p>

          <div className={`rise rise-delay-4 ${styles.heroCtas}`}>
            <Link href="/docs" className="btn btn-primary">
              Documentation <span className="btn-arrow">→</span>
            </Link>
            <Link href="#read" className="btn">
              Read the framework
            </Link>
            <a
              href="https://join.slack.com/t/zilorg/shared_invite/zt-3xye83sw1-cU3H1Hb_yFbmyBBgbt5VGQ"
              target="_blank"
              rel="noopener noreferrer"
              className="btn"
            >
              Join Slack <span className="btn-arrow">→</span>
            </a>
            <NotifyDialog />
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
              <span className={styles.metaValue}>MCP · A2A · DeepEval · OpenTelemetry</span>
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

      {/* ============ THE PROBLEM ============ */}
      <section id="approach">
        <div className="container">
          <div className={styles.twoCol}>
            <div className={styles.colLeft}>
              <span className="eyebrow">01 — The problem</span>
              <h2 className={styles.sectionTitle}>
                Production AI agents have <em className="italic-display">outgrown</em> the practices we use to ship them.
              </h2>
            </div>
            <div className={styles.colRight}>
              <p className="lead">
                A short-turn chatbot fails in predictable ways. A multi-step
                agent that reasons, uses tools, maintains memory, and hands off
                to other agents fails in ways that compound — a bad reasoning
                step leads to a wrong tool call, which writes incorrect data,
                which poisons the agent's memory for the next session.
              </p>
              <p>
                Traditional production-readiness checklists were built for the
                first generation of AI features. They do not cover what
                production agents actually need: lifecycle governance, agent-specific
                security, memory as a system of action, long-running execution,
                multi-agent coordination, and packaging that survives the next
                vendor migration.
              </p>
              <p>
                <span className={styles.statLine}>
                  <strong className={styles.stat}>46%</strong> of organizations cite integration with existing systems as their primary deployment challenge.
                </span>
                <span className={styles.statLine}>
                  <strong className={styles.stat}>67%</strong> aim to avoid high dependency on a single AI provider.
                </span>
                <span className={styles.statLine}>
                  <strong className={styles.stat}>35%</strong> admit they could not immediately disable a rogue AI agent.
                </span>
              </p>
            </div>
          </div>
        </div>
      </section>

      <div className="divider" />

      {/* ============ SEVEN PILLARS ============ */}
      <section className={styles.pillars}>
        <div className="container">
          <div className={styles.pillarsHeader}>
            <span className="eyebrow">02 — The framework</span>
            <h2 className={styles.sectionTitle}>
              Seven pillars. <em className="italic-display">One discipline.</em>
            </h2>
            <p className="lead">
              Each pillar is independently assessable, independently actionable,
              and designed to integrate with existing security, governance, and
              engineering practices. Together they describe what a mature agent
              operation looks like and how to get there.
            </p>
          </div>

          <ol className={styles.pillarList}>
            {pillars.map((p) => (
              <li key={p.num} className={styles.pillarItem}>
                <div className={styles.pillarNum}>{p.num}</div>
                <div className={styles.pillarBody}>
                  <h3 className={styles.pillarName}>{p.name}</h3>
                  <p className={styles.pillarText}>{p.body}</p>
                </div>
              </li>
            ))}
          </ol>
        </div>
      </section>

      <div className="divider" />

      {/* ============ PRINCIPLES ============ */}
      <section id="read">
        <div className="container">
          <div className={styles.principlesHeader}>
            <span className="eyebrow">03 — Principles</span>
            <h2 className={styles.sectionTitle}>
              What makes <span className="mark">.zil</span>{" "}
              <em className="italic-display">different.</em>
            </h2>
          </div>

          <div className={styles.principleGrid}>
            {principles.map((p) => (
              <div key={p.word} className={styles.principle}>
                <h3 className={styles.principleWord}>
                  <em className="italic-display">{p.word}</em>
                </h3>
                <p>{p.body}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      <div className="divider" />

      {/* ============ PACKAGE FORMAT ============ */}
      <section className={styles.codeSection}>
        <div className="container">
          <div className={styles.codeWrapper}>
            <div className={styles.codeIntro}>
              <span className="eyebrow">04 — The artifact</span>
              <h2 className={styles.sectionTitle}>
                <span className="mark">.zil</span> — a signed, portable agent bundle.
              </h2>
              <p className="lead">
                Every Zil-conformant agent ships as a single signed archive
                containing its full declarative specification. Manifest,
                identity, skills, memory configuration, RAG snapshots, and
                evaluation suite — packaged together, versioned together,
                deployed anywhere.
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
                  <span className={styles.codeStatValue}>Any conformant runtime</span>
                </div>
              </div>
            </div>

            <pre className={styles.code}>
              <code>
                <span className={styles.codeComment}>
                  # customer-support-agent-2.1.4.zil
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
                <span className={styles.codeValue}>customer-support-agent</span>
                {"\n  "}
                <span className={styles.codeKey}>version:</span>{" "}
                <span className={styles.codeValue}>2.1.4</span>
                {"\n"}
                {"\n"}
                <span className={styles.codeKey}>spec:</span>
                {"\n  "}
                <span className={styles.codeKey}>identity:</span>{" "}
                <span className={styles.codeRef}>./identity/persona.md</span>
                {"\n  "}
                <span className={styles.codeKey}>adapters:</span>{" "}
                <span className={styles.codeRef}>./adapters/</span>
                {"\n  "}
                <span className={styles.codeKey}>skills:</span>{" "}
                <span className={styles.codeRef}>./skills/</span>
                {"\n  "}
                <span className={styles.codeKey}>memory:</span>{" "}
                <span className={styles.codeRef}>./memory/backend.yaml</span>
                {"\n  "}
                <span className={styles.codeKey}>mcp_servers:</span>{" "}
                <span className={styles.codeRef}>./mcp/</span>
                {"\n  "}
                <span className={styles.codeKey}>data:</span>{" "}
                <span className={styles.codeRef}>./data/kb_snapshot.tar.gz</span>
                {"\n  "}
                <span className={styles.codeKey}>evals:</span>{" "}
                <span className={styles.codeRef}>./evals/baseline.yaml</span>
                {"\n"}
                {"\n"}
                <span className={styles.codeComment}># attestations</span>
                {"\n"}
                <span className={styles.codeKey}>signature:</span>{" "}
                <span className={styles.codeAccent}>cosign</span>
                {"\n"}
                <span className={styles.codeKey}>provenance:</span>{" "}
                <span className={styles.codeAccent}>slsa-v1</span>
                {"\n"}
                <span className={styles.codeKey}>sbom:</span>{" "}
                <span className={styles.codeAccent}>cyclonedx-1.5</span>
              </code>
            </pre>
          </div>
        </div>
      </section>

      <div className="divider" />

      {/* ============ FROM FLUENTDATA ============ */}
      <section className={styles.aboutSection}>
        <div className="container-narrow">
          <span className="eyebrow">05 — Provenance</span>
          <h2 className={styles.sectionTitle}>
            From the team at <em className="italic-display">FluentData</em>.
          </h2>
          <p className="lead">
            Zil is the methodology FluentData uses to deploy production AI
            agents for our clients. We are publishing it openly because we
            believe production agent operations need a shared vocabulary, and
            because no single vendor's platform should be the default answer
            for an industry-wide question.
          </p>
          <p>
            FluentData is a forward-deployed engineering firm working with
            channel partners and direct clients on agentic AI delivery. Zil is
            the connective tissue across our engagements — refined through real
            production work, published as a signal of how we think about the
            problem.
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
            <NotifyDialog />
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
              <span className="eyebrow-muted">Framework</span>
              <ul className={styles.footerList}>
                <li>
                  <Link href="/docs">Documentation</Link>
                </li>
                <li>
                  <Link href="#approach">The problem</Link>
                </li>
                <li>
                  <Link href="#approach">Seven pillars</Link>
                </li>
                <li>
                  <Link href="#read">Principles</Link>
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
                    href="https://modelcontextprotocol.io"
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    Model Context Protocol ↗
                  </a>
                </li>
                <li>
                  <a
                    href="https://a2aproject.org"
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    Agent2Agent Protocol ↗
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
              © 2026 FluentData. Zil is a draft methodology in active development.
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
