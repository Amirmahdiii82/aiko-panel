# Aiko Panel — interface system

Source of truth for UI decisions. Read before any UI work; update when a decision changes.
Styling lives in `app/core/web/css/ui.css` (shared) and `app/modules/<id>/web/<id>.css` (module-only components that
never restyle shared ones).

## Intent

- **Who:** the two owners and a few sellers of Aiko Cosmetics, a small Iranian cosmetics shop. Persian speakers,
  often on a phone between customers, sometimes at a desk doing the books.
- **What they do:** record a sale or purchase in seconds, see what needs attention (out of stock, unpaid, site
  sync errors), check money and margins, compare competitor prices, make product media.
- **Feel:** quiet and exact, like a well-kept ledger. Calm surfaces, numbers that read at a glance, nothing
  decorative. Professional, not playful.

## Identity (do not change)

- **Language/direction:** Persian, `lang="fa" dir="rtl"`, RTL only. Persian digits via `Intl.NumberFormat("fa-IR")`.
- **Typeface:** Vazirmatn (400, 500/600, 700), bundled in `app/core/web/fonts/`.
- **Accent:** Aiko pink (`--accent`, `--accent-ink` for text, `--accent-soft` for tints).
- **Themes:** dark is the default; light is a warm off-white. `<html data-theme>` is always set by `theme.js`.

## Colour rules

- Pink only for **the one primary action of a view** and **the main figure or series of a screen**. Never for
  categories, channels, avatars, counts or secondary badges.
- Selection (active tab, segment) is a lighter step (`--pill`) that slides between items, never pink.
- Status colours (`--ok`, `--warn`, `--bad`, `--info` and their `-soft` tints) only for real status. An account
  name, a channel or a category is not a status → neutral `.badge` (`--surface-3` / `--ink-2`).
- A "change vs previous period" shows only when a previous period exists. No previous period → show nothing.
- No new hex values in rules. Every colour goes through a `:root` token (light) with its `[data-theme="dark"]` pair.

## Depth

- Surfaces: `--bg` → `--surface` (cards, tiles, fields) → `--surface-2` (insets, hover) → `--surface-solid`
  (sheets, menus, popovers that must hide what is under them).
- Cards are flat with a hairline: `inset 0 0 0 1px var(--line)`. No glow, no glass. Dense tables use borders only.
- Only what content scrolls under (top bar when scrolled, bottom bar, sheets, menus) is translucent and blurred.
- Shadows (`--shadow`, `--shadow-lg`) only for floating layers; dark mode leans on the `--line` ring.

## Radius

Follows size: `--r-2xs 6` · `--r-xs 8` · `--r-sm 10` (controls) · `--r-md 12` · `--r-lg 16` · `--r-xl 18` (cards, tiles) · `--r-2xl 24` (sheets, palettes) · `--r-full` (pills, avatars).
Only tab tracks, badges/chips and avatars are fully round (99px). No other literal radii.

## Typography

Body: 14.5px Vazirmatn, deliberate for Vazirmatn's small x-height. Persian needs generous line-height: body ≥ 1.7.
Hierarchy from weight + colour first, size second. No `letter-spacing` and no `text-transform` on Persian text
(it breaks the joined letters); tracking only on Latin-only strings such as codes.

Type scale (tokens in `:root`, about 1.2 from the 14.5px body). Each role pairs a size with a line-height token:
`--lh-tight 1.2` (display), `--lh-heading 1.35`, `--lh-ui 1.55` (dense UI), `--lh-body 1.75` (body, never below 1.7).

| Token | Size | Use |
|---|---|---|
| `--fs-micro` | 11px | counts inside pills, chart axes, kbd |
| `--fs-caption` | 12px | badges, table heads, meta |
| `--fs-small` | 13px | secondary text, labels, buttons-sm, dense table cells |
| `--fs-body` | 14.5px | body, inputs, buttons |
| `--fs-title` | 16px | card titles, sheet titles |
| `--fs-lead` | 19px | totals, detail values |
| `--fs-figure-sm` | 22px | figures in a KPI strip, phone page title |
| `--fs-h1` | 24px | page title (600) |
| `--fs-figure` | 28px | KPI value (500, tabular) |
| `--fs-figure-lg` | 34px | the screen's main figure (600, tabular) |
| `--fs-display` | 48px | single hero figure (pricing index) |

Inputs are 16px on phones (iOS zoom). Numeric values (prices, counts, table number columns, timers) use
`font-variant-numeric: tabular-nums`; numeric table columns are end-aligned.

## Spacing

4px base. Scale: `--sp-0-5 2` · `--sp-1 4` · `--sp-1-5 6` · `--sp-2 8` · `--sp-3 12` · `--sp-4 16` ·
`--sp-5 20` · `--sp-6 24` · `--sp-8 32` · `--sp-10 40` · `--sp-14 56`. `2px` and `6px` allowed only inside small
controls (badge/chip internals). Gap between groups ≥ 2× the gap inside a group.

## Layout & RTL

- Logical properties only (`margin-inline-start`, `inset-inline-end`, `text-align: start`). Physical left/right
  only for physical geometry (safe-area insets), with a `[dir]` override for any `translateX`.
- Horizontally scrolling rows (chips, page tabs) fade at the overflow edge and scroll the active item into view.
- One primary (pink) action per view. When the page body has its own `.btn.primary`, the module's header action
  steps back to the soft look automatically (`.main:has(#view .btn.primary) #top-action .btn.primary` in ui.css).

## Components

- **Button** `.btn` — 42px h · 0 18px · `--r-sm` · 13.5→`--fs-body`/500. Variants: `primary` (pink, one per view),
  `soft`, `ghost`, `danger` (destructive confirmations only, never repeated per row). `sm` 34px, `xs`.
  Press: `scale(.97)`.
- **Badge** `.badge` — 22px h, round, caption size/600. Neutral by default; status variants only for status.
- **KPI tile** `.kpi` — always label / value + unit / foot, same surface + hairline in a strip; value 28px/500
  tabular; only the screen's main figure uses `--accent-ink` (`.kpi.hero`).
- **Table** `table.t` — head caption/500/muted with a bottom hairline; cells 11px 12px; row hover only on
  clickable rows. Row actions that change data live in a row "⋯" menu or the detail sheet, never as a repeated
  coloured button, and never hover-only (touch has no hover).
- **Thumbnails in lists** — decided per store, not per row: if the store uses product images, every row keeps the
  slot (neutral placeholder when missing) so rows stay aligned; otherwise no slot.
- **Avatar** `.avatar` — neutral (`--surface-3` / `--ink`), never the accent.
- **Activity feed** — an item shows its module's name only when the list mixes modules (`mixedModules()`).
- **Payment / account** — the account a sale was paid into is plain text; only «نسیه» / unpaid carries a status badge.
- **Empty state** `.empty` — icon, title (what this place is), one line (how it fills), one action when there is
  one. Filtered-empty names the filter and offers to clear it.

## Pricing module

- Position (cheapest / close / above / far above / unique / no price) uses status colours plus a mark (✓ ≈ ▲ ▲▲ ★ –),
  so colour is never the only cue. "Unique" and "no price" are neutral badges, never pink.
- One cell for where a product stands: `posGap()` = mark + short label + gap % to the cheapest competitor. No separate
  gap column.
- Match score bars are neutral (`--ink-2`), not the accent. Your side of a review card is a `--surface-2` inset.
- Run history shows one line of counts per run ("۶ موفق · ۱ مسدود"); the per-site detail opens in a `<details>`.
- Products on phones render as a list (name, your price vs cheapest, position badge), not a sideways-scrolling table.
- `.phone-only` / `.desk-only` split one action between the page header (desktop) and the page body (phone), so a
  view never shows the same action twice.
- Charts of real data use `cubicInterpolationMode: "monotone"` so a smoothed line never invents values.

## Motion

Every transition uses `--ease-*` / `--dur-*`. Enter/exit ease-out, on-screen movement ease-in-out, sheets
ease-drawer; exits faster than entrances. Only transform/opacity, under 250ms, none on keyboard shortcuts or
repeated actions. Hover effects live behind `@media (hover: hover) and (pointer: fine)`. Respect
`prefers-reduced-motion`.

## Numbers

- Digits: Persian everywhere, via `num()`/`compact()` (Intl `fa-IR`). `fa()` adds thousands separators to whole numbers of
  five digits or more (years and codes keep their digits). Codes (SKU `PRD-010`, sale `S-12`) stay
  Latin, isolated with `.ltr`.
- Money: full amounts in tables without unit (column header carries «تومان»); summaries use `compact()` +
  «تومان». See the Phase 1 audit notes for the inconsistencies being fixed.
