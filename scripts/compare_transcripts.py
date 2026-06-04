#!/usr/bin/env python3
"""Compare two KCXDocumentor transcript.json artifacts."""

from __future__ import annotations

import argparse
import json
import re
import sys
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any


WORD_RE = re.compile(r"[a-z0-9']+")


def main() -> int:
    args = parse_args()
    reference = read_transcript(args.reference)
    candidate = read_transcript(args.candidate)
    report = compare_transcripts(reference, candidate, args.examples)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare two transcript.json files.")
    parser.add_argument("reference", type=Path, help="Reference transcript.json, usually the Teams VTT sidecar session.")
    parser.add_argument("candidate", type=Path, help="Candidate transcript.json, usually the local Whisper session.")
    parser.add_argument("--examples", type=int, default=5, help="Number of low-similarity aligned examples to include.")
    parser.add_argument("--output", type=Path, help="Optional JSON report output path.")
    return parser.parse_args()


def read_transcript(path: Path) -> dict[str, Any]:
    if not path.exists() or not path.is_file():
        raise SystemExit(f"transcript does not exist or is not a file: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def compare_transcripts(reference: dict[str, Any], candidate: dict[str, Any], example_count: int = 5) -> dict[str, Any]:
    reference_segments = normalized_segments(reference)
    candidate_segments = normalized_segments(candidate)
    reference_text = " ".join(segment["text"] for segment in reference_segments)
    candidate_text = " ".join(segment["text"] for segment in candidate_segments)
    reference_words = tokenize(reference_text)
    candidate_words = tokenize(candidate_text)
    aligned = align_segments(reference_segments, candidate_segments)
    return {
        "schemaVersion": 1,
        "reference": summarize_transcript(reference, reference_segments, reference_words),
        "candidate": summarize_transcript(candidate, candidate_segments, candidate_words),
        "comparison": {
            "wordErrorRateApprox": round(word_error_rate(reference_words, candidate_words), 4),
            "wordOverlap": round(word_overlap(reference_words, candidate_words), 4),
            "wordSequenceSimilarity": round(SequenceMatcher(None, reference_words, candidate_words).ratio(), 4),
            "alignedSegmentCount": len(aligned),
            "averageAlignedSimilarity": round(
                sum(item["similarity"] for item in aligned) / len(aligned),
                4,
            )
            if aligned
            else 0.0,
        },
        "examples": lowest_similarity_examples(aligned, example_count),
    }


def normalized_segments(transcript: dict[str, Any]) -> list[dict[str, Any]]:
    segments = transcript.get("segments") if isinstance(transcript.get("segments"), list) else []
    normalized = []
    for index, segment in enumerate(segments):
        if not isinstance(segment, dict):
            continue
        text = " ".join(str(segment.get("text", "")).split())
        normalized.append(
            {
                "id": segment.get("id") or f"segment-{index + 1:04d}",
                "startSeconds": parse_float(segment.get("startSeconds")) or 0.0,
                "endSeconds": parse_float(segment.get("endSeconds")) or parse_float(segment.get("startSeconds")) or 0.0,
                "confidence": parse_float(segment.get("confidence")),
                "text": text,
            }
        )
    return normalized


def summarize_transcript(transcript: dict[str, Any], segments: list[dict[str, Any]], words: list[str]) -> dict[str, Any]:
    confidences = [segment["confidence"] for segment in segments if segment["confidence"] is not None]
    non_empty = [segment for segment in segments if segment["text"]]
    return {
        "source": transcript.get("source"),
        "sourceTranscript": transcript.get("sourceTranscript"),
        "durationSeconds": transcript.get("durationSeconds"),
        "segmentCount": len(segments),
        "nonEmptySegmentCount": len(non_empty),
        "wordCount": len(words),
        "averageConfidence": round(sum(confidences) / len(confidences), 4) if confidences else None,
        "lowConfidenceSegmentCount": sum(1 for value in confidences if value < 0.7),
    }


def align_segments(reference: list[dict[str, Any]], candidate: list[dict[str, Any]]) -> list[dict[str, Any]]:
    aligned = []
    for ref in reference:
        midpoint = (ref["startSeconds"] + ref["endSeconds"]) / 2
        match = best_time_match(midpoint, candidate)
        if not match:
            continue
        reference_words = tokenize(ref["text"])
        candidate_words = tokenize(match["text"])
        similarity = word_overlap(reference_words, candidate_words)
        aligned.append(
            {
                "referenceId": ref["id"],
                "candidateId": match["id"],
                "startSeconds": ref["startSeconds"],
                "endSeconds": ref["endSeconds"],
                "similarity": round(similarity, 4),
                "wordSequenceSimilarity": round(SequenceMatcher(None, reference_words, candidate_words).ratio(), 4),
                "referenceText": ref["text"],
                "candidateText": match["text"],
            }
        )
    return aligned


def best_time_match(midpoint: float, candidates: list[dict[str, Any]]) -> dict[str, Any] | None:
    containing = [
        segment
        for segment in candidates
        if segment["startSeconds"] <= midpoint <= max(segment["endSeconds"], segment["startSeconds"])
    ]
    if containing:
        return min(containing, key=lambda item: abs(midpoint - ((item["startSeconds"] + item["endSeconds"]) / 2)))
    if not candidates:
        return None
    return min(candidates, key=lambda item: abs(midpoint - ((item["startSeconds"] + item["endSeconds"]) / 2)))


def lowest_similarity_examples(aligned: list[dict[str, Any]], count: int) -> list[dict[str, Any]]:
    candidates = [item for item in aligned if item["referenceText"] or item["candidateText"]]
    return sorted(candidates, key=lambda item: item["similarity"])[: max(0, count)]


def tokenize(text: str) -> list[str]:
    return WORD_RE.findall(text.lower())


def word_overlap(reference: list[str], candidate: list[str]) -> float:
    if not reference and not candidate:
        return 1.0
    reference_set = set(reference)
    candidate_set = set(candidate)
    union = reference_set | candidate_set
    if not union:
        return 0.0
    return len(reference_set & candidate_set) / len(union)


def word_error_rate(reference: list[str], candidate: list[str]) -> float:
    if not reference:
        return 0.0 if not candidate else 1.0
    return levenshtein_distance(reference, candidate) / len(reference)


def levenshtein_distance(left: list[str], right: list[str]) -> int:
    previous = list(range(len(right) + 1))
    for left_index, left_word in enumerate(left, start=1):
        current = [left_index]
        for right_index, right_word in enumerate(right, start=1):
            current.append(
                min(
                    previous[right_index] + 1,
                    current[right_index - 1] + 1,
                    previous[right_index - 1] + (0 if left_word == right_word else 1),
                )
            )
        previous = current
    return previous[-1]


def parse_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


if __name__ == "__main__":
    sys.exit(main())
