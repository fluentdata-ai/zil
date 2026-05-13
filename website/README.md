# getzil.dev

The public-facing website for **Zil** — FluentData's framework for production AI agents.

## Stack

- **Next.js 15** (App Router)
- **React 19**
- **TypeScript**
- Plain CSS modules (no Tailwind, no UI library — every styling decision is intentional)
- Self-hosted Google Fonts (Fraunces serif display, Inter body, JetBrains Mono technical)
- Zero external runtime dependencies

## Local development

```bash
npm install
npm run dev
```

Site runs at `http://localhost:3000`.

## Deploy to Vercel

### Option 1 — via Vercel CLI

```bash
npm i -g vercel
vercel
```

Follow the prompts. On first deploy, Vercel will detect Next.js automatically.

### Option 2 — via Git integration

1. Push this repo to GitHub
2. Go to [vercel.com/new](https://vercel.com/new)
3. Import the repo
4. Vercel auto-detects Next.js — accept defaults
5. Click **Deploy**

### Custom domain

After first deploy:

1. Vercel project → **Settings** → **Domains**
2. Add `getzil.dev`
3. Vercel will display the DNS records to configure at your registrar
4. SSL provisions automatically once DNS resolves

## File structure

```
getzil-site/
├── app/
│   ├── layout.tsx        # Root layout, metadata, font loading
│   ├── page.tsx          # The single-page site (all sections)
│   ├── page.module.css   # Section-specific styles
│   └── globals.css       # Design system, typography, base
├── public/               # Static assets (add favicon here)
├── package.json
├── next.config.js
└── tsconfig.json
```

## Editing content

All copy lives in `app/page.tsx` as React JSX. The seven pillars and four
principles are defined as data arrays at the top of the file — easiest place
to update copy without touching layout.

## Design notes

The aesthetic is deliberately **instrument-grade editorial** — silver-and-warm-accent
palette, Fraunces italic display type for the Zil wordmark, restrained
typographic hierarchy. The intent is to read as a serious technical publication
rather than a generic AI startup landing page.

Color tokens (in `globals.css`):
- `--bg: #0a0a0c` — near-black, slightly cool
- `--silver-100..700` — the metallic grayscale
- `--accent: #e8c87a` — the warm metallic accent ("argentum struck against flame")

Typography:
- **Display**: Fraunces (a parametric serif, slight optical-size adjustments)
- **Body**: Inter (with stylistic alternates enabled)
- **Mono**: JetBrains Mono (for code and technical labels)

## License

Site code: MIT.
Zil framework methodology: open, under active development by FluentData.
