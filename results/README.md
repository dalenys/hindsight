# results/

Local evaluation and benchmark output — recall-session transcripts and
hybrid-vs-vector benchmark tables produced while validating each substrate.

These files quote the ingested conversation corpus verbatim, so they are
**private by construction** and git-ignored. Only this README is committed.

To reproduce a benchmark against your own corpus:

```bash
cd mcp_server
uv run python scripts/bench_hybrid.py
```
