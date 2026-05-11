-- Seed: prompt_templates — extraction and summarization prompts
-- Idempotent: ON CONFLICT DO NOTHING on (name, version)

INSERT INTO prompt_templates (name, version, capability, template_text, output_schema, is_active)
VALUES
    -- Relation extraction prompt
    ('relation_extraction', 1, 'EXTRACTION',
     E'You are a financial relation extraction system.\n\nGiven the following text from a financial document, extract all relations between entities.\n\nFor each relation, provide:\n- subject: the entity performing the action or holding the relationship\n- object: the entity being acted upon or related to\n- relation_type: one of the canonical relation types\n- polarity: positive, negative, or neutral\n- confidence: your confidence score between 0.0 and 1.0\n- evidence_text: the exact text span supporting this relation\n\nText:\n{{ text }}\n\nEntities found:\n{{ entities }}\n\nExtract all relations as a JSON array.',
     '{"type": "array", "items": {"type": "object", "properties": {"subject": {"type": "string"}, "object": {"type": "string"}, "relation_type": {"type": "string"}, "polarity": {"type": "string", "enum": ["positive", "negative", "neutral"]}, "confidence": {"type": "number"}, "evidence_text": {"type": "string"}}, "required": ["subject", "object", "relation_type", "confidence"]}}'::jsonb,
     true),

    -- Relation summarization prompt
    ('relation_summarization', 1, 'SUMMARIZATION',
     E'You are a financial analyst summarizing the relationship between two entities.\n\nRelation: {{ subject }} --[{{ relation_type }}]--> {{ object }}\n\nEvidence pieces (ordered by date):\n{% for e in evidence %}\n- [{{ e.date }}] {{ e.text }} (confidence: {{ e.confidence }})\n{% endfor %}\n\nWrite a concise summary (2-4 sentences) of this relationship based on the evidence.\nFocus on the current state, key developments, and confidence level.',
     '{"type": "object", "properties": {"summary": {"type": "string"}, "key_facts": {"type": "array", "items": {"type": "string"}}}, "required": ["summary"]}'::jsonb,
     true),

    -- Entity profile generation prompt
    ('entity_profile', 1, 'ENTITY_PROFILE',
     E'You are a financial analyst creating a brief entity profile.\n\nEntity: {{ entity_name }} ({{ entity_type }})\n\nKnown relations:\n{% for r in relations %}\n- {{ r.type }}: {{ r.other_entity }} (confidence: {{ r.confidence }})\n{% endfor %}\n\nRecent mentions:\n{% for m in mentions %}\n- [{{ m.date }}] {{ m.text }}\n{% endfor %}\n\nWrite a concise profile (3-5 sentences) suitable for embedding as a definition view.',
     '{"type": "object", "properties": {"profile": {"type": "string"}, "key_attributes": {"type": "array", "items": {"type": "string"}}}, "required": ["profile"]}'::jsonb,
     true)

ON CONFLICT (name, version) DO NOTHING;

-- SummaryWorker (Worker 13C) hardcodes this UUID as _PROMPT_TEMPLATE_ID.
-- Without this row, every summary INSERT fails with a FK violation and
-- relation_summaries stays permanently empty.
-- BP-NEW: "SummaryWorker prompt_template_id FK seed missing" (2026-05-10)
INSERT INTO prompt_templates (template_id, name, version, capability, template_text, output_schema, is_active)
VALUES (
    '00000000-0000-0000-0000-000000000001',
    'relation_summary_v2',
    2,
    'SUMMARIZATION',
    E'Summarize the following evidence statements about a relationship between two entities into a concise 2-3 sentence summary. Focus on key facts and avoid repetition.\n\nSTRICT RULES:\n- Do not invent or add any claims not present in the evidence statements below.\n- If the evidence statements are contradictory, write: ''Evidence is conflicting on [topic].''\n- Do not use qualitative adjectives (''strong'', ''strategic'', ''important'') unless they appear verbatim in the evidence.\n\n{evidence_statements}',
    '{"type": "object", "properties": {"summary": {"type": "string"}}, "required": ["summary"]}'::jsonb,
    true
)
ON CONFLICT (template_id) DO NOTHING;
