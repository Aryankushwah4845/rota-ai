# Rota AI — Plan

## Vision
An add-on "brain" that sits beside a company's existing rota/HR software, learns from historical
rotas, and generates a fair draft rota in one click. Managers review, tweak, and publish.

## Key decisions
- **Integrate, don't replace.** Large chains won't switch software; we plug in via file export/import, API, or an embedded button.
- **Runs locally / on-premise.** Client staff data stays inside their systems — our main selling point.
- **One core engine + industry templates + client settings.** Connectors translate each client's data into our standard format.
- **Neutral metrics only.** Measure reliability, skills and preferences — never label people "hard workers" (fairness + GDPR).

## Industries
Restaurants, grocery/retail, care homes, and more. Each industry's rules come from manager discovery meetings.

## Build stages
1. Setup (folder, Python, Git, GitHub) 
2. Discovery questionnaire + manager meetings
3. Working engine on fake café data
4. Local web screen
5. Smarter features: history, fairness, demand, explanations, sick cover
6. Pilot with one real business
7. Packaging + connectors
8. Business: GDPR, data processing agreements, pricing
