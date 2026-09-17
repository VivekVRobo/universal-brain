# Alignment Contract Schema

The Alignment Contract is the canonical bridge between natural-language intent and executable work.

## Required fields

    contract_id: uuid
    version: integer
    status: draft | clarification_required | active | superseded | closed
    created_at: timestamp
    authority_event_id: uuid

    original_inputs:
      - input_id: uuid
        exact_content_ref: immutable_reference
        received_at: timestamp

    objective:
      statement: string
      rationale: [string]
      priority: integer

    requirements:
      - requirement_id: string
        statement: string
        source_input_ids: [uuid]
        kind: functional | quality | safety | privacy | permission | evidence
        priority: must | should | may
        verification_method: string

    constraints:
      - constraint_id: string
        statement: string
        authority: explicit_user | constitution | policy | derived
        source_refs: [string]

    non_goals:
      - statement: string
        source_refs: [string]

    assumptions:
      - assumption_id: string
        statement: string
        impact: low | medium | high
        confidence_basis: string
        confirmed: boolean
        rollback_path: string

    ambiguities:
      - ambiguity_id: string
        question: string
        impact: low | medium | high
        affected_refs: [string]
        resolution_status: open | assumed | answered

    permissions:
      action_ceiling: A0 | A1 | A2
      allowed_capabilities: [string]
      denied_capabilities: [string]
      expires_at: timestamp | null

    acceptance_criteria:
      - criterion_id: string
        statement: string
        evidence_type: string
        verifier: deterministic | independent_model | operator | mixed

    commitments:
      - commitment_id: string
        statement: string
        source_refs: [string]

    change_log:
      - version: integer
        reason: string
        authority_event_id: uuid
        semantic_diff_ref: string

## Transition rules

- draft → active requires no unresolved high-impact ambiguity and at least one acceptance criterion.
- A contract containing A1 work requires explicit rollback and evidence requirements.
- A correction creates a new version; historical versions are never overwritten.
- A task binds to one contract version and must revalidate before execution.
- Closing a contract requires a verification report or an explicit cancellation event.

