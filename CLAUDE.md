# CLAUDE.md

Automated Virginia legal name-change filing. Flask app under
`va_name_change/web/`, document generation and filing logic in the package, plus
an orchestrator (`orchestrator.py`) driving a self-healing codegen loop.

## Design

Stack: Flask with Jinja templates under `va_name_change/web/templates/`. Styles
live in a `<style>` block in `base.html`. No framework, no build step, no UI
library.

### Tokens (from templates/base.html)
- Page background `#f0f2f5`, cards white with `0 1px 3px rgba(0,0,0,0.1)`, radius 8px
- Text `#1a1a2e`, headings `#16213e`, secondary `#555`
- Nav bar `#16213e` with `#e2e8f0` links
- Primary button `#2563eb`, hover `#1d4ed8`. Secondary `#64748b`. Success `#16a34a`.
- Inputs: 1px `#cbd5e1`, radius 6px, focus ring `rgba(59,130,246,0.15)`
- System font stack, 1.6 line height, container `max-width: 780px`

### Layout
- `base.html` owns nav and container. Every page extends it.
- `.card` is the primary container, one concern per card
- Intake is a numbered wizard: `intake/step1_identity` through `step4_confirm`
- Post-intake screens: `documents`, `filing`, `status`, `post_decree`

### Rules
- This is a legal filing for a real person under stress. Plain language, no jargon,
  no cleverness. Say what the form is for and what happens after they submit it.
- Never imply legal advice. Never guess at a value that goes on a court document.
- Every wizard step is resumable and shows where the user is in the sequence.
- Anything generated or prefilled is visibly marked and editable before filing.
- Every screen ships loading, empty, and error states.
- Reading level matters more than density. Keep the 780px measure.

## Runtime model routing

- Runtime uses only **Haiku, Sonnet, or Opus**. **Fable is never called at
  runtime.** It is a build-time tool in Claude Code only.
- No model id is hardcoded at a call site. Resolve it from one config value.
- Every call declares its tier, a max token budget, and what happens on failure.
- High-volume paths (per request, per row, per frame) never default to Opus.

`orchestrator.py` currently calls OpenAI `gpt-4` directly with the id inline.
That predates this policy. It is flagged in the fleet routing audit and needs a
deliberate decision before anyone changes it.
