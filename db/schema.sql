\restrict dbmate

-- Dumped from database version 16.13 (Ubuntu 16.13-1.pgdg24.04+1)
-- Dumped by pg_dump version 18.3

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET transaction_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: vector; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public;


--
-- Name: EXTENSION vector; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON EXTENSION vector IS 'vector data type and ivfflat and hnsw access methods';


SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: embeddings_1536; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.embeddings_1536 (
    item_id uuid NOT NULL,
    model text NOT NULL,
    embedding public.vector(1536) NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: items; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.items (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    kind text NOT NULL,
    source text NOT NULL,
    content text NOT NULL,
    attrs jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    content_tsv tsvector GENERATED ALWAYS AS (to_tsvector('english'::regconfig, content)) STORED,
    CONSTRAINT items_kind_check CHECK ((kind = ANY (ARRAY['document'::text, 'event'::text, 'entity'::text])))
);


--
-- Name: items_s0_archive; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.items_s0_archive (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    source text NOT NULL,
    content text NOT NULL,
    embedding public.vector(1536),
    metadata jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: schema_migrations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.schema_migrations (
    version character varying NOT NULL
);


--
-- Name: embeddings_1536 embeddings_1536_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.embeddings_1536
    ADD CONSTRAINT embeddings_1536_pkey PRIMARY KEY (item_id, model);


--
-- Name: items items_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.items
    ADD CONSTRAINT items_pkey PRIMARY KEY (id);


--
-- Name: items_s0_archive items_s0_archive_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.items_s0_archive
    ADD CONSTRAINT items_s0_archive_pkey PRIMARY KEY (id);


--
-- Name: schema_migrations schema_migrations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.schema_migrations
    ADD CONSTRAINT schema_migrations_pkey PRIMARY KEY (version);


--
-- Name: embeddings_1536_hnsw; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX embeddings_1536_hnsw ON public.embeddings_1536 USING hnsw (embedding public.vector_cosine_ops);


--
-- Name: items_content_tsv_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX items_content_tsv_idx ON public.items USING gin (content_tsv);


--
-- Name: items_conversation_uuid_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX items_conversation_uuid_idx ON public.items USING btree (((attrs ->> 'conversation_uuid'::text))) WHERE (kind = 'document'::text);


--
-- Name: items_created_at_desc_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX items_created_at_desc_idx ON public.items USING btree (created_at DESC);


--
-- Name: items_kind_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX items_kind_idx ON public.items USING btree (kind);


--
-- Name: items_s0_archive_embedding_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX items_s0_archive_embedding_idx ON public.items_s0_archive USING hnsw (embedding public.vector_cosine_ops);


--
-- Name: items_s0_archive_source_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX items_s0_archive_source_idx ON public.items_s0_archive USING btree (source);


--
-- Name: items_source_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX items_source_idx ON public.items USING btree (source);


--
-- Name: embeddings_1536 embeddings_1536_item_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.embeddings_1536
    ADD CONSTRAINT embeddings_1536_item_id_fkey FOREIGN KEY (item_id) REFERENCES public.items(id) ON DELETE CASCADE;


--
-- PostgreSQL database dump complete
--

\unrestrict dbmate


--
-- Dbmate schema migrations
--

INSERT INTO public.schema_migrations (version) VALUES
    ('20260423120000'),
    ('20260423120001'),
    ('20260423130000');
