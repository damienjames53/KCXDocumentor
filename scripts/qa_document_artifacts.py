#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree
from zipfile import BadZipFile, ZipFile


REQUIRED_TERMS = [
    "Purpose",
    "Intended Audience",
    "Workflow Overview",
    "Step-by-Step Procedures",
    "Expected Results",
    "Troubleshooting",
    "Source Recording",
]

FORBIDDEN_PATTERNS = [
    (re.compile(r"\bsystem prompt\b", re.IGNORECASE), "Internal prompt terminology leaked."),
    (re.compile(r"\bdeveloper (?:message|instructions?)\b", re.IGNORECASE), "Internal developer instructions leaked."),
    (re.compile(r"\bchain[- ]of[- ]thought\b", re.IGNORECASE), "Internal reasoning terminology leaked."),
    (re.compile(r"\bAuthorization:\s*Bearer\b", re.IGNORECASE), "Authorization header leaked."),
    (re.compile(r"\bOPENAI_API_KEY\b", re.IGNORECASE), "Environment secret name leaked."),
    (re.compile(r"<environment_context>", re.IGNORECASE), "Agent environment metadata leaked."),
    (re.compile(r"\bprocedure_trace\.json\b.*\{", re.IGNORECASE | re.DOTALL), "Raw trace JSON appears to have leaked into the guide."),
    (re.compile(r"\bSmartReq\b", re.IGNORECASE), "Reference-project terminology leaked."),
    (re.compile(r"\bDamienDev\b", re.IGNORECASE), "Reference-project path/name leaked."),
]

STRICT_FORBIDDEN_PATTERNS = [
    (re.compile(r"\bPrototype narration segment\b", re.IGNORECASE), "Prototype placeholder narration leaked."),
    (re.compile(r"\bReplace this with local speech-to-text output\b", re.IGNORECASE), "Local STT placeholder leaked."),
    (re.compile(r"\bVisible UI text pending local OCR\b", re.IGNORECASE), "Local OCR placeholder leaked."),
    (re.compile(r"\bplaceholder-only\b", re.IGNORECASE), "Placeholder confidence text leaked."),
]


@dataclass
class ArtifactResult:
    path: str
    passed: bool
    missing_required_terms: list[str]
    forbidden_matches: list[str]
    warnings: list[str]
    reviewer_comment_count: int = 0
    body_clean: bool = True


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def extract_text_from_xml(xml_bytes: bytes) -> str:
    text_parts: list[str] = []
    try:
        root = ElementTree.fromstring(xml_bytes)
    except ElementTree.ParseError:
        return ""
    for node in root.iter():
        if node.text and node.tag.endswith("}t"):
            text_parts.append(node.text)
    return normalize(" ".join(text_parts))


def office_text_parts(path: Path) -> tuple[str, str]:
    body_parts: list[str] = []
    comment_parts: list[str] = []
    with ZipFile(path) as package:
        for name in package.namelist():
            if not name.endswith(".xml"):
                continue
            if name.startswith("word/comments") or name.startswith("word/people"):
                comment_text = extract_text_from_xml(package.read(name))
                if comment_text:
                    comment_parts.append(comment_text)
                continue
            if not (name.startswith("word/") or name.startswith("ppt/slides/")):
                continue
            body_text = extract_text_from_xml(package.read(name))
            if body_text:
                body_parts.append(body_text)
    return normalize(" ".join(body_parts)), normalize(" ".join(comment_parts))


def reviewer_comment_count(path: Path) -> int:
    with ZipFile(path) as package:
        if "word/comments.xml" not in package.namelist():
            return 0
        try:
            root = ElementTree.fromstring(package.read("word/comments.xml"))
        except ElementTree.ParseError:
            return 0
    return sum(1 for node in root.iter() if node.tag.endswith("}comment"))


def text_from_office(path: Path) -> str:
    body_text, comment_text = office_text_parts(path)
    return normalize(" ".join(part for part in [body_text, comment_text] if part))


def check_artifact(path: Path, strict: bool = False) -> ArtifactResult:
    missing: list[str] = []
    forbidden: list[str] = []
    warnings: list[str] = []

    if not path.exists():
        return ArtifactResult(str(path), False, ["file exists"], [], [])

    try:
        body_text, comment_text = office_text_parts(path)
        comment_count = reviewer_comment_count(path)
    except BadZipFile:
        return ArtifactResult(str(path), False, [], [f"{path.name} is not a readable Office Open XML file"], [])

    lowered = body_text.lower()
    for term in REQUIRED_TERMS:
        if term.lower() not in lowered:
            missing.append(term)

    body_forbidden: list[str] = []
    all_text = normalize(" ".join(part for part in [body_text, comment_text] if part))
    for pattern, reason in FORBIDDEN_PATTERNS:
        match = pattern.search(all_text)
        if match:
            forbidden.append(f"{reason} Matched `{match.group(0)[:80]}`.")
        body_match = pattern.search(body_text)
        if body_match:
            body_forbidden.append(f"{reason} Matched `{body_match.group(0)[:80]}`.")

    if strict:
        for pattern, reason in STRICT_FORBIDDEN_PATTERNS:
            match = pattern.search(body_text)
            if match:
                forbidden.append(f"{reason} Matched `{match.group(0)[:80]}`.")
                body_forbidden.append(f"{reason} Matched `{match.group(0)[:80]}`.")

    if "keycentrix" not in lowered:
        warnings.append("Document does not include visible keycentrix company text.")

    if "screenshot" not in lowered and "screen" not in lowered:
        warnings.append("Document does not appear to reference screenshots or screen states.")
    if comment_text:
        warnings.append("Document includes reviewer comments that should be resolved before customer release.")

    return ArtifactResult(
        path=str(path),
        passed=not missing and not forbidden,
        missing_required_terms=missing,
        forbidden_matches=forbidden,
        warnings=warnings,
        reviewer_comment_count=comment_count,
        body_clean=not body_forbidden,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Scan generated KCXDocumentor Office artifacts for required guide sections and leakage.")
    parser.add_argument("artifacts", nargs="+", type=Path, help="DOCX/PPTX artifacts to scan.")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    parser.add_argument("--strict", action="store_true", help="Also fail on prototype placeholder text that is acceptable only in local demos.")
    args = parser.parse_args()

    results = [check_artifact(path, strict=args.strict) for path in args.artifacts]
    passed = all(result.passed for result in results)

    if args.json:
        print(json.dumps({"passed": passed, "artifacts": [result.__dict__ for result in results]}, indent=2))
    else:
        print("KCXDocumentor artifact QA")
        for result in results:
            status = "PASS" if result.passed else "FAIL"
            print(f"\n[{status}] {result.path}")
            for term in result.missing_required_terms:
                print(f"  missing required text: {term}")
            for match in result.forbidden_matches:
                print(f"  forbidden/stale text: {match}")
            for warning in result.warnings:
                print(f"  warning: {warning}")
        print(f"\nResult: {'PASS' if passed else 'FAIL'}")

    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
