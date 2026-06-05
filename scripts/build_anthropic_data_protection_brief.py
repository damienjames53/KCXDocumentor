#!/usr/bin/env python3
from __future__ import annotations

from datetime import date
from pathlib import Path

from docx import Document

from build_prototype_collateral_docx import (
    DocSpec,
    OUT_DIR,
    _bullets,
    _callout,
    _cover,
    _header_footer,
    _style_document,
    _table,
)


OUTPUT = OUT_DIR / "KCXDocumentor - Anthropic API Data Protection Brief.docx"


def add_doc_control(doc: Document, spec: DocSpec) -> None:
    doc.add_heading("Document Control", level=1)
    _table(
        doc,
        ["Control", "Value"],
        [
            ["Document Title", spec.title],
            ["Document ID", spec.document_id],
            ["Status", spec.status],
            ["Owner", spec.owner],
            ["Audience", spec.audience],
            ["Review Basis", "Anthropic public documentation reviewed on 2026-06-05"],
        ],
    )
    doc.add_heading("Version History", level=1)
    _table(
        doc,
        ["Version", "Date", "Summary"],
        [["1.0", date.today().isoformat(), "Initial executive data protection and BAA readiness brief."]],
    )


def build() -> Path:
    spec = DocSpec(
        title="KCXDocumentor - Anthropic API Data Protection Brief",
        subtitle="Executive review of API data use, PHI/PII exposure, and BAA readiness",
        document_id="KCXDOC-DATA-001",
        status="Executive review",
        owner="keycentrix Engineering and Product",
        audience="Executive Team, Security, Compliance, Product, Training, Implementation, and Engineering",
        purpose="Summarize Anthropic API data-use protections and the additional requirements needed before KCXDocumentor is used with protected health information or sensitive personal information.",
        scope="Focused on KCXDocumentor use of Anthropic's first-party API for guide generation. This brief does not evaluate Claude consumer products, Claude Team plans, partner-hosted model platforms, or third-party integrations.",
        sections=[],
        output_name=OUTPUT.name,
    )

    doc = Document()
    doc.core_properties.title = spec.title
    doc.core_properties.author = "keycentrix"
    doc.core_properties.subject = spec.subtitle
    doc.core_properties.comments = "Executive compliance brief built with the DamienDev document recipe pattern."
    _style_document(doc)
    _header_footer(doc, spec.title)
    _cover(doc, spec)
    add_doc_control(doc, spec)

    doc.add_heading("Purpose", level=1)
    doc.add_paragraph(spec.purpose)
    doc.add_heading("Scope", level=1)
    doc.add_paragraph(spec.scope)
    doc.add_heading("Intended Audience", level=1)
    doc.add_paragraph(spec.audience)

    doc.add_heading("Executive Summary", level=1)
    _callout(
        doc,
        "Recommended executive position",
        "KCXDocumentor should continue using the local-first architecture, but production use with PHI should wait until Anthropic HIPAA-ready API access is enabled under a signed BAA and the application enforces PHI-aware controls.",
    )
    _bullets(
        doc,
        [
            "Anthropic's Commercial Terms state that customer inputs and outputs remain customer content and are not used to train Anthropic models.",
            "Anthropic's published standard API retention says API inputs and outputs are automatically deleted within 30 days, subject to exceptions for law, usage-policy enforcement, certain longer-retention features, or agreed alternatives.",
            "Anthropic offers zero data retention arrangements for eligible enterprise API customers and HIPAA-ready API access with a signed Business Associate Agreement.",
            "For KCXDocumentor, raw recordings stay local, but transcript excerpts, OCR text, reviewer notes, approved screenshot context, and generated guide content can still contain PHI or PII if the source recording contains it.",
            "Until BAA coverage and HIPAA-ready API organization controls are active, the safest operating rule is to avoid sending PHI to Anthropic and to use de-identified or internal-only test data.",
        ],
    )

    doc.add_heading("KCXDocumentor Data Flow Considerations", level=1)
    _table(
        doc,
        ["Data Element", "Current Handling", "Executive Risk View"],
        [
            ["Raw video recording", "Processed locally on the workstation.", "Lowest vendor exposure if raw video is never sent to Anthropic."],
            ["Speech transcript", "Used to create compact guide context.", "Can contain PHI/PII if a recording includes patient names, prescription details, identifiers, or support context."],
            ["OCR and screen text", "Extracted locally and summarized into the trace.", "Can expose patient, pharmacy, employee, account, or workflow-sensitive details."],
            ["Reviewer notes", "Used to steer guide generation.", "Can introduce PHI/PII if reviewers type identifiers or case details."],
            ["Approved screenshots", "May be included or represented in the guide-generation context.", "Image content can include PHI/PII if screens are not masked or reviewed."],
            ["Generated guide output", "Returned by Anthropic and stored locally.", "May restate sensitive content unless prompts and QA rules prevent it."],
        ],
    )

    doc.add_heading("Published Anthropic Protections Relevant To API Use", level=1)
    _table(
        doc,
        ["Protection", "Published Position", "Meaning For KCXDocumentor"],
        [
            ["Model training", "Anthropic's Commercial Terms state that Anthropic may not train models on customer content from Services.", "This supports use of the API for confidential documentation workflows, subject to contract and data-handling review."],
            ["Customer ownership", "Customer retains inputs and owns outputs under the Commercial Terms, to the extent permitted by law.", "Generated guides should remain keycentrix/customer-controlled deliverables."],
            ["Standard retention", "API inputs and outputs are deleted within 30 days by default, with stated exceptions.", "Default API use is not zero retention and should not be treated as sufficient for PHI without a covered arrangement."],
            ["Policy enforcement retention", "Flagged inputs and outputs may be retained longer for usage-policy enforcement; classifier scores may be retained longer.", "Sensitive data should be minimized even when using the standard API because exception paths exist."],
            ["Zero data retention", "Eligible enterprise API customers may have arrangements where inputs and outputs are not stored at rest after the response, except for law or misuse needs.", "ZDR is a strong control for regulated or sensitive workloads but requires Anthropic approval and contract confirmation."],
            ["HIPAA-ready API", "Anthropic supports HIPAA-ready API integrations with a signed BAA and a HIPAA-enabled organization.", "Production PHI use should be routed through the HIPAA-ready organization, not a general API organization."],
        ],
    )

    doc.add_heading("BAA And HIPAA-Ready Requirements", level=1)
    _table(
        doc,
        ["Requirement", "What Anthropic Publishes", "KCXDocumentor Action"],
        [
            ["Signed BAA", "To use the first-party API with PHI, the organization administrator must sign a BAA and contact sales to enable it.", "Begin Anthropic sales/BAA process before allowing PHI-bearing recordings."],
            ["HIPAA-enabled organization", "Anthropic provisions a dedicated organization with HIPAA readiness controls and feature restrictions.", "Use a separate Anthropic organization/API key for HIPAA-ready KCXDocumentor generation."],
            ["Eligible features only", "HIPAA-enabled organizations block non-eligible features; not all API features are covered.", "Keep guide generation on covered Messages API behavior and avoid unsupported features."],
            ["No Console or Workbench use", "Console and Workbench are not covered under the BAA for this API use case.", "Do not paste KCXDocumentor prompt payloads containing PHI into Console, Workbench, or consumer Claude surfaces."],
            ["Third-party integrations", "External tools and third-party data flows are not covered by Anthropic's BAA.", "Keep the Azure Function proxy limited to Anthropic API calls and avoid web search, external MCPs, or third-party tools for PHI content."],
            ["Feature limitations", "Batch API, Files API, Skills API, Code Execution, Computer Use, and Web Fetch are not covered for HIPAA-ready API users per Anthropic's BAA coverage table.", "Do not use these features for PHI workflows unless Anthropic contract terms later explicitly cover them."],
            ["Schema restrictions", "Anthropic warns not to place PHI in JSON schema definitions, enum values, constants, or patterns because those cached schemas do not receive the same PHI protections as message content.", "Ensure KCXDocumentor schemas and tool definitions are generic and never patient- or transaction-specific."],
        ],
    )

    doc.add_heading("Recommended Product Controls Before PHI Use", level=1)
    _bullets(
        doc,
        [
            "Create a PHI mode that blocks guide generation unless the configured API endpoint is tied to a HIPAA-ready Anthropic organization under a signed BAA.",
            "Add a preflight warning that identifies transcript, OCR, reviewer notes, and approved screenshots as possible PHI/PII transmission points.",
            "Add redaction or masking options for patient names, dates of birth, prescription identifiers, phone numbers, addresses, email addresses, MRNs, and account numbers before prompt assembly.",
            "Maintain the current backend proxy pattern so API keys are never exposed in browser JavaScript.",
            "Keep raw recordings, extracted frames, and generated files in mapped local folders with workstation access controls.",
            "Log only operational metadata needed for audit and cost reporting; avoid storing PHI in cloud usage records, file names, session names, or telemetry.",
            "Disable or block unsupported Anthropic features for KCXDocumentor PHI workflows, including Files API, batch processing, web fetch, external tools, and non-covered beta features.",
            "Document a user-facing rule: recordings used for customer-facing guide generation should be de-identified unless the HIPAA-ready/BAA path is active.",
        ],
    )

    doc.add_heading("Decision Matrix", level=1)
    _table(
        doc,
        ["Operating Scenario", "Allowed For Demo?", "Allowed For PHI?", "Recommended Control"],
        [
            ["Internal demo with synthetic or de-identified data", "Yes", "No PHI present", "Use current API path with local-first controls and reviewer QA."],
            ["Internal workflow recording with possible PII but no PHI", "Conditional", "Not applicable", "Minimize, redact, and confirm business approval before API generation."],
            ["Recording that may show PHI", "No, unless de-identified", "Not under standard API path", "Require signed BAA, HIPAA-ready API organization, and PHI mode controls."],
            ["Production customer-facing documentation from real pharmacy workflows", "Conditional", "Only with covered controls", "Use HIPAA-ready API access or ensure complete de-identification before generation."],
        ],
    )

    doc.add_heading("Executive Decision Points", level=1)
    _bullets(
        doc,
        [
            "Decide whether KCXDocumentor will be permitted to process PHI-bearing recordings, or whether all pilot recordings must be de-identified.",
            "If PHI use is expected, start the Anthropic BAA and HIPAA-ready API enablement process before expanding the pilot.",
            "Assign Security/Compliance review of KCXDocumentor's prompt payload, logging, storage, and UI warnings.",
            "Define whether ZDR is required as an additional contractual control even though Anthropic now documents HIPAA-ready API access separately from ZDR.",
            "Approve product work for PHI mode, redaction checks, and unsupported-feature blocking before regulated production use.",
        ],
    )

    doc.add_heading("Source References", level=1)
    _table(
        doc,
        ["Source", "Reviewed Topic"],
        [
            ["Anthropic Commercial Terms of Service, effective June 17, 2025", "Customer content ownership, no model training on customer content, data processing and confidentiality obligations."],
            ["Anthropic API and Data Retention documentation", "Standard retention, zero data retention, HIPAA readiness, PHI handling guidelines, unsupported features, and backend proxy guidance."],
            ["Anthropic Privacy Center: How long do you store my organization's data?", "30-day API retention, usage-policy exception retention, feedback retention, and legal exceptions."],
            ["Anthropic Privacy Center: Zero data retention agreement scope", "ZDR scope, covered products, and limitations."],
            ["Claude Help Center: Business Associate Agreements for Commercial Customers", "BAA availability, required activation, covered and excluded product surfaces, and API feature coverage."],
        ],
    )

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    doc.save(OUTPUT)
    return OUTPUT


def main() -> int:
    output = build()
    print(f"Built {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
