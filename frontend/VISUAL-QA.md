# Visual and Interaction QA Checklist

Run this for each new screen and for substantial UI changes.

## Visual hierarchy
- [ ] Primary action and page purpose are obvious.
- [ ] Spacing, typography, radii, borders, and elevation match the existing design system.
- [ ] Hover, focus, pressed, selected, disabled, loading, empty, success, and error states are visually distinct where applicable.
- [ ] Responsive layout works at narrow mobile, tablet, and desktop widths.
- [ ] No overflow, clipped popover, layout jump, or unexpected scroll movement.

## Motion
- [ ] Motion communicates a state change or provides useful feedback.
- [ ] Durations and easing are consistent with shared tokens.
- [ ] Enter and exit transitions both work.
- [ ] Repeated clicks, rapid month changes, and interrupted transitions do not break state.
- [ ] Lists use stable keys; large lists do not trigger excessive animation.
- [ ] No gratuitous bounce, constant movement, or excessive stagger.
- [ ] Animation does not block input or delay important content.
- [ ] `prefers-reduced-motion: reduce` is respected.

## Accessibility
- [ ] Keyboard navigation works without a mouse.
- [ ] Focus is visible and is not lost after dialogs or transitions.
- [ ] Controls have accessible names and appropriate semantics.
- [ ] Status changes are announced appropriately when needed.
- [ ] Color is not the only way to communicate state.
- [ ] Touch targets and drag interactions are usable on mobile.

## Engineering
- [ ] Lint/typecheck/tests/build pass where configured.
- [ ] No console errors, hydration warnings, or React key warnings.
- [ ] No unnecessary animation dependencies or duplicate primitives.
- [ ] Motion uses transform/opacity where practical.
- [ ] Actual browser behavior was checked if browser tooling is available.
- [ ] Any unverified behavior is explicitly noted in the delivery summary.
