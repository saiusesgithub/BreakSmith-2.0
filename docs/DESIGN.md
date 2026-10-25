# BreakSmith design language

The interface starts with a cinematic narrative and resolves into an operational console. The opening sequence invites exploration; the console earns trust by showing only backend events, scanner matches, model responses, and proposed replacements that actually exist.

## Visual system

| Role | Color | Use |
| --- | --- | --- |
| Canvas | `#0a0a0c` | The fixed night-sky backdrop and main page surface |
| Foreground | `#f4f2ef` | Headlines and high-priority text |
| Signal pink | `#f5b8d0` | Active timeline dots, focus, key labels, and model cues |
| Deep rose | `#c26a97` | Secondary glows and orbital gradients |
| Muted text | `#9c988f` | Supporting copy |
| Evidence green | `#9edfb4` | Proposed replacement and successful state |
| Risk coral | `#f0786c` | High-severity finding markers and errors |

The landing sections retain the supplied HTML's large typography, translucent surfaces, photographic figure, and pink orbital particles. The scan console uses the same black and rose palette, restrained borders, and compact monospace labels so the live data feels like part of the scene.

## Type and icons

- **Cinematic copy:** the supplied page's sans-serif type, large tracking-tight headings, and small uppercase labels.
- **Operations UI:** DM Sans for readable text and IBM Plex Mono for state, file paths, metrics, and logs.
- **Landing icons:** Iconify icons in the original template.
- **Console icons:** Lucide React icons, used to distinguish source, scanner, model, remediation, and status.
- **Brand mark:** [`assets/logo.svg`](assets/logo.svg), a shield and orbital motif drawn in the same pink palette.

Icons are supporting cues. Severity, stage, and AI status also appear as text, so color and shape are never the only source of meaning.

## Motion

| Moment | Implementation | Purpose |
| --- | --- | --- |
| Opening sequence | Scroll-driven beat windows and a sticky stage | Walk through source, detection, analysis, and review |
| Orbital background | Three.js point cloud shader | Keep the supplied cinematic background |
| Petal layer | Canvas 2D | Add depth while scrolling |
| Section reveals | GSAP and ScrollTrigger | Reveal cards and headlines at the same visual rhythm as the supplied HTML |
| Agent cards | Pointer tilt and depth transforms | Keep the original tactile interaction |

The page checks `prefers-reduced-motion` and limits or skips the most animated effects. The opening title is visible at the top of the page, and the timeline contains one dot per story beat.

## Assets and implementation

The five images from the supplied page live in [`frontend/public/template-assets`](../frontend/public/template-assets). The original Tailwind browser runtime, Iconify component, GSAP, and ScrollTrigger scripts live in [`frontend/public/vendor`](../frontend/public/vendor); Three.js is an npm dependency bundled by Vite. This keeps the visual experience available when the original asset host and CDNs are unavailable.

The interactive console lives in [`frontend/src/App.tsx`](../frontend/src/App.tsx), with console-specific styling in [`frontend/src/styles.css`](../frontend/src/styles.css). Its content comes from the FastAPI scan endpoints. Decorative copy explains the workflow; counts, events, findings, model analysis, and suggested code are populated from the backend.

## UI principles

1. **Evidence before confidence.** A scanner match includes a rule, file, line, and source context.
2. **Visible provenance.** Model analysis appears only after a local model response has been parsed.
3. **Human review.** Suggested replacements are displayed beside the original; the app does not apply them.
4. **Honest empty states.** Zero matches means the included rules found no patterns, not that the repository is secure.
5. **Readable errors.** Dependency and job failures remain visible in the console instead of being hidden by the cinematic presentation.
