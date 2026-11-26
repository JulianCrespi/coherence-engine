# Coherence Engine

What if an organization could learn from its own experience? Coherence Engine follows a fictional company whose AI agents preserve context, trace changed commitments, and discover opportunities across teams. Each agent works within an assigned role.

The demo follows Maya's Delivery handoff. A signed amendment shortens North's notice deadline from 48 to 24 hours. Maya's agent must connect a departed colleague's note with a later job rename. Stan in Operations approves the targeted change, and a separate simulated inbox records delivery. In the final scene, Noor's Product agent connects two independent observations and records a proposed trial that awaits review.

## Run the judge walkthrough

Use Python 3.14 and the pinned Relate binding. The replay runs locally without a model account.

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -B judge_replay.py --serve
```

Open [the judge viewer](http://127.0.0.1:8765/). Select **Remember**, **Respond**, or **Discover**, then select nodes to read the evidence. In **Respond**, select **Verifier** to inspect the Operations approval, scheduler state, and inbox receipt.

The walkthrough replays recorded model requests and the fictional approval. It reruns the Relate operations and the simulator against a fresh store and checks the results before opening the viewer.

## How it uses Relate

**Mode** Single file  
**Saved graph** [`data/north.rl`](data/north.rl)

Relate runs in the Python process and stores the fictional North graph in one portable file. Judges can reopen the included graph to inspect agent assignments, temporal observations, versioned evidence, and the Commercial Ops notification without a database server.

The live North view opens `data/north.rl` in read-only mode. It queries the applicable rule at Maya's cutoff and follows the evidence links to the renamed job. The judge replay creates a fresh single-file store for the handoff and Product scenes.

To rebuild the North graph in a new file, run:

```sh
.venv/bin/python -B north_memory.py data/north-rebuilt.rl
.venv/bin/python -B north_ask.py --store data/north-rebuilt.rl
```

## Try Ask Both as Maya

Run `.venv/bin/python -B north_ask.py` and open [the North view](http://127.0.0.1:8773/). Switch between Day 13 and Day 14 to see when the Commercial Ops watch recorded the signed amendment and notified Maya's agent.

For live **Ask Both** answers, install the Codex CLI and sign in to ChatGPT. Use fictional questions. GPT-6.2 Sol Low answers twice with the same role, cutoff, and permitted source records. The Relate answer also receives the temporal rule, dependency path, and watch activity. This comparison is read-only.

## Verify the demo

```sh
.venv/bin/python -B -m unittest -q
.venv/bin/python -B judge_replay.py
```

The tests check dated readback, access boundaries, watch retries, recorded calls, and simulated effects. The shipped graph must match a newly generated fixture at both cutoffs.

## Tools and AI disclosure

- **Relate 1.2.0** stores the graph through its embedded Python binding and runs parameterized Cypher queries.
- **Python and SQLite** run the gateway, local viewer, simulated scheduler, and independent inbox.
- **Qwen3 1.7B** produced the original recorded tool requests used by the judge replay. The replay runs without model weights.
- **OpenAI Codex** assisted design, implementation, verification, and documentation. The optional live North view uses account-based GPT-6.2 Sol Low.

Earlier Daydreamer research inspired the design. This hackathon repository contains the fictional demo and its fixtures. All people, contracts, operational events, and outcomes in the demo are synthetic.
