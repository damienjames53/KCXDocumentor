# GitHub Actions Deployment

KCXDocumentor deploys the Azure Function proxy from GitHub Actions using OpenID Connect.

## Why OIDC

Microsoft and the Azure Functions action currently recommend OIDC for GitHub Actions deployments. OIDC uses short-lived tokens and avoids storing publish profiles or service-principal secrets in GitHub.

The workflow is:

```text
.github/workflows/deploy-azure-function.yml
```

It deploys only:

```text
azure-functions/kcxdocumentor-ai
```

## Azure Identity

Use a user-assigned managed identity with `Website Contributor` scoped to the Function App:

```text
Function App: kcxdocumentor-ai-dev
Resource Group: rg-kcxdocumentor-dev
Subscription: kcx-newleaf-001
```

The identity must have a federated credential for:

```text
repo:<owner>/<repo>:ref:refs/heads/main
```

## GitHub Variables

The workflow expects repository variables:

```text
AZURE_CLIENT_ID
AZURE_TENANT_ID
AZURE_SUBSCRIPTION_ID
```

These are identifiers, not secrets. No publish profile should be stored for this workflow.

## Deployment Shape

The workflow:

1. Checks out the repo.
2. Installs Node 22.
3. Runs `npm ci --omit=dev` in `azure-functions/kcxdocumentor-ai`.
4. Runs the Function syntax check.
5. Logs into Azure with OIDC.
6. Deploys the Function App using `Azure/functions-action@v1`.

This avoids remote Kudu builds and keeps deployment scoped to the Function source folder.
