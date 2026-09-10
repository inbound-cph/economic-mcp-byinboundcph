# Skills til e-conomic

Færdige arbejdsgange, som Claude Code, Codex og andre agenter, der følger
[Agent Skills-standarden](https://agentskills.io), kan bruge sammen med e-conomic
MCP-serveren. Hvert skill er en mappe med en `SKILL.md`, der beskriver hvornår skillet
gælder, og hvordan opgaven løses korrekt og sikkert.

| Skill | Det gør den | Skriver i e-conomic? |
|---|---|---|
| `economic-debitorer` | Forfaldne fakturaer, aldersfordeling, anbefalet opfølgning og udkast til rykkere | Nej |
| `economic-maanedsrapport` | Måneds-, kvartals- eller årsrapport: hovedtal, udvikling, debitorer, likviditet, største kunder | Nej |
| `economic-kundeoverblik` | Alt om én kunde: stamdata, kontakter, saldo, historik, åbne poster, kladder og tilbud | Nej |
| `economic-kontoudtog` | Posteringer på en konto, filtre, løbende sum, afstemning og CSV-eksport | Nej |
| `economic-dataspoergsmaal` | Præcise svar på ad hoc-spørgsmål med de rigtige kilder, filtre og pagination | Nej |
| `economic-fakturakladde` | Opret og ret fakturakladder med korrekte referencer; bogfør kun på udtrykkelig anmodning | Ja (kladde; bogføring kun efter ja) |
| `economic-bilag` | Finansbilag i kassekladden: omposteringer, småudgifter, gebyrer, rettelser | Ja (ubogført post i kladden) |

Skriveskills viser altid et forslag og venter på et ja, før noget oprettes. Kører
serveren med `MCP_READ_ONLY=true`, er skriveværktøjerne ikke tilgængelige, og
skills'ene forklarer det.

## Installation

Forudsætning: e-conomic MCP-serveren er tilføjet i klienten (GUIDE.md trin 4).

**Claude Code – som plugin (anbefalet):**

```
/plugin marketplace add inbound-cph/economic-mcp-v2
/plugin install economic@economic-mcp
```

Skills'ene hedder derefter `/economic:economic-debitorer` osv. og trigger også
automatisk, når en opgave passer.

**Claude Code og Codex – kopiér ind som personlige skills:**

```bash
python scripts/install_skills.py          # ~/.claude/skills og ~/.agents/skills
python scripts/install_skills.py --link   # symlinks, så git pull opdaterer dem
```

**I selve repoet** finder Claude Code skills'ene via pluginet, og Codex finder dem via
`.agents/skills`, så snart du åbner agenten i mappen.

## Skriv dine egne

Kopiér en af mapperne, ret `name` og `description` i toppen af `SKILL.md`, og beskriv
arbejdsgangen i imperativ. Beskrivelsen er det, agenten bruger til at afgøre, om
skillet skal bruges, så nævn de ord brugerne faktisk siger. Hold alle tal i e-conomic
MCP-værktøjerne, og lad skriveoperationer kræve et ja.
