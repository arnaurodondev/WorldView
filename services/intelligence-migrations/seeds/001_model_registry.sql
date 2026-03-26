-- Seed: model_registry — initial ML models for intelligence pipeline
-- Idempotent: ON CONFLICT DO NOTHING on (model_id, provider, version)

INSERT INTO model_registry (model_id, provider, capability, version, dimension, max_input_tokens, is_active, performance_tier, config)
VALUES
    -- Embedding model (primary)
    ('bge-large-en-v1.5', 'OLLAMA', 'EMBEDDING', 'v1.5', 1024, 512, true, 'PRIMARY',
     '{"ollama_model": "bge-large-en-v1.5", "batch_size": 32}'::jsonb),

    -- NER model (primary)
    ('gliner-large-v2.1', 'HUGGINGFACE', 'NER', 'v2.1', NULL, 512, true, 'PRIMARY',
     '{"model_name": "urchade/gliner_large-v2.1", "threshold": 0.5}'::jsonb),

    -- Extraction / summarization model (primary)
    ('Qwen2.5-7B-Instruct', 'OLLAMA', 'EXTRACTION', 'v2.5', NULL, 32768, true, 'PRIMARY',
     '{"ollama_model": "qwen2.5:7b-instruct", "temperature": 0.1, "top_p": 0.9}'::jsonb)

ON CONFLICT (model_id, provider, version) DO NOTHING;
