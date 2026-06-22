# ADR-002: Qualification confidence threshold

## Status

Accepted

## Decision

Use `0.75` as the minimum qualification confidence threshold via the shared
setting `QUALIFICATION_CONFIDENCE_THRESHOLD`.

## Context

Lead qualification extracts structured customer answers from WhatsApp (and later
voice) conversations. Each extracted field includes a model-reported confidence
score between `0` and `1`.

## Why

Values below `0.75` must not be treated as reliable customer answers. A lower
threshold would accept ambiguous or weak extractions as confirmed data, which
risks incorrect lead records and poor downstream booking decisions.

## Scope

- **Now:** WhatsApp qualification flow reads the shared threshold from Django
  settings through `get_qualification_confidence_threshold()`.
- **Later:** Voice qualification can adopt the same shared rule without
  duplicating configuration.

## Out of scope (this task)

This ADR and T3.2 only define the configuration value and accessor. Field
rejection logic based on the threshold belongs to T3.4.

## Configuration

- Environment variable: `QUALIFICATION_CONFIDENCE_THRESHOLD`
- Default: `0.75`
- Valid range: `(0, 1]` (greater than `0`, less than or equal to `1`)
