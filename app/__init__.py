"""Phase 5 — Query Bot (RAG) backend.

Real-time, read-only service: retrieves relevant reviews from the pre-built
Chroma index (Phase 4), grounds answers in Phase 3 aggregates, and has Groq
synthesize a cited answer. Never triggers scraping.
"""
