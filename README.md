# Coherence Engine

**Turning organizational memory into proactive collective intelligence.**

*Relate by Neo4j Hackathon 2026 · Research prototype · Proprietary software*

## Vision

What if an organization could learn from its own experience?

Every organization generates knowledge through conversations, decisions, customer interactions, and operational challenges. Much of that knowledge remains fragmented across teams, applications, and people's memories.

Coherence Engine explores an organizational intelligence layer that preserves experience, connects knowledge, and helps teams act on what they collectively know. The hackathon prototype follows one fictional company through a contract handoff and a cross-team discovery.

## Run the judge walkthrough

Use Python 3.14. The replay runs without a model account or model weights.

```sh
git clone https://github.com/JulianCrespi/coherence-engine.git
cd coherence-engine
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -B judge_replay.py --serve
```

Open the [judge viewer](http://127.0.0.1:8765/). Choose a scene and select nodes to see the evidence.

| Scene | What to look for |
| --- | --- |
| **Remember** | Maya's Delivery agent starts a fresh session and recovers Ari's unfinished handoff under an institutional grant. |
| **Respond** | A signed amendment cuts North's deadline from 48 to 24 hours. Ari's note identifies the component, and the scheduler log identifies its renamed job, `notify-8`. Open **Verifier** to see Stan's approval and the separate simulated inbox receipt. |
| **Discover** | Noor's Product agent connects two independent observations with a pilot capability. It recognizes a forwarded copy and records a one-site trial proposal for review. |

The walkthrough replays recorded model requests and a fictional Operations approval. It reruns Relate reads and writes, the scheduler update, and the independent inbox check. Every person, record, and operational outcome in the demo is synthetic.

## How it uses Relate

**Mode** Single file

**Saved graph** [`data/north.rl`](data/north.rl)

Relate runs inside the Python process. The saved North graph is a portable file that judges can reopen without running a separate database server. It contains agent assignments, temporal observations, versioned evidence, and the Commercial Ops notification.

The North viewer reads the included graph in read-only mode. It queries the applicable deadline at Maya's cutoff and follows the source links to the renamed job. The judge replay creates its own single-file store while it reruns the three scenes.

To rebuild the North graph in a separate file:

```sh
.venv/bin/python -B north_memory.py data/north-rebuilt.rl
.venv/bin/python -B north_ask.py --store data/north-rebuilt.rl
```

## Try Ask Both as Maya

Run `.venv/bin/python -B north_ask.py` and open the [North viewer](http://127.0.0.1:8773/). On Day 13, Maya sees the 48-hour rule. On Day 14, the simulated Commercial Ops watch surfaces the signed 24-hour amendment. Open the observation to see its Day 10 effective date and Day 14 recording date.

For live answers, install the Codex CLI and sign in to ChatGPT. Ask a fictional question as Maya. Both GPT-6.2 Sol Low calls receive the same role, question, cutoff, and permitted sources. The Relate answer also receives the applicable rule, evidence path, and watch activity. Each answer shows its citations and token use. The comparison is read-only.

## Verify the demo

```sh
.venv/bin/python -B -m unittest -q
.venv/bin/python -B judge_replay.py
```

The tests check permissions, temporal cutoffs, watch retries, replay, and simulated effects. They also compare the included graph with a fresh fixture at both Maya cutoffs.

## Core capabilities

The research explores five capabilities. The hackathon prototype illustrates continuity, coordination, and discovery in the fictional company.

| Capability | Purpose |
| --- | --- |
| Capture | Preserve relevant organizational experience. |
| Connect | Establish meaningful relationships across fragmented knowledge. |
| Remember | Maintain context across agents, sessions, and time. |
| Discover | Surface risks, contradictions, and opportunities. |
| Learn | Carry a decision and its observed outcome into future work. |

## Technology and AI use

- **Relate 1.2.0** stores the graph and runs parameterized Cypher queries through its embedded Python binding.
- **Python and SQLite** run the agent gateway, viewers, simulated scheduler, and independent inbox.
- **Qwen3 1.7B** produced the recorded model requests used in the judge replay.
- **OpenAI Codex** assisted design, implementation, verification, and documentation. The optional live North comparison uses account-based GPT-6.2 Sol Low.

## Research background and status

Coherence Engine builds on Julián Crespi's independent Daydreamer research into persistent AI memory, knowledge graphs, and human-agent collaboration. The hackathon implementation applies those ideas to organizational learning. This repository contains the standalone prototype and its synthetic fixtures.

Coherence Engine is an experimental research prototype for the 2026 Relate by Neo4j Hackathon. The fictional demonstration establishes the behavior of the implemented scenarios. Longitudinal organizational learning remains an open research question.

## Author

**Julián Crespi**

Creator, project architect, and developer.

Coherence Engine is an independent research and development project created with the assistance of AI development tools.

## License and intellectual property

Copyright © 2026 Julián Crespi. All rights reserved.

**Coherence Engine is proprietary software.**

The materials in this repository are made publicly accessible for inspection, demonstration, and evaluation in connection with the Relate by Neo4j Hackathon.

Permission is granted to hackathon organizers and judges to download, install, execute, and evaluate the software solely for competition-related purposes.

Except for this limited permission, rights granted under GitHub's Terms of Service, or rights provided by applicable law, no permission is granted to reproduce, modify, redistribute, sublicense, create derivative works from, commercially exploit, or otherwise use the proprietary materials without prior written authorization from the copyright holder.

Third-party software and dependencies remain subject to their respective licenses.

All rights not expressly granted are reserved.

## Commercial inquiries

For licensing, research collaboration, partnerships, or commercial inquiries, please contact [Julián Crespi through GitHub](https://github.com/JulianCrespi).
