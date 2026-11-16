# UI Quality and Motion Standard

## Non-negotiable principle
A feature is not complete when it merely compiles. It must have a coherent visual hierarchy, intentional interaction states, and appropriate motion. Motion is part of implementation, not optional polish.

## Before changing UI
1. Inspect the existing framework, package manager, styling conventions, design tokens, router, and component library.
2. Reuse existing components and animation dependencies where possible. Do not introduce a competing UI or animation system without a clear reason.
3. Identify the key user interactions and their initial, active, loading, success, empty, and error states.
4. Keep the design consistent with the product. Do not blindly apply animation to every element.

## Required interaction feedback
- Buttons: clear hover/focus and press feedback; disabled and loading states must be distinct.
- Dialogs/popovers: deliberate entrance and exit, with existing accessibility semantics preserved.
- Calendars/date pickers: animate month/view changes and selected-date indicators without shifting the whole page unexpectedly.
- Tabs/segmented controls: animate the active indicator when appropriate; maintain keyboard navigation.
- Lists/grids: animate additions/removals/reordering using stable keys; do not animate huge datasets indiscriminately.
- Forms: communicate validation, submission, success, and failure states.
- KPIs: animate meaningful numeric changes only when it improves comprehension; avoid misleading or distracting counters.
- AI interfaces: distinguish idle, listening, thinking, streaming, tool execution, success, and failure. Never imply a tool is working when it is not.
- Navigation: animate route or panel transitions where they aid continuity; preserve focus and avoid unexpected scroll jumps.
- Data-heavy screens: use skeletons or restrained transitions when useful; avoid delaying access to data.

## Motion defaults
Use `src/lib/motion.ts` when present. Otherwise establish equivalent shared tokens.
- Fast feedback: 120–180 ms.
- Standard interaction: 180–250 ms.
- Panels/dialogs: 220–350 ms.
- Use restrained spring physics for tactile controls and ease-out for entrances.
- Keep hover movement subtle; no exaggerated bounce, gratuitous parallax, or constant movement without purpose.
- Prefer `transform` and `opacity`; measure performance before adding complex layout animation.

## Accessibility and robustness
- Respect `prefers-reduced-motion`; provide reduced or instant transitions where appropriate.
- Preserve semantic HTML, accessible names, focus management, keyboard behavior, and visible focus rings.
- Support touch and mouse; do not rely on hover as the only affordance.
- Handle rapid repeated actions, interrupted animations, unmounting, and loading/error states.
- Avoid fake progress and animations that misrepresent real system activity.
- Do not use animation to hide latency or block users from interacting.
- Avoid hydration errors and unnecessary client components in Next.js.
- Keep bundles and rendering overhead proportionate to the benefit.

## Mandatory visual QA
Before calling a UI feature done:
1. Run available lint, typecheck, tests, and build checks.
2. Run the app and inspect the rendered interface when browser tooling is available.
3. Exercise all important interaction states, including reverse transitions and rapid repeated interactions.
4. Check mobile and desktop layouts.
5. Check keyboard/focus behavior and reduced-motion behavior.
6. Fix jarring, missing, inconsistent, inaccessible, or distracting motion.
7. Report exactly what was verified and what could not be verified. Never claim browser verification without actually performing it.
