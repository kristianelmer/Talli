---
name: Talli
description: Quiet, systematic annual reporting for simple Norwegian holding companies.
colors:
  primary: "#176b55"
  primary-strong: "#084838"
  canvas: "#f7f8fa"
  surface: "#ffffff"
  selection: "#e8f3ef"
  ink: "#17202a"
  muted: "#617067"
  line: "#dfe5e8"
  warning: "#985713"
  danger: "#a73a34"
typography:
  headline:
    fontFamily: "Arial, Helvetica, sans-serif"
    fontSize: "32px"
    fontWeight: 750
    lineHeight: 1.2
    letterSpacing: "-0.025em"
  title:
    fontFamily: "Arial, Helvetica, sans-serif"
    fontSize: "24px"
    fontWeight: 750
    lineHeight: 1.25
    letterSpacing: "-0.015em"
  body:
    fontFamily: "Arial, Helvetica, sans-serif"
    fontSize: "15px"
    fontWeight: 400
    lineHeight: 1.55
  label:
    fontFamily: "Arial, Helvetica, sans-serif"
    fontSize: "13px"
    fontWeight: 700
    lineHeight: 1.3
    letterSpacing: "normal"
rounded:
  sm: "6px"
  md: "8px"
  lg: "10px"
  pill: "999px"
spacing:
  xs: "6px"
  sm: "10px"
  md: "14px"
  lg: "20px"
  xl: "32px"
components:
  button-primary:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.surface}"
    typography: "{typography.label}"
    rounded: "{rounded.md}"
    padding: "12px 16px"
    height: "44px"
  button-primary-hover:
    backgroundColor: "{colors.primary-strong}"
    textColor: "{colors.surface}"
    typography: "{typography.label}"
    rounded: "{rounded.md}"
    padding: "12px 16px"
    height: "44px"
  button-secondary:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    typography: "{typography.label}"
    rounded: "{rounded.md}"
    padding: "12px 16px"
    height: "44px"
  input:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    typography: "{typography.body}"
    rounded: "{rounded.md}"
    padding: "10px 12px"
    height: "44px"
  panel:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    rounded: "{rounded.lg}"
    padding: "20px"
  nav-item-active:
    backgroundColor: "{colors.selection}"
    textColor: "{colors.primary-strong}"
    typography: "{typography.label}"
    rounded: "{rounded.md}"
    padding: "10px 12px"
---

# Design System: Talli

## Overview

**Creative North Star: "The Clear Desk"**

Talli feels like sitting down to a clear, well-organized desk before completing consequential work. Everything required is visible and within reach; irrelevant operating-company features are absent. The interface is reassuring, plain-spoken, and meticulous, with calm hierarchy and familiar product conventions that let the owner concentrate on the annual reporting task.

The visual character is Quiet confidence expressed through Nordic clarity: crisp neutral surfaces, restrained evergreen accents, precise spacing, and minimal ornament. Density is moderate. Guidance is present at the point of action without turning the entire product into an inflexible wizard.

The system explicitly rejects visual imitation of Fiken, generic AI-generated styling, decorative novelty, clutter, feature bloat, unexplained accounting jargon, and intimidating filing flows.

**Key Characteristics:**

- Crisp, neutral, and highly legible.
- Systematic navigation with one obvious next action.
- Familiar controls with complete, unmistakable states.
- Moderate density without dashboard clutter.
- Motion limited to meaningful state feedback.

## Colors

Nordic clarity pairs a true neutral canvas with clear white working surfaces, evergreen action color, and cool charcoal text. Color is functional and restrained.

### Primary

- **Filing Green:** Primary actions, active navigation, progress, focus, and positive readiness. Its rarity makes it meaningful.
- **Deep Filing Green:** Hover and active states, plus occasional high-contrast anchored surfaces.

### Neutral

- **Crisp Canvas:** The application background. It is neutral rather than cream, paper, sand, or parchment.
- **Clear White:** Forms, tables, and working panels that need separation from the canvas.
- **Quiet Selection:** Active navigation and selected rows; never a decorative wash across whole sections.
- **Quiet Ink:** Primary text and high-consequence data.
- **Ledger Grey:** Secondary text and supporting metadata. It passes WCAG AA on Crisp Canvas and Clear White.
- **Fine Rule:** Dividers, input strokes, and structural boundaries.

### Semantic

- **Caution Ochre:** Warnings and states that require review. Pair it with an icon or explicit label; color alone never carries status.
- **Blocking Red:** Errors, destructive actions, and filing blocks. Use only where the user must act.

**The Ten-Percent Rule.** Filing Green occupies no more than roughly ten percent of a normal working screen. It marks action and state, never atmosphere.

**The True-Neutral Rule.** Warm cream, sand, paper, parchment, and beige application backgrounds are prohibited. Warmth comes from reassuring language and interaction quality, not a tinted canvas.

## Typography

**Display Font:** Arial (with Helvetica and generic sans-serif fallbacks)  
**Body Font:** Arial (with Helvetica and generic sans-serif fallbacks)  
**Label/Mono Font:** The system monospace stack is reserved for identifiers, payload previews, and technical evidence.

**Character:** One familiar sans-serif family carries the interface. Weight, spacing, and placement create hierarchy; decorative font pairing has no role in a filing product.

### Hierarchy

- **Headline** (750, 32px, 1.2): Page identity and the primary annual task. One per page.
- **Title** (750, 24px, 1.25): Major workflow areas and panel groups.
- **Body** (400, 15px, 1.55): Instructions, explanations, and form guidance, capped at 70ch for prose.
- **Label** (700, 13px, normal tracking): Controls, metadata, navigation, and compact state labels.
- **Technical** (400, 12px, 1.5): Identifiers and filing evidence only; never general body copy.

**The Product-Scale Rule.** Headings use fixed product sizes. Marketing-scale fluid headings and 44–84px interface titles are prohibited.

**The Sentence-Case Rule.** Navigation, labels, and section titles use Norwegian sentence case. Repeated uppercase eyebrows and tracked kickers are prohibited.

## Elevation

Talli is flat by default. Crisp Canvas, Clear White, Fine Rule, and spacing establish depth. Shadows are reserved for elements that genuinely sit above the document flow: menus, dialogs, popovers, and temporary overlays. Static panels and cards never combine a border with a wide soft shadow.

### Shadow Vocabulary

- **Overlay:** `0 8px 24px rgba(23, 32, 42, 0.14)` for menus, dialogs, and popovers only.
- **Focus ring:** `0 0 0 3px rgba(23, 107, 85, 0.22)` accompanies a visible Filing Green focus stroke on interactive controls.

**The Flat-By-Default Rule.** If an element remains in the normal document flow, structure it with tone, spacing, or Fine Rule—not a shadow.

## Components

Components are precise and familiar: standard affordances, compact geometry, consistent 6–10px curves, and unmistakable states. Every interactive component defines default, hover, focus-visible, active, disabled, loading, and error behavior where applicable.

### Buttons

- **Shape:** Gently curved rectangle (8px) with a 44px minimum height and 12px × 16px padding.
- **Primary:** Filing Green fill with Clear White text. Use for one dominant action within a local task area.
- **Hover / Focus:** Deep Filing Green on hover; visible Filing Green stroke plus the focus ring on keyboard focus; a subtle darkening on active. Disabled controls retain readable labels and lose action emphasis.
- **Secondary:** Clear White with a Fine Rule border and Quiet Ink text. It never receives a decorative shadow.

### Chips

- **Style:** Use only for filters or compact state labels. Pills are permitted here because the shape communicates compact taxonomy, not decoration.
- **State:** Selected chips use Quiet Selection and Deep Filing Green text. Status chips always include explicit text and, when useful, an icon.

### Cards / Containers

- **Corner Style:** Restrained 10px curves for working panels; 8px for compact rows.
- **Background:** Clear White over Crisp Canvas, or no container when spacing and dividers are sufficient.
- **Shadow Strategy:** Flat at rest. Overlay shadow is forbidden on static panels.
- **Border:** Fine Rule only when the boundary aids scanning.
- **Internal Padding:** 20px for standard panels and 14px for compact rows.

### Inputs / Fields

- **Style:** Clear White field, Fine Rule stroke, 8px curve, 44px minimum height, and Quiet Ink text. Placeholder text must remain WCAG AA legible.
- **Focus:** Filing Green stroke and the focus ring; never remove the native outline without an equal or stronger replacement.
- **Error / Disabled:** Blocking Red stroke plus a plain-language message placed next to the field. Disabled state remains readable and visibly non-interactive.

### Navigation

Persistent product navigation uses 13px bold labels and familiar placement. Default items use Ledger Grey, hover uses Quiet Ink, and active items use Quiet Selection with Deep Filing Green text. On narrow screens, navigation collapses structurally into a labeled menu or bottom-level pattern; it never becomes an unlabeled icon rail.

### Readiness row

The signature workflow component shows obligation name, short explanation, explicit status, and the next action in one scannable row. Completed, warning, and blocked states combine text, iconography, and semantic color. Rows use dividers and spacing rather than nested cards.

## Do's and Don'ts

### Do:

- **Do** use Filing Green only for primary actions, active navigation, progress, focus, and positive readiness.
- **Do** organize annual reporting around an obvious current state, next action, and blocking issue.
- **Do** use familiar controls, Norwegian sentence case, and plain-language explanations for accounting terms.
- **Do** prefer lists, rows, dividers, and whitespace over repeated cards when the content belongs to one workflow.
- **Do** meet WCAG 2.2 AA with keyboard operation, visible focus, screen-reader semantics, sufficient contrast, non-color cues, and reduced-motion support.
- **Do** use 150–250ms state transitions with exponential ease-out and an instant or crossfade alternative for reduced motion.

### Don't:

- **Don't** visually imitate Fiken even though it is a business and category reference.
- **Don't** use generic AI-generated styling, decorative novelty, glassmorphism, gradient text, or ornamental gradients.
- **Don't** use warm cream, sand, paper, parchment, or beige as the application canvas.
- **Don't** create clutter or feature bloat by exposing payroll, invoicing, VAT, or other operating-company concepts in the default navigation.
- **Don't** use unexplained accounting jargon or filing flows that feel intimidating or bureaucratic.
- **Don't** repeat uppercase eyebrows, numbered section scaffolding, hero metrics, or identical card grids.
- **Don't** pair a 1px panel border with a soft shadow whose blur is 16px or more.
- **Don't** use card or input radii above 16px; reserve full pills for chips and compact taxonomy.
- **Don't** rely on color alone for readiness, warnings, errors, or completion.
