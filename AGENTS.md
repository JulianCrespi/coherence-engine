# Coherence Engine development

Start with [README.md](README.md) for setup and the three demo scenes. This repository is the standalone synthetic hackathon app. Its root [LICENSE](LICENSE) governs the code.

- Keep fixtures fictional and keep the public checkout self-contained. The default North store is `data/north.rl` in Relate single-file mode.
- Preserve the boundary between the judge replay and live Ask Both. `judge_replay.py` reruns recorded requests, Relate operations, and simulated effects. `north_ask.py` makes optional live calls and opens the packaged graph read-only.
- Maintain actor permissions, knowledge cutoffs, and independent verification of simulated effects. In Ask Both, hold Maya’s role, question, cutoff, and source packet constant. The Relate arm receives the additional graph context.
- When changing graph or replay behavior, run the relevant tests. For a release or a change across both demo paths, run the full suite and replay.

```sh
.venv/bin/python -B -m unittest -q
.venv/bin/python -B judge_replay.py
```

When setup, behavior, or the store path changes, update the README and record the verification result with the change. Preserve original recordings and the outcome of failed checks.
