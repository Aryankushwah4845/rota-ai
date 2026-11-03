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
│   └── rules/            # legal rules by country (uk.py), with room for other countries
├── tests/                # automated checks
├── output/               # generated rotas (not committed)
├── app.py                # the manager's web screen (Streamlit)
├── run_rota.py           # builds the sample café's rota without the screen
└── requirements.txt      # Python packages
```

## Setup (Windows)

```
python -m venv .venv
.venv\Scripts\activate
python -m pip install -r requirements.txt
```

## Run

```
python -m streamlit run app.py   # opens the manager's screen in your browser
python run_rota.py               # saves next week's sample rota, e.g. output/rota_2026-11-09.xlsx
python -m pytest                 # runs the automated checks
```

Press Ctrl+C in the terminal to stop the app. It only accepts connections from this computer.

## Your data

The staff file needs `name`, `role`, `contracted_hours`, `unavailable_days` and `date_of_birth`
(like `2009-03-15` or `15/03/2009`). These are optional: `opted_out_48h` and `sunday_opt_out`
(true or false, blank means false) and `hourly_rate` (like `12.71`).

## Legal rules

All legal values live in [src/rota_ai/rules/uk.py](src/rota_ai/rules/uk.py), each beside the law it
comes from. To support another country, add a file like it: the engine doesn't need to change.
These rules are a guide, not legal advice. Check with an employment adviser.

## Roadmap

1. Working engine on a fake café (spreadsheet in → rota out)
2. Simple local web screen with a "Generate rota" button
3. Learning from history, fairness score, peak-day demand, explanations
4. Pilot with one real business, on their machine
5. Installer + connectors for client systems
