# Rota AI

An AI rota scheduling engine that works **alongside** a business's existing workforce software.
It learns from past rotas, follows each business's rules, and produces a fair draft rota in one click.
It runs on the client's own machine or server, so staff data never leaves their systems.

## Structure

```
rota-ai/
├── docs/                 # plans, questionnaires, meeting notes
│   └── meetings/         # notes from manager discovery meetings
├── data/
│   ├── sample/           # fake test data (safe to commit)
│   └── private/          # real client data — NEVER committed (see .gitignore)
├── src/rota_ai/
│   ├── engine/           # the core rota solver (same for every client)
│   ├── connectors/       # one per client system (CSV, APIs, ...)
│   └── rules/            # industry templates (restaurant, retail, care home)
├── tests/                # automated checks
├── output/               # generated rotas (not committed)
├── run_rota.py           # builds the sample café's rota
└── requirements.txt      # Python packages
```

## Setup (Windows)

```
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

## Run

```
python run_rota.py        # saves the rota to output/rota.xlsx
python -m pytest          # runs the automated checks
```

## Roadmap

1. Working engine on a fake café (spreadsheet in → rota out)
2. Simple local web screen with a "Generate rota" button
3. Learning from history, fairness score, peak-day demand, explanations
4. Pilot with one real business, on their machine
5. Installer + connectors for client systems
