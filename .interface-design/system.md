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

Follows size: `--r-xs 8` · `--r-sm 10` (controls) · `--r-md 12` · `--r-lg 16` · `--r-xl 18` (cards, tiles).
Only tab tracks, badges/chips and avatars are fully round (99px). No other literal radii.

## Typography

Body: 14.5px Vazirmatn, deliberate for Vazirmatn's small x-height. Persian needs generous line-height: body ≥ 1.7.
Hierarchy from weight + colour first, size second. No `letter-spacing` and no `text-transform` on Persian text
(it breaks the joined letters); tracking only on Latin-only strings such as codes.

Type scale (each size paired with a line-height token; being introduced in Phase 3 batch 2):

| Token | Size | Line-height | Use |
|---|---|---|---|
| `--fs-caption` / `--lh-caption` | 12px | 1.6 | badges, table heads, meta |
| `--fs-small` / `--lh-small` | 13px | 1.7 | secondary text, hints, table cells (dense) |
| `--fs-body` / `--lh-body` | 14.5px | 1.75 | body, inputs, buttons |
| `--fs-title` / `--lh-title` | 16px | 1.5 | card titles, sheet titles |
| `--fs-h1` / `--lh-h1` | 24px | 1.35 | page title |
| `--fs-figure` / `--lh-figure` | 28px | 1.3 | KPI value (weight 500, tabular) |
| `--fs-hero` / `--lh-hero` | 40px | 1.2 | single hero figure (pricing overview) |

Inputs are 16px on phones (iOS zoom). Numeric values (prices, counts, table number columns, timers) use
`font-variant-numeric: tabular-nums`; numeric table columns are end-aligned.

## Spacing

4px base. Scale (being introduced in Phase 3 batch 2): `--sp-1 4` · `--sp-2 8` · `--sp-3 12` · `--sp-4 16` ·
`--sp-5 20` · `--sp-6 24` · `--sp-8 32` · `--sp-10 40` · `--sp-14 56`. `2px` and `6px` allowed only inside small
controls (badge/chip internals). Gap between groups ≥ 2× the gap inside a group.

## Layout & RTL

- Logical properties only (`margin-inline-start`, `inset-inline-end`, `text-align: start`). Physical left/right
  only for physical geometry (safe-area insets), with a `[dir]` override for any `translateX`.
- Horizontally scrolling rows (chips, page tabs) fade at the overflow edge and scroll the active item into view.
- One primary (pink) action per view. When the page has its own primary action, the module's header action
  becomes `.btn.soft`.

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
- **Empty state** `.empty` — icon, title (what this place is), one line (how it fills), one action when there is
  one. Filtered-empty names the filter and offers to clear it.

## Motion

Every transition uses `--ease-*` / `--dur-*`. Enter/exit ease-out, on-screen movement ease-in-out, sheets
ease-drawer; exits faster than entrances. Only transform/opacity, under 250ms, none on keyboard shortcuts or
repeated actions. Hover effects live behind `@media (hover: hover) and (pointer: fine)`. Respect
`prefers-reduced-motion`.

## Numbers

- Digits: Persian everywhere, via `num()`/`compact()` (Intl `fa-IR`). Codes (SKU `PRD-010`, sale `S-12`) stay
  Latin, isolated with `.ltr`.
- Money: full amounts in tables without unit (column header carries «تومان»); summaries use `compact()` +
  «تومان». See the Phase 1 audit notes for the inconsistencies being fixed.
