# lilygaripovarealestate-brain — Design Spec

**Date:** 2026-04-25 (revised 2026-04-26 — added social ingestion)
**Status:** Design approved; awaiting implementation plan
**Owner:** Radif (curator), Lily (subject)
**Forks from:** [`radif/obsidian-brain`](https://github.com/radif/obsidian-brain)

## Goal

Build a self-compiling knowledge base for Lily's 9-year real-estate practice. Four user-facing outcomes, in priority order:

1. **Sales conversion** — better scripts, FAQs, objection handling, follow-up.
2. **Ad triggering** — copy and hooks that get the right prospects to call.
3. **AEO website source** — public site optimized for LLM citation (ChatGPT, Perplexity, Claude) when prospects ask "best agent in X area".
4. **CRM-lite** — lightweight tracking of clients, transactions, and the events around them (birthdays, anniversaries, reviews, gifts).

Success criterion for v1: Lily can dump arbitrary content into a small number of folders, the compile pipeline produces a queryable `knowledge/` graph, and the `raw/website/` subset is publish-ready when the site-build job runs.

## Architectural decisions

### A1. Separate repo pair (not a sub-bucket of obsidian-brain)

lilygaripovarealestate-brain is its own structural + content repo pair, forked from obsidian-brain. Rationale:

- Disjoint audiences (technical research vs real-estate practice).
- Independent publish pipeline (her AEO site is hers, not yours).
- The structural-vs-content split that obsidian-brain already polished is *designed* to be forked per knowledge domain.

### A2. Hybrid compile (knowledge sections only)

`compile.py` runs per-file on **knowledge sections** (`brand/`, `communications/`, `marketing/`, `webinars/`, `competitors/`, `strategy/`, `research/`, `website/`). It is **skipped** for `operations/` and `social/`.

Rationale:

- Per-record LLM compilation of operational facts ("Jane bought 123 Oak St in 2019") produces low-signal output. The current compile prompt expects synthesis-worthy concepts; for facts, it inflates 30 words into 400-word stub articles or invents generalizations from a single data point.
- Same logic applies to social posts: a 100-word LinkedIn post doesn't extract into 4 concept articles meaningfully, and at her volume (potentially 10K+ posts across 6 surfaces × 9 years), per-file compile would be both expensive and noisy.
- The genuine LLM value over operational records and social posts is **across-record pattern mining** (e.g., *"clients who got handwritten anniversary cards refer 3× more"*, *"top-10 LinkedIn posts by engagement all open with a question"*). That is a different operation — bulk synthesis, not per-file extraction — and is handled by separate scripts (A3, A7).

Implementation: `scripts/utils.py:list_raw_files()` adds `operations` *and* `social` to its skip-list, alongside the existing `assets` entry.

### A3. Operational synthesis as a separate, deliberate pass

A new script `scripts/synthesize-operations.py` reads everything under `raw/operations/` in bulk, prompts the LLM to find cross-record patterns (referral correlation, segment overlap, gift-to-retention links), and writes results to `knowledge/connections/`. Same SDK call shape as `lint.py:check_contradictions`.

Triggering: manual via `just synthesize`. Not automatic on every compile, not on every commit. Run when the user has a question that demands cross-record reasoning.

This script can be deferred to v2 without blocking v1 — `operations/` is independently useful via Obsidian search + wikilinks + `just ask`.

### A4. Folder-based publishable subset (not frontmatter flag)

`raw/website/` is *literally* the public site source. The publish step is a folder copy + Markdown→HTML render with schema.org metadata injection from `raw/website/meta/`.

Rejected alternative: a `public: true` frontmatter flag on knowledge articles, with a publish script that filters and renders. Reason for rejection: location is more legible than tags. "Which articles to write next for AEO" becomes "look at the empty slots in `raw/website/articles/`" — a concrete answer.

### A5. Aggressive flatness in raw/

Most `raw/` buckets are flat — one folder, descriptive filenames, no sub-folders. The compile pipeline does sub-categorization in `knowledge/`. Three exceptions to flatness:

- `raw/website/` — sub-folders map directly to URL paths.
- `raw/operations/` — the schema (one file per client, one file per transaction) is the retrieval value.
- `raw/social/` — sub-folders map to platform-account surfaces; at 10K+ posts, the platform is part of the retrieval schema.

Rationale: `raw/` is *input shape*, optimized for friction-free dumping. `knowledge/` is *output shape*, optimized for retrieval and synthesis. Compile is the translator.

### A6. Visibility-tagged content for safe public/private separation

Every raw file carries a `visibility:` frontmatter field with one of three values:

- **`public`** — safe to quote *verbatim* in AI-drafted public-facing content (website articles, ads, social posts, LinkedIn long-form). Default for everything in `raw/website/`. Default for posts under `raw/social/` (since the post itself was public when published).
- **`internal`** — must never appear verbatim in public output. Default for `raw/operations/`, `raw/strategy/{pricing,decisions}/`, `raw/competitors/`, internal scripts in `raw/communications/scripts/`. The LLM may *reason about* these but must not quote.
- **`safe-context`** — LLM may reason from *and* paraphrase, but should not quote verbatim. The default for everything else (`raw/brand/`, `raw/communications/playbooks/`, `raw/research/`, etc.) — most knowledge falls here.

When `visibility` is missing, the compile pipeline treats the file as `safe-context`. Any `just ask` flow that drafts public content (ad copy, website article, social post) filters out `internal` files at retrieval time.

For social posts specifically: the post body is `public` (it was published), but the `engagement` metrics + extracted comments are filtered like `internal` data at retrieval — they're useful *context* for pattern analysis but shouldn't be quoted in drafts ("47 likes" doesn't belong in a new post).

This is an explicit application of P4 ("strictly separate internal vs publicly-shareable docs") from `raw/research/business/AI in business.md`.

### A7. Two-track social ingestion (deep content compiles, shallow content bulk-synthesizes)

Lily has 7 social surfaces (FB Business Page, FB Personal, IG-EN, IG-RU, LinkedIn, YouTube, X), bilingual across most. The right ingestion model differs by content depth:

- **Track 1 — YouTube → `raw/transcripts/` (per-file compile).** A 30-min video transcript is ~5K words of searchable substance. YouTube content rides the existing transcript pipeline: `scripts/fetch-youtube-channel.py` lists her channel's videos via YouTube Data API v3, runs each through the existing `transcript.py`, drops files in `raw/transcripts/`. Compile picks them up like any other transcript. Longitudinal queries (the COVID/WFH example) work cleanly.
- **Track 2 — FB / IG / LinkedIn / X → `raw/social/` (skip-listed, bulk synthesis).** Posts are shallow (50–500 words typical), and per-file compile against 10K+ items would burn cost and produce noise. `raw/social/` joins the compile skip-list. Pattern mining happens via a deferred `scripts/synthesize-social.py` analogous to `synthesize-operations.py`.

Both tracks share the same access reality:

| Surface | Tier A (data export) | Tier B (API) | Track |
|---|---|---|---|
| FB Page (Lily Garipova Real Estate) | ✅ | ✅ Graph API + Page Access Token | Track 2 |
| FB Personal | ✅ | ❌ | Track 2 |
| IG-EN, IG-RU | ✅ | Conditional — only if Business/Creator + linked to a FB Page | Track 2 |
| LinkedIn (personal) | ✅ | ❌ | Track 2 |
| YouTube | ✅ | ✅ YouTube Data API v3 (free quota) | **Track 1** |
| X.com | ✅ | ❌ (or paid Basic+ tier) | Track 2 |

## Mandatory documents (per AI search principles)

The principles in `raw/research/business/` call for specific named artifacts that the AI relies on. The spec mandates these exist as named slots — they are not optional. Empty stubs at v1 are acceptable; missing slots are not.

| Doc | Path | Purpose | Maps to principle |
|---|---|---|---|
| **Company overview** | `raw/brand/company-overview.md` | Single-paragraph "who Lily is, who she serves, how she's different." Read first by any AI agent introduced to the brand. | P5 (AI in business) |
| **Brand voice & style guide** | `raw/brand/voice-and-style.md` | Tone, signature phrases, sentence-length norms, words to use/avoid. | P5 |
| **Content guidelines (the big one)** | `raw/website/meta/content-guidelines.md` | **All P11–P17, P20, P21, P23, P24 in one place.** Title-includes-search-term, fact density rule, brand-by-name discipline, brand-mention pattern, awards-with-numbers rule, niche-specific award page titles, bullets/tables/long-form structure. Required reading for any compile or `just ask` flow that drafts `raw/website/articles/*` or other public content. | P11–P17, P20–P24 |
| **Important pages list** | `raw/website/meta/important-pages.md` | Sitemap-style listing of every page that matters, with a one-line description each. Lets the AI know which pages exist when asked to update or cross-link. | P5 |
| **Brand mentions log** | `raw/research/brand-mentions.md` | Append-only register of external coverage (podcast guest spots, listicle inclusions, press hits, third-party reviews). The closest controllable proxy for primary bias (P10). | P10 |
| **Directory tracking** | `raw/research/aeo/directory-tracking.md` | Which directories AI cites for *real-estate-in-Lily's-market* — running list, updated periodically by checking Google AI mode for relevant prospect-style queries. Of the ~12 directories that matter per industry, identify the 1-3 that dominate citations. | P25–P27 |
| **Keyword research** | `raw/research/aeo/keyword-research.md` | What prospects actually search for — Reddit topic discovery output (P28), with similar-topic variants kept distinct (P29). Drives which articles get written next under `raw/website/articles/`. | P22, P28, P29 |
| **Account inventory** | `raw/social/account-inventory.md` | Single source of truth for every social surface — URL, language, account type (personal / business / creator), API access tier, last-export date. Used by ingestion scripts and by the compile pipeline when it needs to attribute a post to its origin surface. | P1 (comprehensive KB) |

The competitor profiles (`raw/competitors/<slug>.md`) and FAQs (in `raw/communications/`) are also P5 standard documents but they're already covered in the schemas section below — they grow organically rather than being one mandated file each.

## Directory tree

### Structural repo: `lilygaripovarealestate-brain/`

Forked from obsidian-brain. Same shape:

```
lilygaripovarealestate-brain/
├── scripts/                        # compile, query, lint, transcript, synthesize-{operations,social},
│                                   # fetch-{meta-social,youtube-channel}, import-social-export,
│                                   # link-content, etc.
├── hooks/                          # session-start, session-end, pre-compact (CLAUDE_INVOKED_BY-guarded)
├── .claude/
│   ├── settings.json               # hook config
│   ├── commands/                   # slash commands forked + scoped to real-estate domain
│   └── skills/                     # agent skills forked + scoped
├── AGENTS.md                       # adapted: real-estate KB schema (article formats, frontmatter)
├── CLAUDE.md                       # adapted: project rules (incl. visibility flag enforcement)
├── README.md                       # adapted: setup walkthrough
├── justfile                        # same recipes plus `synthesize`, `synthesize-social`,
│                                   # `fetch-meta`, `fetch-youtube`, `import-social`, `publish`
├── pyproject.toml                  # same deps + youtube-transcript-api (already there) + 
│                                   # platform SDKs added as needed (facebook-sdk, etc.)
└── raw/  knowledge/  notes/        # symlinks → lilygaripovarealestate-brain-content/
```

### Content repo: `lilygaripovarealestate-brain-content/`

Private. Symlinked into the structural repo via the existing `link-content.py` machinery (linked mode, relative symlinks).

```
lilygaripovarealestate-brain-content/
├── raw/
│   ├── daily/                      # auto — Claude Code session flushes
│   ├── clippings/                  # auto — Web Clipper output
│   ├── transcripts/                # auto — transcript.py output (YouTube channel ingestion lands here too)
│   │
│   ├── brand/                      # logos, voice, visual style, positioning — flat
│   │   ├── company-overview.md     # MANDATORY (P5)
│   │   └── voice-and-style.md      # MANDATORY (P5)
│   ├── communications/             # email templates, scripts, playbooks, FAQs — flat
│   ├── marketing/                  # ads, social, hooks, campaigns, calendar logic — flat
│   ├── webinars/                   # one .md per webinar (notes + analysis + transcript wikilink) — flat
│   ├── competitors/                # one .md per competitor + cross-analysis files — flat
│   ├── strategy/                   # annual plans, marketing strategy, decisions, pricing — flat
│   ├── research/                   # market, AEO, SEO, personas, industry, LinkedIn — flat
│   │   ├── brand-mentions.md       # MANDATORY (P10)
│   │   └── aeo/
│   │       ├── directory-tracking.md  # MANDATORY (P25–P27)
│   │       └── keyword-research.md    # MANDATORY (P22, P28, P29)
│   │
│   ├── website/                    # IS the published artifact — keeps structure
│   │   ├── pages/                  # /about, /services, /neighborhoods/*
│   │   ├── articles/
│   │   │   ├── neighborhood-guides/
│   │   │   ├── buyer-guides/
│   │   │   ├── seller-guides/
│   │   │   └── market-reports/
│   │   ├── awards/                 # award badges + citation pages (per ai-search-award-signal)
│   │   └── meta/
│   │       ├── content-guidelines.md   # MANDATORY (P11–P17, P20, P21, P23, P24)
│   │       ├── important-pages.md      # MANDATORY (P5)
│   │       ├── schema.md               # schema.org JSON-LD definitions
│   │       └── robots-and-sitemap.md   # crawler rules
│   │
│   ├── social/                     # NOT compiled — bulk-synthesized via synthesize-social.py
│   │   ├── account-inventory.md    # MANDATORY — every surface with URL + access tier
│   │   ├── facebook-page/          # Lily Garipova Real Estate Page (RU+EN content)
│   │   ├── facebook-personal/      # personal profile (RU+EN content)
│   │   ├── instagram-en/
│   │   ├── instagram-ru/
│   │   ├── linkedin/               # personal, EN
│   │   └── x/                      # EN
│   │   # YouTube intentionally absent — it goes to raw/transcripts/ (Track 1, see A7)
│   │
│   └── operations/                 # NOT compiled — plain Markdown, navigated via Obsidian + wikilinks
│       ├── clients/                # one .md per client (profile + family + reviews + notes)
│       │   └── <client-slug>.md
│       ├── transactions/           # one .md per deal Lily worked
│       │   └── <address-slug>.md   # if same address transacts twice, prefix year or use sections
│       ├── presents-log.md         # append-only, dated headings — gifts given
│       ├── emails-log.md           # append-only, dated headings — marketing emails sent
│       └── timeline.md             # client birthdays, anniversaries, family events
│
├── knowledge/                      # LLM-compiled output (excludes operations/ and social/)
│   ├── concepts/  connections/  qa/
│   ├── index.md  log.md
│   └── brand-ambassador.md         # synthesized master doc (see §Compile pipeline mechanics)
└── notes/                          # freeform scratch
```

### Thirteen top-level `raw/` buckets

| Bucket | Authored by | Compiled? | Notes |
|---|---|---|---|
| `daily/` | hook | ✓ | Session-flush output |
| `clippings/` | Web Clipper | ✓ | Competitor sites, articles, listings |
| `transcripts/` | `transcript.py` + `fetch-youtube-channel.py` | ✓ | YouTube + webinar recordings (Track 1) |
| `brand/` | Lily/Radif | ✓ | Identity, voice, visual style; includes mandatory `company-overview.md` + `voice-and-style.md` |
| `communications/` | Lily/Radif | ✓ | Templates, scripts, playbooks, FAQs |
| `marketing/` | Lily/Radif | ✓ | Ads, social, hooks, campaigns, calendar logic |
| `webinars/` | Lily/Radif | ✓ | One .md per webinar; wikilinks to transcript |
| `competitors/` | Lily/Radif | ✓ | One .md per competitor; structured frontmatter (see below) |
| `strategy/` | Lily/Radif | ✓ | Annual plans, marketing strategy, decisions, pricing |
| `research/` | Lily/Radif | ✓ | Market, AEO, SEO, personas, industry, LinkedIn; includes mandatory `brand-mentions.md` + `aeo/{directory-tracking,keyword-research}.md` |
| `website/` | Lily/Radif | ✓ | Sub-folders map to URLs; the publish artifact source; includes mandatory `meta/content-guidelines.md` + `meta/important-pages.md` |
| `social/` | Lily (originally) + import scripts (ingestion) | ✗ | One sub-folder per platform-account surface (Track 2); skip-listed; bulk synthesis via `synthesize-social.py` |
| `operations/` | Lily/Radif | ✗ | Records, not concepts |

Lily's mental model when *manually* dumping content: *"is this about brand / communications / marketing / webinars / competitors / strategy / research / website / operations?"* — nine choices. The four auto-filled buckets (`daily/`, `clippings/`, `transcripts/`, `social/`) aren't decisions she has to make.

## Cross-linking pattern

The reason `operations/` is its own bucket is so a client record can sit at the center of an Obsidian wikilink hub:

```
operations/clients/jane-smith.md
   ├─ [[operations/transactions/123-oak-st]]                ← her purchase
   ├─ [[operations/presents-log#2020-09-22-jane-smith]]     ← anniversary card entry
   ├─ [[operations/emails-log#2024-05-14-jane-smith-bday]]  ← birthday email entry
   ├─ [[operations/timeline#jane-smith]]                    ← May 14 + family events
   │
   └─ [[brand/positioning/luxury-condo-buyer]]              ← into the knowledge graph
   └─ [[communications/email-templates/birthday-greeting]]  ← template the email used
```

The two upward links bridge `operations/` (facts) into the compiled `knowledge/` graph (concepts). When asked *"how should I write a birthday email for Jane?"*, `just ask` reads the index, follows wikilinks from `jane-smith.md` into the brand and communications knowledge, and synthesizes a personalized draft.

## Schemas

### Visibility (every raw file)

All raw files carry a `visibility:` frontmatter field. Per A6:

```yaml
---
visibility: public | internal | safe-context
---
```

Defaults if absent: `safe-context`. Hard rules:

- `raw/website/**` → `public` by default (override per file if some content is internal).
- `raw/social/**` → `public` (post body) by default; engagement metrics treated as internal at retrieval.
- `raw/operations/**` → `internal`.
- `raw/strategy/{pricing,decisions}/**` → `internal`.
- `raw/competitors/**` → `internal` (competitive intelligence).
- `raw/communications/scripts/**` → `internal` (sales scripts shouldn't be in public-facing content).
- Everything else → `safe-context` unless explicitly tagged.

### Competitor frontmatter (in `raw/competitors/<slug>.md`)

```yaml
---
title: "Coldwell Banker (Local Branch)"
type: competitor-profile
visibility: internal
positioning: "luxury, transactional, brand-name security"
target_segments: [empty-nesters, relocations, $1M+]
negotiation_style: "aggressive listing-side, quick to discount commission"
channels: [Zillow boost, Google Ads, brand referrals]
strengths: [brand recognition, training pipeline, listing volume]
weaknesses: [generic communication, slow follow-up, low local roots]
last_updated: 2026-04-25
sources:
  - "raw/clippings/coldwell-website-snapshot-2026-04.md"
  - "raw/clippings/coldwell-zillow-listings-q1-2026.md"
---
```

The schema is a contract enforced by review, not by code. Compile picks up the structured fields and threads them into the knowledge graph; comparative analysis can ask *"who serves the same segment Lily does, and how do they negotiate differently?"*

### Webinar frontmatter (in `raw/webinars/<date>-<slug>.md`)

```yaml
---
title: "Working from Home: The Future of Work"
visibility: safe-context
date: 2020-10-15
audience: "Local prospective sellers, ~120 attendees"
recording_url: "https://www.youtube.com/watch?v=..."
transcript: "[[transcripts/2020-10-15-wfh-future]]"
themes: [remote-work, suburban-migration, home-office-trends]
predictions:
  - claim: "Demand for home offices will outlast the pandemic"
    aged_well: true
  - claim: "Urban condos will permanently lose value"
    aged_well: false
---
```

The `predictions` field is what makes COVID-era claims findable years later. Compile turns each prediction into a concept article with a date and a cited source; six months from now, *"what did Lily predict about remote work?"* returns a curated list with their aging status.

### Social post frontmatter (in `raw/social/<surface>/<date>-<slug>.md`)

```yaml
---
platform: facebook-page              # facebook-page | facebook-personal | instagram-en |
                                     # instagram-ru | linkedin | x
language: ru                         # ru | en
account_url: https://www.facebook.com/LilyGaripovaRealEstate
post_url: https://www.facebook.com/.../posts/123
date: 2024-03-15
post_type: text-with-image           # text | text-with-image | image | video | reel | story | repost | article
visibility: public                   # the post itself is public; engagement filtered separately
engagement:
  likes: 47
  comments: 12
  shares: 3
hashtags: [westside, denverrealestate]
ingested_via: meta-graph-api         # meta-graph-api | data-export | web-clipper | manual
ingested_at: 2026-04-26T14:22:00Z
---

[post body, then any extracted comments]
```

`language` lets `just ask "what hooks have worked best in my Russian Instagram posts?"` filter by language. `engagement` and any extracted comments are treated as `internal`-tier at retrieval despite the file's `public` visibility — they're useful as context for pattern analysis but shouldn't be quoted in drafts.

### Account inventory (in `raw/social/account-inventory.md`)

```yaml
---
title: "Lily's social account inventory"
visibility: internal
last_audit: 2026-04-26
---
# Surfaces

## Facebook Page — Lily Garipova Real Estate
- url: https://www.facebook.com/LilyGaripovaRealEstate
- languages: [ru, en]
- account_type: business-page
- api_tier: B (Graph API + Page Access Token)
- track: 2 (raw/social/facebook-page/)
- last_export: 2026-03-01
- last_api_pull: 2026-04-26

## Facebook Personal
- url: https://www.facebook.com/lily.garipova
- languages: [ru, en]
- account_type: personal-profile
- api_tier: A (export only)
- track: 2 (raw/social/facebook-personal/)
- last_export: 2026-03-01

## Instagram English
- url: https://www.instagram.com/lily.garipova.realty
- language: en
- account_type: TBD (business-or-creator-linked-to-fb-page → tier B; otherwise tier A)
- track: 2 (raw/social/instagram-en/)

## Instagram Russian
- url: https://www.instagram.com/...
- language: ru
- account_type: TBD
- track: 2 (raw/social/instagram-ru/)

## LinkedIn (personal)
- url: https://www.linkedin.com/in/lily-garipova
- language: en
- account_type: personal-profile
- api_tier: A (export only) + C (web clipper for high-signal)
- track: 2 (raw/social/linkedin/)

## YouTube (Russian)
- url: https://www.youtube.com/@lily-garipova-realty-ru
- language: ru
- api_tier: B (YouTube Data API v3, free quota)
- track: 1 (raw/transcripts/ via fetch-youtube-channel.py)

## X.com
- url: https://x.com/lily_garipova
- language: en
- api_tier: A (data export); B unaffordable for personal use
- track: 2 (raw/social/x/)
```

This is the single source of truth for ingestion scripts: they read this file to know which surfaces exist, what tier of access applies, and where to deposit their output.

### Client record (in `raw/operations/clients/<slug>.md`)

```yaml
---
name: "Jane Smith"
visibility: internal
first_contact: 2018-11-03
status: closed-buyer
family:
  spouse: "Mark Smith"
  children:
    - name: "Emma"
      birthday: 2014-03-08
    - name: "Liam"
      birthday: 2016-08-12
birthday: 1985-05-14
anniversary: 2012-09-22
preferred_contact: email
referral_source: "Sarah Chen"
transactions: [[transactions/123-oak-st]]
---
```

Sections: notes, conversation history, gifts received (wikilinks to presents-log entries), email history (wikilinks to emails-log entries), reviews.

### Transaction record (in `raw/operations/transactions/<slug>.md`)

```yaml
---
address: "123 Oak Street"
visibility: internal
neighborhood: "West Side"
client: [[clients/jane-smith]]
role: "buyer's agent"
list_price: 750000
sold_price: 735000
listed: 2019-04-01
closed: 2019-06-15
days_on_market: 75
commission_pct: 2.5
---
```

Sections: the sale story (what happened, what was learned), photos (or wikilinks to assets), comparable listings cited.

## Compile pipeline mechanics

### Skip-list change

`scripts/utils.py:list_raw_files()` currently skips directories named `assets`. Add `operations` *and* `social` to that skip-list. One-line change.

### Content-guidelines as required compile context

When `compile.py` processes any file under `raw/website/articles/**` or `raw/website/pages/**`, the prompt **must include the contents of `raw/website/meta/content-guidelines.md`** as required reading. The same rule applies to any `just ask` flow that produces public-facing draft content (ad copy, social posts, LinkedIn long-form, blog drafts).

This enforces P11–P17 (title discipline, fact density, brand-by-name, brand-mention pattern), P20 (niche-specific award page titles), P21 (awards with numbers), P23 (search term in title), P24 (bullets, tables, long-form structure) without requiring the LLM to remember them — it reads them as context every time.

Mechanism: `compile_source()` detects when `source_path` is under `raw/website/{articles,pages}/` and prepends the content-guidelines content to the prompt. For `query.py`, a similar branch detects "draft public content" intent (configurable trigger phrase, or a `--public` flag) and includes the guidelines.

### Visibility filtering at retrieval

When drafting public-facing content, the retrieval step filters out raw files (and their derived concept articles) tagged `visibility: internal`. The compile and query implementations carry the visibility tag through into concept frontmatter so retrieval can filter without re-reading sources.

For internal-use queries (`just ask "should I take a Capitol Hill listing?"`), no filter applies — the LLM sees everything.

For social posts: the retrieval step keeps the post body but strips the `engagement` metrics block (and any extracted comments) when drafting public content, even though the post's `visibility` is `public`.

### `synthesize-operations.py` (deferrable to v2)

```python
# Same SDK pattern as lint.py:check_contradictions
async def synthesize_operations() -> list[str]:
    content = read_all_operations()  # bulk read of raw/operations/**
    prompt = "Find cross-record patterns: referral correlations, segment overlaps, gift-retention links, ..."
    # ... emit one or more knowledge/connections/<pattern>.md files
```

Triggered by `just synthesize`. Cost-bounded (one LLM call per run, not per file). Output lands in `knowledge/connections/` with sources back to the operational records.

### `synthesize-social.py` (deferrable to v2)

Parallel structure to `synthesize-operations.py`, but reading `raw/social/**` and producing pattern articles like *"top-10 LinkedIn posts by engagement all open with a question"* or *"Russian Instagram posts about West Side schools get 3× the engagement of generic listing posts"*. Output lands in `knowledge/connections/`.

Can be filtered: `just synthesize-social --platform=linkedin`, `just synthesize-social --language=ru`, etc., to produce surface-specific or language-specific analyses.

### `synthesize-brand-ambassador.py` (deferrable to v2)

A single LLM-driven synthesis pass that produces `knowledge/brand-ambassador.md` — a unified master document stitching the seven mandatory documents (company overview, voice/style, content guidelines, important pages, brand mentions, directory tracking, keyword research) plus the competitor profiles and high-signal concept articles into one navigable doc. This is the document uploaded to external Claude / ChatGPT / NotebookLM projects to give them everything-about-Lily in one shot.

Triggered by `just brand-ambassador` (or rolled into `just synthesize`). Updates whenever any constituent doc changes — runs incremental, comparing input hashes since last build, similar to `compile.py`'s state.json mechanism.

This is the explicit P7 ("brand ambassador that updates itself") implementation. Deferrable to v2.

### `publish` (deferrable to v2)

A separate script that reads `raw/website/` and emits the AEO-optimized public site. Implementation choice — Eleventy, Astro, or a custom Markdown→HTML renderer. Out of scope for the v1 KB design; the spec just guarantees that `raw/website/` is the source of truth when the publish step is built.

## Social ingestion scripts (deferrable to v2)

Three ingestion scripts cover the access matrix from A7. All write into `raw/social/<platform>/<date>-<slug>.md` (or `raw/transcripts/` for YouTube), reading the surface inventory from `raw/social/account-inventory.md` to know which platforms to attempt and which tier to use.

| Script | Tier | Cadence | Surfaces it covers |
|---|---|---|---|
| `scripts/import-social-export.py` | A | One-time per export ZIP | Any platform — accepts a downloaded data-export ZIP, normalizes posts into the bucket. |
| `scripts/fetch-meta-social.py` | B | Recurring (manual `just fetch-meta` or cron) | FB Page (always), IG Business/Creator (if linked) — incremental pull since last sync. Stores the last-sync cursor in `scripts/state.json`. |
| `scripts/fetch-youtube-channel.py` | B | Recurring (manual `just fetch-youtube` or cron) | YouTube — lists channel videos via Data API v3, runs each new video through existing `transcript.py`, drops transcripts into `raw/transcripts/`. |

**Bootstrap order**: ship Tier-A import first (covers everything one-time), then add Tier-B fetchers in priority order (YouTube highest because of content depth, then FB Page, then IG if account types confirmed Business+linked).

LinkedIn personal, FB Personal, X — Tier A (export) only. No Tier B fetcher planned. Web Clipper (Tier C) covers high-signal individual posts.

## Bootstrap / migration

1. Fork obsidian-brain into `lilygaripovarealestate-brain` and `lilygaripovarealestate-brain-content` (private). Same `link-content.py` setup flow as documented in obsidian-brain's README.
2. Copy the seven AEO-research files from `obsidian-brain/raw/research/business/*.md` into `lilygaripovarealestate-brain-content/raw/research/aeo/` with attribution. These seed the AEO doctrine immediately so the first website articles aren't written cold.
3. Adapt `AGENTS.md` and `CLAUDE.md` to real-estate domain language (article schemas, examples, the visibility-flag rule, the social bucket).
4. Adapt `.claude/skills/` and `.claude/commands/` — most carry over unchanged; some (e.g. `kb-collect-assets`) need scoped wording.
5. **Initialize the eight mandatory documents as stubs** (per §Mandatory documents):
   - `raw/brand/company-overview.md`
   - `raw/brand/voice-and-style.md`
   - `raw/website/meta/content-guidelines.md` (port the relevant rules from `raw/research/business/Ranking in AI Search.md` and `raw/research/business/Blogging.md` and `raw/research/business/Awards in AI Search.md`)
   - `raw/website/meta/important-pages.md`
   - `raw/research/brand-mentions.md`
   - `raw/research/aeo/directory-tracking.md`
   - `raw/research/aeo/keyword-research.md`
   - `raw/social/account-inventory.md` (fill in the seven surfaces with URLs, languages, account types, API tiers)
6. Initialize empty `raw/operations/{presents-log,emails-log,timeline}.md` with a header. Initialize empty client/transaction folders.
7. Initialize empty `raw/social/{facebook-page,facebook-personal,instagram-en,instagram-ru,linkedin,x}/` folders with `.gitkeep` files.
8. Begin dumping content into the nine human-authored buckets.
9. Run `just compile` periodically as content accumulates.
10. Once Tier-A export ZIPs are in hand, run `just import-social <zip>` for each surface. Then build Tier-B fetchers in priority order (YouTube → FB Page → IG if eligible).

## What's intentionally out of scope for v1

- **`synthesize-operations.py`, `synthesize-social.py`, `synthesize-brand-ambassador.py`** — useful but not blocking. v1 ships with these scripts absent; `operations/` and `social/` are independently navigable, and the unified brand-ambassador doc is a v2 nice-to-have for external Claude/ChatGPT/NotebookLM uploads.
- **The publish step** (`raw/website/` → live AEO site) — separate workstream. The KB v1 just provides the content source.
- **Tier-B social fetchers** (`fetch-meta-social.py`, `fetch-youtube-channel.py`) — also v2. v1 ships with the import-export normalizer (`import-social-export.py`) only, since that requires no API setup.
- **Automation around CRM events** (auto-send birthday email when timeline says it's today) — out of scope; the timeline file is for human reference, not a triggering system.
- **Importing 9 years of historical content** — that's a continuous activity over weeks/months, done by Lily/Radif manually or via tools (Web Clipper for sites, `transcript.py` for webinars, the Tier-A export normalizer for social). The spec describes the destination, not the migration tooling.
- **Operational AEO activities** — getting awards (P19), running directory-tracking workflows in Google AI mode (P26–P27), Reddit topic discovery (P28), and primary-bias content campaigns (P10). The spec defines the named slots that *receive* the output of these activities (`raw/website/awards/`, `raw/research/aeo/directory-tracking.md`, `raw/research/aeo/keyword-research.md`, `raw/research/brand-mentions.md`); the populating is ongoing work, not a v1 implementation deliverable.
- **Visibility-flag enforcement at code level** — v1 relies on review discipline + the compile pipeline's filter when drafting public content. If `internal` content starts leaking into public output, add a `lint.py` check that scans drafted public content for verbatim quotes from `internal` sources.
- **Cross-language post pairing** — when Lily posts the same content in RU + EN, treating them as a paired unit (same hook, two languages) is interesting analytically but not v1. v1 treats every social post as independent; `language:` frontmatter makes filtering trivial. Pairing logic can be added later if `synthesize-social.py` shows it'd be valuable.

## Open questions deferred to implementation

- Naming convention for `raw/transactions/<slug>.md` when same address transacts twice — prefix-year vs single-file-with-sections is left to the first time it happens.
- Operations logs (`presents-log.md`, `emails-log.md`, `timeline.md`) grow without bound. If they exceed ~5,000 lines, shard by year. Don't pre-shard.
- Schema enforcement on competitor / webinar / client / transaction frontmatter — review-only for v1. If drift becomes a problem, add a `lint.py` check that validates against a JSON Schema.
- Trigger mechanism for "draft public content" filter in `query.py` — explicit `--public` flag vs intent detection from the prompt. Pick at implementation time.
- **Instagram account types — TBD.** Are IG-EN and IG-RU Business or Creator accounts each linked to a Facebook Page? If yes → Tier B (Graph API) viable, `fetch-meta-social.py` covers them. If personal → Tier A only. The `account-inventory.md` mandatory doc is where this gets resolved during bootstrap; the rest of the spec is agnostic.
- Storage for social ZIPs — exports can be hundreds of MB or several GB. The content repo's git-LFS rule (set up in obsidian-brain's content repo for `*.pdf`, `*.png`, etc.) should extend to `*.zip`. Decide at content-repo init.
