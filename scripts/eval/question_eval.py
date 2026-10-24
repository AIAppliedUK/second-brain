"""Hand-written, paraphrased questions with known answer documents, run unscoped."""
import os
import statistics
import time

from second_brain_core.config import Settings
from second_brain_core.db import Database
from second_brain_core.embeddings import build_embedder
from second_brain_core.repository import ChunkRepository
from second_brain_core.retrieval import HybridRetriever
from second_brain_models import SearchRequest

QUESTIONS = [
    ("what rate limit does the API gateway apply per IP address?", ["Schedule-2B"]),
    ("how long do we keep audit records and how is the table split up?", ["Schedule-2B"]),
    ("how are late bids dealt with when the policy is decided case by case?", ["Q2.3"]),
    ("can buyers intervene in a reverse auction while bidding is live?", ["Schedule-2B"]),
    ("AI idea for spotting tenants likely to fall behind on rent", ["Link-Housing-Association"]),
    ("what training do change champions get before launch?", ["pre-go-live-plan", "Q2.29"]),
    ("is there a practice environment where users can try things without touching live data?", ["Schedule-2B"]),
    ("which schedule is the parent company guarantee in the S2C contract?", ["Parent Company Guarantee"]),
    ("what does Museums Galleries Scotland expect from contractors on carbon and sustainability?", ["Organisation Health Checker"]),
    ("supplier duties around labour exploitation and human rights in the supply chain", ["Transparency and Protections"]),
    ("how do we track competitors in our bid pipeline?", ["Tender-Pipeline-Master-Process"]),
    ("what milestones are shown on the submission deadline timeline in the tender app?", ["AI-Tender-Manager-Design-Document"]),
    ("which regulation limits call-off value against the advertised contract maximum?", ["ICT Model Terms and Conditions"]),
    ("API endpoint for searching suppliers and the filters it supports", ["Schedule-2B"]),
]

settings = Settings()
from second_brain_core.embeddings import build_reranker
from second_brain_core.retrieval import RetrievalConfig
retriever = HybridRetriever(ChunkRepository(Database(os.environ["SECOND_BRAIN_DB_DSN"])), build_embedder(settings),
    config=RetrievalConfig(rerank_candidates=int(os.getenv("CANDS", "40")), rerank_passage_words=int(os.getenv("WORDS", "0"))), reranker=build_reranker(settings))
retriever.search(SearchRequest(query="warm up", limit=10))  # exclude one-off ONNX session warm-up from timings
ranks, lat = [], []
for question, targets in QUESTIONS:
    t = time.perf_counter()
    hits = retriever.search(SearchRequest(query=question, limit=10)).hits
    lat.append((time.perf_counter() - t) * 1000)
    rank = next(
        (i for i, h in enumerate(hits, 1) if any(tg in h.source_uri.replace("%20", " ") for tg in targets)),
        None,
    )
    ranks.append(rank)
    top = hits[0].source_uri.replace("%20", " ").rsplit("/", 1)[-1][:55] if hits else "-"
    if os.getenv("QUIET"): continue
    print(f"{('#' + str(rank)) if rank else 'MISS':>5}  {question[:70]:70s}  top: {top}")
n = len(ranks)
print(
    f"\nhit@1={sum(r == 1 for r in ranks)}/{n}  hit@3={sum(bool(r and r <= 3) for r in ranks)}/{n}  "
    f"hit@10={sum(bool(r) for r in ranks)}/{n}  MRR={statistics.mean(1 / r if r else 0 for r in ranks):.2f}  "
    f"p50={statistics.median(lat):.0f}ms"
)
