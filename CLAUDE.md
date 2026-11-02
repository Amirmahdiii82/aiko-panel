# CLAUDE.md

## UI skills

- All UI work: `interface-design`. Design decisions live in `.interface-design/system.md`. Read it before any UI
  work and keep it updated.
- Styling lives in `app/core/web/css/ui.css`. Every color, font, radius and spacing value goes through a CSS custom
  property declared in `:root`. No new hex values or magic numbers in rules. If tokens don't exist yet, propose a
  token block before using new values.
- Module stylesheets (`app/modules/<id>/web/<id>.css`) only add module-specific components; they never restyle shared
  ones and use the same tokens.
- Review skills are manual-only (`disable-model-invocation: true`): `better-typography`, `better-accessibility`,
  `better-layout`, `better-writing`, `interface-review`, `review-animations`, `remove-animations`, `break-ui`,
  `web-design-guidelines`. `npx skills update` may drop that flag; re-apply it after updates.

## Conflict rules (these override any individual skill)

- Persian text: no `letter-spacing`, no `text-transform`. Labels, table headers and tags use normal weight/tracking.
- Hierarchy: weight + color before size. One accent (Aiko pink) for the one primary action and the main figure of a
  screen. One depth strategy: hairline borders (`--line`); shadows only on floating layers.
- Motion: transform/opacity only, under 250ms, `--ease-*`/`--dur-*` tokens, none on keyboard shortcuts or repeated
  actions. Respect `prefers-reduced-motion`.
- RTL only (`dir="rtl"`, Persian). Logical properties (`margin-inline-start`, `inset-inline-end`,
  `text-align: start`), never left/right except for physical geometry such as safe-area insets. Vazirmatn only.
- No hover-only actions: everything reachable by tap and keyboard.

## Review workflow (before merging UI)

1. `/interface-review` on the branch
2. `/break-ui` on any new data-heavy component (long names, empty lists, huge counts)
3. `/better-accessibility` on forms and dialogs
4. `/web-design-guidelines` as the last pass
