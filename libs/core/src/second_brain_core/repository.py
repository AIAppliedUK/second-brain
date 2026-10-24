from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from psycopg.rows import dict_row

from second_brain_models import (
    AuditEvent,
    ChunkRecord,
    ChunkUpsert,
    SourceRecord,
    SourceSummary,
    SourceUpsert,
)

from .db import Database


def _vector_literal(values: Sequence[float]) -> str:
    return "[" + ",".join(f"{value:.8f}" for value in values) + "]"


@dataclass(slots=True)
class QueryBundle:
    sql: str
    params: dict[str, Any]


def build_metadata_filter_sql(
    metadata_matches: dict[str, str],
    alias: str,
    parameter_prefix: str = "metadata",
) -> tuple[str, dict[str, str]]:
    parts: list[str] = []
    params: dict[str, str] = {}
    for index, (key, value) in enumerate(metadata_matches.items()):
        key_name = f"{parameter_prefix}_key_{index}"
        value_name = f"{parameter_prefix}_value_{index}"
        parts.append(f"{alias}.metadata ->> %({key_name})s = %({value_name})s")
        params[key_name] = key
        params[value_name] = value
    return " AND ".join(parts), params


# A lexeme in more than this share of chunks is "common": matched on its own it turns
# the GIN lookup into a scan of most of the table, for chunks that only cover one query
# term and so rank below everything else.
COMMON_LEXEME_FREQUENCY = 0.03

# Corpus frequency of each query lexeme, from the planner statistics ANALYZE keeps for
# chunks.tsv (most_common_elem_freqs carries three trailing summary values, which pair
# with NULL elements and drop out of the join).
_LEXEME_FREQUENCY_SQL = """
    SELECT e.lexeme, e.frequency
    FROM pg_stats s,
        unnest(s.most_common_elems::text::text[], s.most_common_elem_freqs)
            AS e(lexeme, frequency)
    WHERE s.tablename = 'chunks' AND s.attname = 'tsv'
        AND e.lexeme = ANY(tsvector_to_array(to_tsvector('english', %(query)s)))
"""


def _tsquery_term(lexeme: str) -> str:
    return "'" + lexeme.replace("\\", "\\\\").replace("'", "''") + "'"


def build_lexical_filter(lexemes: Sequence[str], frequencies: dict[str, float]) -> str | None:
    """Build the tsquery that selects lexical candidates.

    Rare lexemes match on their own; common ones only in pairs, so a chunk must share two
    common words with the query to qualify. Without statistics every lexeme is rare and
    this is a plain OR of the query terms.
    """
    rare = [lex for lex in lexemes if frequencies.get(lex, 0.0) <= COMMON_LEXEME_FREQUENCY]
    common = [lex for lex in lexemes if lex not in rare]
    if len(common) == 1 and not rare:
        rare, common = common, []
    clauses = [_tsquery_term(lex) for lex in rare]
    clauses += [
        f"({_tsquery_term(first)} & {_tsquery_term(second)})"
        for index, first in enumerate(common)
        for second in common[index + 1 :]
    ]
    return " | ".join(clauses) or None


def build_lexical_query(
    query: str,
    embedding_dimension: int,
    limit: int,
    filters: dict[str, Any],
) -> QueryBundle:
    _ = embedding_dimension
    metadata_sql, metadata_params = build_metadata_filter_sql(
        filters.get("metadata_matches", {}), "c"
    )
    # OR the query's terms (plainto_tsquery ANDs them): natural-language questions rarely
    # contain every term. Rank by how many distinct terms a chunk covers first, then by
    # ts_rank_cd density (normalised to 0-1) so one word repeated many times cannot
    # outrank a chunk that contains the whole query.
    # filter_tsq narrows the candidates (see build_lexical_filter); ChunkRepository fills it
    # in from corpus statistics, otherwise every chunk matching any term is a candidate.
    where_clauses = ["c.tsv @@ COALESCE(%(filter_tsq)s::tsquery, q.tsq)", "s.status = 'active'"]
    params: dict[str, Any] = {
        "query": query,
        "limit": limit,
        "filter_tsq": None,
        **metadata_params,
    }
    if memory_scopes := filters.get("memory_scopes"):
        where_clauses.append("c.memory_scope = ANY(%(memory_scopes)s)")
        params["memory_scopes"] = memory_scopes
    if source_types := filters.get("source_types"):
        where_clauses.append("s.source_type = ANY(%(source_types)s)")
        params["source_types"] = source_types
    if containers := filters.get("containers"):
        where_clauses.append("s.container_lineage && %(containers)s")
        params["containers"] = containers
    if updated_after := filters.get("updated_after"):
        where_clauses.append("s.updated_at >= %(updated_after)s")
        params["updated_after"] = updated_after
    if updated_before := filters.get("updated_before"):
        where_clauses.append("s.updated_at <= %(updated_before)s")
        params["updated_before"] = updated_before
    if metadata_sql:
        where_clauses.append(metadata_sql)
    sql = f"""
        SELECT
            c.id,
            c.source_id,
            c.memory_scope,
            c.chunk_index,
            c.heading_path,
            c.chunk_text,
            c.token_count,
            c.metadata,
            (
                SELECT count(*) FROM unnest(q.lexemes) AS lexeme
                WHERE c.tsv @@ quote_literal(lexeme)::tsquery
            ) + ts_rank_cd(c.tsv, q.tsq, 32) AS lexical_score,
            s.id AS source_row_id,
            s.memory_scope AS source_memory_scope,
            s.source_type,
            s.external_id,
            s.title,
            s.uri,
            s.container_lineage,
            s.created_at,
            s.updated_at,
            s.ingested_at,
            s.content_hash,
            s.metadata AS source_metadata,
            NULL AS raw_html,
            NULL AS raw_text,
            NULL AS canonical_text,
            s.status,
            s.deleted_at
        FROM chunks c
        INNER JOIN sources s ON s.id = c.source_id
        CROSS JOIN (
            SELECT
                to_tsquery(
                    'english', replace(plainto_tsquery('english', %(query)s)::text, '&', '|')
                ) AS tsq,
                tsvector_to_array(to_tsvector('english', %(query)s)) AS lexemes
        ) q
        WHERE {" AND ".join(where_clauses)}
        ORDER BY lexical_score DESC, c.chunk_index ASC
        LIMIT %(limit)s
    """
    return QueryBundle(sql=sql, params=params)


def build_vector_query(
    query_embedding: Sequence[float], limit: int, filters: dict[str, Any]
) -> QueryBundle:
    metadata_sql, metadata_params = build_metadata_filter_sql(
        filters.get("metadata_matches", {}), "c"
    )
    where_clauses = ["c.embedding IS NOT NULL", "s.status = 'active'"]
    params: dict[str, Any] = {
        "embedding": _vector_literal(query_embedding),
        "limit": limit,
        **metadata_params,
    }
    if memory_scopes := filters.get("memory_scopes"):
        where_clauses.append("c.memory_scope = ANY(%(memory_scopes)s)")
        params["memory_scopes"] = memory_scopes
    if source_types := filters.get("source_types"):
        where_clauses.append("s.source_type = ANY(%(source_types)s)")
        params["source_types"] = source_types
    if containers := filters.get("containers"):
        where_clauses.append("s.container_lineage && %(containers)s")
        params["containers"] = containers
    if updated_after := filters.get("updated_after"):
        where_clauses.append("s.updated_at >= %(updated_after)s")
        params["updated_after"] = updated_after
    if updated_before := filters.get("updated_before"):
        where_clauses.append("s.updated_at <= %(updated_before)s")
        params["updated_before"] = updated_before
    if metadata_sql:
        where_clauses.append(metadata_sql)
    sql = f"""
        SELECT
            c.id,
            c.source_id,
            c.memory_scope,
            c.chunk_index,
            c.heading_path,
            c.chunk_text,
            c.token_count,
            c.metadata,
            1 - (c.embedding <=> %(embedding)s::vector) AS vector_score,
            s.id AS source_row_id,
            s.memory_scope AS source_memory_scope,
            s.source_type,
            s.external_id,
            s.title,
            s.uri,
            s.container_lineage,
            s.created_at,
            s.updated_at,
            s.ingested_at,
            s.content_hash,
            s.metadata AS source_metadata,
            NULL AS raw_html,
            NULL AS raw_text,
            NULL AS canonical_text,
            s.status,
            s.deleted_at
        FROM chunks c
        INNER JOIN sources s ON s.id = c.source_id
        WHERE {" AND ".join(where_clauses)}
        -- Distance must be the only sort key, or the planner cannot use the HNSW index.
        ORDER BY c.embedding <=> %(embedding)s::vector ASC
        LIMIT %(limit)s
    """
    return QueryBundle(sql=sql, params=params)


def _row_to_source(row: dict[str, Any]) -> SourceRecord:
    return SourceRecord(
        id=row["source_row_id"],
        memory_scope=row["source_memory_scope"],
        source_type=row["source_type"],
        external_id=row["external_id"],
        title=row["title"],
        uri=row["uri"],
        container_lineage=row["container_lineage"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        ingested_at=row["ingested_at"],
        content_hash=row["content_hash"],
        metadata=row["source_metadata"],
        raw_html=row["raw_html"],
        raw_text=row["raw_text"],
        canonical_text=row["canonical_text"],
        status=row["status"],
        deleted_at=row["deleted_at"],
    )


def _row_to_chunk(row: dict[str, Any], score_field: str) -> ChunkRecord:
    kwargs = {
        "id": row["id"],
        "source_id": row["source_id"],
        "memory_scope": row["memory_scope"],
        "chunk_index": row["chunk_index"],
        "heading_path": row["heading_path"],
        "chunk_text": row["chunk_text"],
        "token_count": row["token_count"],
        "metadata": row["metadata"],
        "embedding": [],
        "source": _row_to_source(row),
    }
    if score_field == "lexical_score":
        kwargs["lexical_score"] = row["lexical_score"]
    else:
        kwargs["vector_score"] = row["vector_score"]
    return ChunkRecord(**kwargs)


class SourceRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def upsert_source(self, source: SourceUpsert) -> SourceRecord:
        with self.database.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                INSERT INTO sources (
                    id, source_type, external_id, title, uri, container_lineage,
                    memory_scope, created_at, updated_at, content_hash, metadata, raw_html,
                    raw_text, canonical_text, status
                ) VALUES (
                    %(id)s, %(source_type)s, %(external_id)s, %(title)s, %(uri)s,
                    %(container_lineage)s, %(memory_scope)s, %(created_at)s, %(updated_at)s,
                    %(content_hash)s, %(metadata)s::jsonb, %(raw_html)s,
                    %(raw_text)s, %(canonical_text)s, %(status)s
                )
                ON CONFLICT (memory_scope, source_type, external_id) DO UPDATE SET
                    title = EXCLUDED.title,
                    uri = EXCLUDED.uri,
                    container_lineage = EXCLUDED.container_lineage,
                    memory_scope = EXCLUDED.memory_scope,
                    created_at = EXCLUDED.created_at,
                    updated_at = EXCLUDED.updated_at,
                    content_hash = EXCLUDED.content_hash,
                    metadata = EXCLUDED.metadata,
                    raw_html = EXCLUDED.raw_html,
                    raw_text = EXCLUDED.raw_text,
                    canonical_text = EXCLUDED.canonical_text,
                    status = EXCLUDED.status,
                    ingested_at = NOW()
                RETURNING *
                """,
                {
                    **source.model_dump(),
                    "metadata": json.dumps(source.metadata),
                },
            )
            row = cur.fetchone()
            conn.commit()
        if row is None:
            raise RuntimeError("Failed to upsert source")
        return SourceRecord(**row)

    def get_source_by_identity(
        self,
        memory_scope: str,
        source_type: str,
        external_id: str,
    ) -> SourceRecord | None:
        with self.database.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT * FROM sources
                WHERE memory_scope = %s AND source_type = %s AND external_id = %s
                """,
                (memory_scope, source_type, external_id),
            )
            row = cur.fetchone()
        if row is None:
            return None
        return SourceRecord(**row)

    def mark_failed(self, source: SourceUpsert) -> SourceRecord:
        """Record a file that could not be ingested, so unchanged files are not retried."""
        return self.upsert_source(source.model_copy(update={"status": "failed"}))

    def list_local_file_ids(self, memory_scope: str) -> dict[str, UUID]:
        with self.database.connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT external_id, id FROM sources
                WHERE memory_scope = %s AND source_type = 'local_file'
                """,
                (memory_scope,),
            )
            return {external_id: source_id for external_id, source_id in cur.fetchall()}

    def delete_local_files_outside_scopes(self, path_prefix: str, keep_scopes: set[str]) -> int:
        """Delete files under path_prefix that belong to no current scope (deleted folders)."""
        escaped = path_prefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        with self.database.connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                DELETE FROM sources
                WHERE source_type = 'local_file'
                  AND external_id LIKE %s
                  AND memory_scope <> ALL(%s)
                """,
                (escaped + "/%", list(keep_scopes)),
            )
            deleted = cur.rowcount
            conn.commit()
        return deleted

    def delete_sources(self, source_ids: Sequence[UUID]) -> int:
        if not source_ids:
            return 0
        with self.database.connection() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM sources WHERE id = ANY(%s)", (list(source_ids),))
            deleted = cur.rowcount
            conn.commit()
        return deleted

    def get_source(self, source_id: UUID) -> SourceRecord | None:
        with self.database.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
            cur.execute("SELECT * FROM sources WHERE id = %s", (source_id,))
            row = cur.fetchone()
        if row is None:
            return None
        return SourceRecord(**row)

    def list_sources(
        self,
        limit: int = 25,
        source_type: str | None = None,
        memory_scope: str | None = None,
    ) -> list[SourceSummary]:
        sql = """
            SELECT
                s.id,
                s.memory_scope,
                s.source_type,
                s.title,
                s.uri,
                s.container_lineage,
                s.updated_at,
                s.ingested_at,
                s.status,
                s.metadata,
                COUNT(c.id)::integer AS chunk_count
            FROM sources s
            LEFT JOIN chunks c ON c.source_id = s.id
        """
        params: list[Any] = []
        where_clauses: list[str] = ["s.status = 'active'"]
        if source_type:
            where_clauses.append("s.source_type = %s")
            params.append(source_type)
        if memory_scope:
            where_clauses.append("s.memory_scope = %s")
            params.append(memory_scope)
        sql += " WHERE " + " AND ".join(where_clauses)
        sql += """
            GROUP BY
                s.id, s.memory_scope, s.source_type, s.title, s.uri,
                s.container_lineage, s.updated_at, s.ingested_at, s.status, s.metadata
            ORDER BY s.updated_at DESC NULLS LAST, s.ingested_at DESC
            LIMIT %s
        """
        params.append(limit)
        with self.database.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
        return [SourceSummary(**row) for row in rows]

    def list_memory_scopes(self) -> list[dict[str, Any]]:
        with self.database.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT
                    memory_scope,
                    COUNT(*)::integer AS source_count,
                    COUNT(DISTINCT source_type)::integer AS source_type_count,
                    MAX(updated_at) AS last_updated_at
                FROM sources
                GROUP BY memory_scope
                ORDER BY MAX(updated_at) DESC NULLS LAST, memory_scope ASC
                """
            )
            rows = cur.fetchall()
        return list(rows)

    def delete_memory_scope(self, memory_scope: str) -> dict[str, int]:
        with self.database.connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                DELETE FROM audit_log
                WHERE metadata ->> 'memory_scope' = %s
                   OR source_id IN (SELECT id FROM sources WHERE memory_scope = %s)
                """,
                (memory_scope, memory_scope),
            )
            deleted_audit_events = cur.rowcount
            cur.execute("DELETE FROM chunks WHERE memory_scope = %s", (memory_scope,))
            deleted_chunks = cur.rowcount
            cur.execute("DELETE FROM sources WHERE memory_scope = %s", (memory_scope,))
            deleted_sources = cur.rowcount
            conn.commit()
        return {
            "deleted_audit_events": deleted_audit_events,
            "deleted_chunks": deleted_chunks,
            "deleted_sources": deleted_sources,
        }


class ChunkRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def replace_chunks(self, source_id: UUID, chunks: list[ChunkUpsert]) -> None:
        with self.database.connection() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM chunks WHERE source_id = %s", (source_id,))
            cur.executemany(
                """
                INSERT INTO chunks (
                    id, source_id, chunk_index, heading_path, chunk_text,
                    memory_scope, token_count, metadata, embedding
                ) VALUES (
                    %(id)s, %(source_id)s, %(chunk_index)s, %(heading_path)s, %(chunk_text)s,
                    %(memory_scope)s, %(token_count)s, %(metadata)s::jsonb,
                    %(embedding)s::vector
                )
                """,
                [
                    {
                        **chunk.model_dump(),
                        "metadata": json.dumps(chunk.metadata),
                        "embedding": _vector_literal(chunk.embedding),
                    }
                    for chunk in chunks
                ],
            )
            conn.commit()

    def get_chunk_context(self, chunk_id: UUID, before: int, after: int) -> list[ChunkRecord]:
        with self.database.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                WITH current_chunk AS (
                    SELECT source_id, chunk_index FROM chunks WHERE id = %s
                )
                SELECT
                    c.id,
                    c.source_id,
                    c.memory_scope,
                    c.chunk_index,
                    c.heading_path,
                    c.chunk_text,
                    c.token_count,
                    c.metadata,
                    s.id AS source_row_id,
                    s.memory_scope AS source_memory_scope,
                    s.source_type,
                    s.external_id,
                    s.title,
                    s.uri,
                    s.container_lineage,
                    s.created_at,
                    s.updated_at,
                    s.ingested_at,
                    s.content_hash,
                    s.metadata AS source_metadata,
                    s.raw_html,
                    s.raw_text,
                    s.canonical_text,
                    s.status,
                    s.deleted_at
                FROM chunks c
                INNER JOIN current_chunk cc ON cc.source_id = c.source_id
                INNER JOIN sources s ON s.id = c.source_id
                WHERE c.chunk_index BETWEEN cc.chunk_index - %s AND cc.chunk_index + %s
                ORDER BY c.chunk_index ASC
                """,
                (chunk_id, before, after),
            )
            rows = cur.fetchall()
        return [_row_to_chunk({**row, "lexical_score": None}, "lexical_score") for row in rows]

    def lexical_search(self, query_bundle: QueryBundle) -> list[ChunkRecord]:
        params = dict(query_bundle.params)
        with self.database.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "SELECT tsvector_to_array(to_tsvector('english', %(query)s)) AS lexemes", params
            )
            lexemes = cur.fetchone()["lexemes"]
            cur.execute(_LEXEME_FREQUENCY_SQL, params)
            frequencies = {row["lexeme"]: row["frequency"] for row in cur.fetchall()}
            params["filter_tsq"] = build_lexical_filter(lexemes, frequencies)
            cur.execute(query_bundle.sql, params)
            rows = cur.fetchall()
        return [_row_to_chunk(row, "lexical_score") for row in rows]

    def vector_search(self, query_bundle: QueryBundle) -> list[ChunkRecord]:
        with self.database.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
            # Scope/type filters are applied after the HNSW walk; iterative scan keeps
            # walking until `limit` rows survive the filter instead of returning too few.
            cur.execute("SET LOCAL hnsw.ef_search = 100")
            cur.execute("SET LOCAL hnsw.iterative_scan = relaxed_order")
            cur.execute(query_bundle.sql, query_bundle.params)
            rows = cur.fetchall()
        rows.sort(key=lambda row: row["vector_score"], reverse=True)
        return [_row_to_chunk(row, "vector_score") for row in rows]


class AuditRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def add_event(self, event: AuditEvent) -> None:
        with self.database.connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO audit_log (
                    id, source_id, event_type, status, message, metadata, created_at
                ) VALUES (
                    %(id)s, %(source_id)s, %(event_type)s, %(status)s, %(message)s,
                    %(metadata)s::jsonb, COALESCE(%(created_at)s, NOW())
                )
                """,
                {**event.model_dump(), "metadata": json.dumps(event.metadata)},
            )
            conn.commit()

    def list_recent_failures(
        self,
        event_type: str | None = None,
        limit: int = 10,
        memory_scope: str | None = None,
    ) -> list[dict[str, Any]]:
        sql = """
            SELECT created_at, event_type, status, message, metadata
            FROM audit_log
            WHERE status = 'failed'
        """
        params: list[Any] = []
        if event_type:
            sql += " AND event_type = %s"
            params.append(event_type)
        if memory_scope:
            sql += " AND metadata ->> 'memory_scope' = %s"
            params.append(memory_scope)
        sql += " ORDER BY created_at DESC LIMIT %s"
        params.append(limit)
        with self.database.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
        return list(rows)
