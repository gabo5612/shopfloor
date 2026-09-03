-- anvil — esquema base. Ver CONTEXTO-ANVIL.md §6.
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE TABLE IF NOT EXISTS document (
  doc_id          TEXT PRIMARY KEY,
  title           TEXT NOT NULL,
  vendor          TEXT,
  equipment_tag   TEXT,
  revision        TEXT,
  effective_date  DATE,
  superseded_by   TEXT REFERENCES document(doc_id),
  lang            TEXT NOT NULL DEFAULT 'en',
  source_path     TEXT NOT NULL,
  sha256          TEXT NOT NULL,
  n_pages         INT,
  ingested_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS page (
  doc_id          TEXT NOT NULL REFERENCES document(doc_id) ON DELETE CASCADE,
  page_no         INT NOT NULL,          -- 1-indexado, como lo ve un humano
  raw_text        TEXT,
  route           TEXT NOT NULL,         -- 'fast' | 'ocr'
  ocr_confidence  REAL,
  PRIMARY KEY (doc_id, page_no)
);

CREATE TABLE IF NOT EXISTS chunk (
  chunk_id        BIGSERIAL PRIMARY KEY,
  doc_id          TEXT NOT NULL REFERENCES document(doc_id) ON DELETE CASCADE,
  page_from       INT NOT NULL,
  page_to         INT NOT NULL,
  section_path    TEXT,
  kind            TEXT NOT NULL,         -- prose | table | procedure
  content         TEXT NOT NULL,
  embedding       vector(1024),          -- bge-m3; 1024 < 2000 -> no hace falta halfvec
  tsv             tsvector,
  embed_model     TEXT,
  embed_dim       INT,
  chunk_strategy_version TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS chunk_embedding_idx ON chunk
  USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS chunk_tsv_idx ON chunk USING gin (tsv);
CREATE INDEX IF NOT EXISTS chunk_doc_idx  ON chunk (doc_id, page_from);

CREATE TABLE IF NOT EXISTS query_log (
  query_id     BIGSERIAL PRIMARY KEY,
  question     TEXT NOT NULL,
  lang         TEXT,
  answer       TEXT,
  abstained    BOOLEAN NOT NULL DEFAULT false,
  verifier_passed BOOLEAN,
  retry_count  INT NOT NULL DEFAULT 0,
  model        TEXT,
  latency_ms   INT,
  asked_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS citation (
  query_id      BIGINT NOT NULL REFERENCES query_log(query_id) ON DELETE CASCADE,
  chunk_id      BIGINT NOT NULL REFERENCES chunk(chunk_id),
  rank          INT NOT NULL,
  score_dense   REAL,
  score_lexical REAL,
  score_rerank  REAL,
  PRIMARY KEY (query_id, chunk_id)
);

-- Cache semantico de preguntas respondidas.
CREATE TABLE IF NOT EXISTS qa_cache (
  cache_id      BIGSERIAL PRIMARY KEY,
  question      TEXT NOT NULL,
  lang          TEXT NOT NULL,
  embedding     vector(1024) NOT NULL,
  terms         TEXT[] NOT NULL,      -- guard determinista: M24, 8.8, E-114
  answer        TEXT NOT NULL,
  chunk_ids     BIGINT[] NOT NULL,
  content_hash  TEXT NOT NULL,        -- si el documento cambia, el cache muere
  doc_ids       TEXT[] NOT NULL DEFAULT '{}',
  stale         BOOLEAN NOT NULL DEFAULT false,  -- doc cambio: se re-responde
  refreshed_at  TIMESTAMPTZ,
  hits          INT NOT NULL DEFAULT 0,
  confirmed     BOOLEAN,              -- NULL sin confirmar, true 👍, false 👎
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  last_used_at  TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS qa_cache_emb_idx ON qa_cache
  USING hnsw (embedding vector_cosine_ops);
