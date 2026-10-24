"""Recall eval for second-brain's HybridRetriever against the live index.

Builds a labelled query set from random *live* chunks (file still on disk,
not under .claude/worktrees) and checks whether the source that chunk came
from appears in the top-k results. Three query styles:

  keywords  - 4 distinctive words copied from the chunk (best case for lexical)
  heading   - the chunk's deepest heading, e.g. "Disaster Recovery" (topic search)
  question  - heading wrapped as a natural question ("how do we handle X?")

Each query runs scoped to the chunk's project (what a well-behaved agent does).
"""
import os
import random
import re
import statistics
import sys
import time

from second_brain_core.db import Database
from second_brain_core.config import Settings
from second_brain_core.embeddings import build_embedder
from second_brain_core.repository import ChunkRepository
from second_brain_core.retrieval import HybridRetriever
from second_brain_models import SearchFilters, SearchRequest

N = int(sys.argv[1]) if len(sys.argv) > 1 else 120
random.seed(7)
dsn = os.environ["SECOND_BRAIN_DB_DSN"]
db = Database(dsn)
retriever = HybridRetriever(ChunkRepository(db), build_embedder(Settings()))

STOP = set("""the and for with that this from are was were have has will shall would
should could their there which when where what into onto about your our you not
been being also such than then them they these those each other more most must
can may any all its it's within across between under over upon using used use""".split())

import psycopg

with psycopg.connect(dsn) as conn:
    rows = conn.execute(
        """
        SELECT c.source_id::text, c.memory_scope, c.chunk_text, c.heading_path, s.external_id
        FROM chunks c TABLESAMPLE SYSTEM (10)
        JOIN sources s ON s.id = c.source_id
        WHERE c.token_count >= 60
          AND s.external_id NOT LIKE '%%/.claude/worktrees/%%'
          AND s.external_id ~* '\\.(md|docx|pdf)$'
        LIMIT 20000
        """
    ).fetchall()

live = [r for r in rows if os.path.exists(r[4])]
# one chunk per source, prefer ones with a meaningful heading
by_src = {}
for r in live:
    if r[3] and len(r[3][-1]) > 6 and r[0] not in by_src:
        by_src[r[0]] = r
sample = random.sample(list(by_src.values()), min(N, len(by_src)))
print(f"sampled rows={len(rows)} live={len(live)} distinct-live-sources={len(by_src)} eval={len(sample)}")


def keywords(text):
    words = [w for w in re.findall(r"[A-Za-z][A-Za-z\-]{4,}", text) if w.lower() not in STOP]
    words = sorted(set(words), key=lambda w: (-len(w), w))[:12]
    random.shuffle(words)
    return " ".join(words[:4])


MODE = sys.argv[2] if len(sys.argv) > 2 else "hybrid"
import second_brain_core.repository as R
from second_brain_core.retrieval import HybridRetriever as HR
_orig_lex = R.build_lexical_query
def _lex(query, embedding_dimension, limit, filters):
    b = _orig_lex(query, embedding_dimension, limit, filters)
    if "clean" in MODE:
        b.sql = b.sql.replace("WHERE ", "WHERE s.external_id NOT LIKE '%%/.claude/worktrees/%%' AND ", 1)
    if "or" in MODE:
        terms = [w for w in re.findall(r"[A-Za-z0-9]+", query) if w.lower() not in STOP and len(w) > 2]
        b.params["query"] = " OR ".join(terms) or query
    return b
import second_brain_core.retrieval as RT
RT.build_lexical_query = _lex

def run(query, scope):
    t = time.perf_counter()
    req = SearchRequest(query=query, limit=10, filters=SearchFilters(memory_scopes=[scope]))
    if MODE == "hybrid":
        hits = retriever.search(req).hits
    else:
        bundle = _lex(query, 256, 10, req.filters.model_dump())
        from types import SimpleNamespace as NS
        hits = [NS(source_id=h.source_id, lexical_score=h.lexical_score, metadata=h.metadata or {}, source_uri=h.source.uri)
                for h in retriever.chunk_repository.lexical_search(bundle)]
    return hits, (time.perf_counter() - t) * 1000


styles = {
    "keywords": lambda r: keywords(r[2]),
    "heading": lambda r: r[3][-1],
    "question": lambda r: f"how do we handle {r[3][-1].lower()} in this project?",
}
ghost_cache = {}
for name, make in styles.items():
    h1 = h5 = h10 = 0
    rr = []
    lat = []
    lex_empty = 0
    ghosts = total_hits = 0
    for r in sample:
        q = make(r)
        if not q.strip():
            continue
        hits, ms = run(q, r[1])
        lat.append(ms)
        ids = [str(h.source_id) for h in hits]
        if not hits or all(h.lexical_score is None for h in hits):
            lex_empty += 1
        for h in hits:
            p = h.metadata.get("path") or h.source_uri.removeprefix("file://")
            if p not in ghost_cache:
                ghost_cache[p] = not os.path.exists(p)
            ghosts += ghost_cache[p]
            total_hits += 1
        rank = ids.index(r[0]) + 1 if r[0] in ids else None
        h1 += rank == 1
        h5 += bool(rank and rank <= 5)
        h10 += bool(rank)
        rr.append(1 / rank if rank else 0)
    n = len(lat)
    print(
        f"{name:9s} n={n} hit@1={h1/n:.0%} hit@5={h5/n:.0%} hit@10={h10/n:.0%} "
        f"MRR={statistics.mean(rr):.2f} lexical-empty={lex_empty/n:.0%} "
        f"ghost-hits={ghosts/max(total_hits,1):.0%} p50={statistics.median(lat):.0f}ms "
        f"p95={sorted(lat)[int(n*0.95)-1]:.0f}ms"
    )
