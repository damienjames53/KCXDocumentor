# KCXDocumentor Copilot Instructions

## Read-Only Reference Projects

This project may use the following repositories as reference material only:

- `/Users/djames/Documents/DamienDev`
- `/Users/djames/Documents/AppDev/SmartReq`
- `/Users/djames/Documents/AppDev/KCXUIComponents`

Do not modify, reformat, delete, move, commit, or generate files inside any reference project while working on KCXDocumentor.

If useful patterns, assets, scripts, or documentation are needed from those projects, copy the required material into this repository first and adapt only the local copy.

Treat DamienDev, SmartReq, and KCXUIComponents as removable external references. KCXDocumentor should not depend on their paths at runtime or during normal local builds.

## UI Standard

Use KCXUIComponents as the read-only UI reference for current KCX product styling. New KCXDocumentor UI should follow the KCXUIComponents approach:

- Token-driven CSS using semantic `--kcx-ui-*` variables.
- Shared primitive concepts such as panels, buttons, status badges, top/app shell, layout grids, and form fields.
- No tenant-specific component forks or custom CSS injection.
- Copy any needed style patterns locally before adapting them.

## Azure Function Deployment

Deploy Azure Function code through the configured GitHub Actions workflow only.

- Do not use local zip deploy, Kudu zip deploy, publish profiles, or ad hoc `func azure functionapp publish` commands for `kcxdocumentor-ai-dev`.
- Function code changes should be committed and pushed so `.github/workflows/deploy-azure-function.yml` performs the deployment.
- Azure portal or CLI updates are acceptable for runtime app settings, secrets, provider endpoints, and resource configuration when explicitly needed.
- Keep provider keys server-side in the Function App settings; never place AI provider keys in local app configuration, browser code, committed files, or workstation setup docs.
