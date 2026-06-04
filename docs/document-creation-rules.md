# Document Creation Rules

These rules are based on the DamienDev keycentrix document recipe and copied local assets.

## Source Assets

Local document builds must use assets from this repository:

- `assets/branding/images/keycentrix-template-logo.png`
- `assets/branding/images/keycentrix-full-logo.png`
- `assets/branding/images/keycentrix-logo-from-template.png`
- `assets/branding/images/sticky-logo.png`
- `tools/document_lib/keycentrix_docx.py`

The reference project `/Users/djames/Documents/DamienDev` must not be modified and should not be required after this experiment is populated.

## Brand Rules

- Visible company-name text must be `keycentrix` in all lowercase unless preserving an exact source quote or file path.
- Use the copied keycentrix visual assets as the baseline.
- Do not call the artifact `branded` unless the document is explicitly about brand work.
- Use the established palette when no template config is present:
  - blue `#1C75BC`
  - green `#8CC63F`
  - dark text `#1F2937`
  - muted gray `#6B7280`
  - light blue fill `#EAF3FB`
  - light gray fill `#F3F4F6`
- Use Calibri as the default Word-compatible fallback.

## User Guide Structure

Generated application user guides should use this structure unless a source package specifies otherwise:

1. Title
2. Purpose statement
3. Version, status, owner, and effective date
4. Intended audience
5. Prerequisites
6. Workflow overview
7. Step-by-step procedures
8. Expected results
9. Troubleshooting notes
10. Appendix with source recording metadata and review notes

## Screenshot Rules

- Include screenshots only when they clarify an action, field, menu, confirmation, or result.
- Prefer stills that align with explicit speaker intent.
- Avoid transition frames, loading states, blurred frames, and duplicate screens.
- Caption screenshots with the related step and the visible UI state.
- Do not include sensitive values visible in the source recording unless they have been approved or redacted.

## Packaging Pattern

Each generated guide package should contain:

1. Final DOCX.
2. Editable guide draft JSON or Markdown.
3. `procedure_trace.json`.
4. Selected screenshot assets.
5. Rendered QA artifacts when available.
6. `README.md` with source recording metadata, assumptions, open review questions, and QA status.

