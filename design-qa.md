# 咸鱼项目记账助手 — Design QA

## Comparison Target

- Source visual truth: `/Users/chentao/Downloads/咸鱼项目记账助手_Codex参考素材/00_full_reference.png`
- Source layout guide: `/Users/chentao/Downloads/咸鱼项目记账助手_Codex参考素材/layout_annotated.png`
- Source focused references: `/Users/chentao/Downloads/咸鱼项目记账助手_Codex参考素材/03_summary_cards.png` through `11_delivery_countdown.png`
- Browser-rendered implementation: `/Users/chentao/Documents/New project 3/qa/implementation-final.png`
- Full-view comparison: `/Users/chentao/Documents/New project 3/qa/compare-final.png`
- Focused comparison: `/Users/chentao/Documents/New project 3/qa/focused-comparison.png`
- Final verified URL: `http://127.0.0.1:4341/#%E9%A1%B9%E7%9B%AE%E7%AE%A1%E7%90%86`
- State: desktop dashboard, initial loaded state, no search filter, drawer closed.

## Viewport And Normalization

- Source pixels: 1448 × 1086.
- Implementation pixels: 1448 × 1086, captured full-page from a 1448 × 1086 CSS viewport.
- CSS viewport: 1448 × 1086.
- Device scale factor: 1.
- Density normalization: none required; source and implementation are equal-density, equal-size PNGs.
- Full-view alignment: top-left aligned with no browser chrome or extra canvas padding.

## Full-view Comparison Evidence

The final comparison confirms the same high-level composition: 270 px fixed sidebar, greeting/search/profile header, five unequal-width metric cards, three-card core row, payment/detail row, light blue-purple background, rounded white surfaces, and the same visual hierarchy. All major regions remain visible within the 1448 × 1086 frame.

## Focused Region Evidence

`qa/focused-comparison.png` contains equal-size source and implementation pairs for:

1. Metrics: titles, amount hierarchy, illustration placement, mini charts, colors, and card proportions.
2. Core row: income chart, project progress rows, operation-duration card, radii, and spacing.
3. Detail row: payment table, daily balance, goal, reminders, customer source, and delivery countdown.

These focused views were required because table typography, small labels, chart scales, and asset crops are too small to judge confidently from the full-view comparison alone.

## Comparison History

### Pass 1 — blocked

- [P2] Metric amounts collided with the decorative 3D objects because the initial grid used equal-width columns.
  - Fix: changed the desktop grid to the source's unequal card ratios and tightened the first amount's optical size.
  - Post-fix evidence: `qa/implementation-1448x1086-pass2.png` and the Metrics row in `qa/focused-comparison.png`.
- [P2] The initial month total showed ¥4,700 instead of the source-grounded ¥5,680, and due-date pills were one day high.
  - Fix: corrected the mock payment date and normalized date arithmetic to local midnights.
  - Post-fix evidence: the final DOM and screenshot show ¥5,680, 2/6/1-day project pills, and a 10-day delivery countdown.
- [P2] Sidebar promo/countdown cards sat too low because a flexible spacer consumed the available column height.
  - Fix: changed the spacer to fixed height so both cards align with the source's vertical rhythm.
  - Post-fix evidence: `qa/compare-final.png`.
- [P2] The operation-duration crop contained duplicated source text and visually overlapped the implementation copy.
  - Fix: recropped the supplied source artwork to the illustration-only region.
  - Post-fix evidence: the Core row in `qa/focused-comparison.png`.
- [P2] A desktop floating CTA covered the delivery countdown and did not appear in the source.
  - Fix: hid the floating CTA on the reference desktop breakpoint while retaining it for tablet/mobile access.
  - Post-fix evidence: `qa/implementation-final.png`.

### Pass 2 / Final — passed

No actionable P0/P1/P2 design differences remain after the fixes above.

## Required Fidelity Surfaces

- Fonts and typography: uses a PingFang/SF/Inter-aligned system stack with matching heavy display headings, compact table copy, tabular amount figures, coherent weight hierarchy, and no clipped or overlapping desktop text. The Chinese fallback renders consistently at tested widths.
- Spacing and layout rhythm: card widths, three-row composition, 11–12 px region gaps, 20–22 px radii, fixed sidebar, core card proportions, and bottom detail grouping closely match the reference. The final 1448 frame has no horizontal overflow.
- Colors and visual tokens: blue-purple primary, green income, orange duration, red attention states, muted slate copy, soft borders, translucent surfaces, and restrained shadows map to the source palette and retain readable contrast.
- Image quality and asset fidelity: all prominent supplied visual subjects are present—duck mascot, planet, wallets, payment card, clipboard, orange calendar, purple operation calendar, trophy, and hourglass. They use real raster source assets, not custom SVG/CSS substitutes. Final crops are sharp at the rendered slot sizes.
- Copy and content: app-specific Chinese labels match the supplied prompt; currency uses CNY formatting; dates use Chinese-local formatting; dynamic dates intentionally differ from the static 2025 reference.
- Icons: Phosphor icons provide one consistent rounded/duotone family for navigation, controls, project rows, notifications, and form feedback.
- Responsiveness: 1280, 1024, and 768 screenshots are saved under `qa/`. Each has `scrollWidth === clientWidth`. At 1024 and 768 the fixed sidebar becomes an accessible off-canvas menu and the metric/detail grids reflow without overlap.
- Accessibility: semantic headings/regions/table/dialog, explicit input labels, alt text for meaningful images, visible focus rings, Escape-to-close drawer behavior, practical tablet tap targets, and `prefers-reduced-motion` support are present.

## Interaction And Browser Verification

- Opened the quick-accounting drawer from the sidebar.
- Confirmed validation rejects a blank/zero amount with a visible field error.
- Submitted a ¥320 stage payment and verified cumulative income, monthly income, today income, trend badge, goal progress, net income, row count, and newest payment row all update together.
- Verified success toast and icon-based particle feedback.
- Searched for “李老板” and verified one matching project and two matching payments.
- Opened and closed the tablet sidebar at 1024 px.
- Checked the browser console after the stable final render: no errors or warnings.

## Seven-page Extension QA

- New reference sources: `public/reference/pages/project-management.png`, `income-records.png`, `expense-records.png`, `customer-management.png`, `data-statistics.png`, `goal-plan.png`, and `settings-center.png`.
- Final normalized comparisons: `qa/pages/comparison-sheet-final.png`; every pair places the supplied reference on the left and the matching implementation on the right at the same 4:3 frame.
- Final individual implementation captures: `qa/pages/project-v2.png`, `income.png`, `expense-v4.png`, `customer-v3.png`, `analytics-v4.png`, `goals-v4.png`, and `settings-v4.png`.
- The project and customer pages were corrected so their right-side dashboards begin beside the first-row summary cards, matching the supplied desktop composition.
- The goal page was corrected to use an independent achievement/focus/reminder rail so the route map and learning plan remain visible in the first frame.
- Expense alerts and settings groups were density-tuned so the reference's bottom content remains reachable without horizontal overflow.
- Recharts animations were allowed to settle before comparison; donut, area, line, and grouped-bar charts were visibly populated in the final captures.

### Extension interaction checks

- Left navigation changed the active route and URL hash for all seven pages.
- Created a new project through the modal and verified the new row appeared immediately.
- Switched the customer list between table and nine-card views.
- Opened and closed the income quick-accounting drawer from the income page.
- Toggled automatic backup and verified `aria-pressed` changed from `true` to `false`.
- Triggered immediate sync and verified the “数据同步完成” toast.
- Verified the mobile off-canvas navigation opens and the page has no horizontal document overflow at the tested narrow viewport.
- Final fresh-port handoff tab reported title “咸鱼项目记账助手”, visible H1 “项目管理”, active navigation “项目管理”, and no console errors or warnings.

## Follow-up Polish

- [P3] Some screenshot-derived 3D assets retain a faint light-background edge under close inspection; bespoke transparent originals would make these seams fully invisible.
- [P3] The top-right avatar uses a consistent icon treatment rather than the exact illustrated portrait from the static reference.

## Implementation Checklist

- [x] Source and implementation compared at the same desktop viewport and state.
- [x] Focused comparisons reviewed for metrics, core cards, and detail cards.
- [x] All P0/P1/P2 findings fixed and rechecked.
- [x] Primary interaction path and responsive menu tested in the in-app browser.
- [x] Typecheck, production build, and Sites worker tests passed.

final result: passed
