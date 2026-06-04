# KCXDocumentor Copilot Instructions

## Read-Only Reference Projects

This project may use the following repositories as reference material only:

- `/Users/djames/Documents/DamienDev`
- `/Users/djames/Documents/AppDev/SmartReq`
- `/Users/djames/Documents/AppDev/CustomerAppUI`

Do not modify, reformat, delete, move, commit, or generate files inside either reference project while working on KCXDocumentor.

If useful patterns, assets, scripts, or documentation are needed from those projects, copy the required material into this repository first and adapt only the local copy.

Treat DamienDev, SmartReq, and CustomerAppUI as removable external references. KCXDocumentor should not depend on their paths at runtime or during normal local builds.

## UI Standard

Use CustomerAppUI as the read-only UI reference for current KCX product styling. New KCXDocumentor UI should follow the CustomerAppUI approach:

- Token-driven CSS using semantic `--kcx-ui-*` variables.
- Shared primitive concepts such as panels, buttons, status badges, top/app shell, layout grids, and form fields.
- No tenant-specific component forks or custom CSS injection.
- Copy any needed style patterns locally before adapting them.
