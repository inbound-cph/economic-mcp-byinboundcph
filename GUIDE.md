# Kom godt i gang: din egen e-conomic MCP-server

> **Tillykke! Du har hentet InboundCPH's e-conomic MCP-server.** Den er udviklet af
> Ian Rosenfeldt, founder af INBOUND CPH A/S, og er et offentligt projekt under PolyForm Shield-licensen: du må frit bruge, ændre og
> videregive koden, også i din egen virksomhed, men ikke sælge den eller udbyde den som
> konkurrerende produkt eller service. Er du udvikler, er du velkommen til at forbedre
> løsningen og sende en pull request. Opsætningen tager typisk 30–60
> minutter. Noget kan din AI-assistent klare for dig, og noget skal du selv gøre i
> browseren, fordi det kræver dine egne logins:
>
> | Din AI klarer | Du gør selv |
> |---|---|
> | Tjekker din maskine, installerer det der mangler og hjælper med at oprette Railway-konto | Opretter en gratis e-conomic udvikleraftale og en app (trin 1) |
> | Deployer til Railway og genererer sikre nøgler (trin 2) | Godkender appen i dit eget regnskab (trin 1) |
> | Sætter variabler og verificerer, at det virker | Logger ind på Railway (trin 2) |
> | Forbinder din klient og installerer skills (trin 4 og 5b) | Opretter en OAuth-klient hos Google eller Microsoft (trin 3) |

Denne guide får dig fra nul til en kørende MCP-server, som lader Claude, Codex, Cursor
og andre AI-assistenter arbejde direkte i dit e-conomic-regnskab: slå kunder op, finde
forfaldne fakturaer, trække saldi og posteringer, og (når du slår det til) oprette
fakturaer og bilag.

Serveren hoster du selv, typisk på [Railway](https://railway.com). Kun de personer du
godkender kan logge ind. Regnskabsdata går direkte mellem din server og e-conomic.

```
Claude / Codex / Cursor  ──login──▶  din MCP-server (Railway)  ──API-tokens──▶  e-conomic
```

**Tid:** 30 til 60 minutter første gang. Det meste er klik i e-conomic, Railway og
Google/Microsoft. Selve serveren kræver ingen kodeændringer.

---

## Den nemme vej: lad Claude Code eller Codex gøre arbejdet

Repoet indeholder instruktioner til AI-kodeagenter (`AGENTS.md` / `CLAUDE.md`).
Klon repoet, åbn det i Claude Code eller Codex og bed agenten om hjælp:

```bash
git clone https://github.com/inbound-cph/economic-mcp-byinboundcph.git
cd economic-mcp-byinboundcph
claude          # eller: codex
```

Skriv fx: *"Hjælp mig med at sætte e-conomic MCP-serveren op på Railway."*

Agenten tjekker forudsætninger, deployer klonen til Railway, genererer nøgler, sætter
variabler og forbinder din klient. Du skal selv klare de ting der kræver et login i en
browser (e-conomic, Railway, Google/Microsoft). Agenten fortæller hvornår.

Resten af guiden er den manuelle vej og opslagsværk for både dig og agenten.

---

## Trin 0: Det skal du have klar

Du behøver ikke have alt på forhånd. Din AI-assistent spørger, hvad du har, og guider dig
gennem resten. Her er samme liste til dig:

| Det skal du have | Har du det ikke, så |
|---|---|
| **Claude Code** eller **Codex** på din computer | Claude Code: [claude.com/code](https://claude.com/code) (kræver Claude Pro/Max/Team). Codex: [chatgpt.com/codex](https://chatgpt.com/codex) (kræver ChatGPT Plus/Pro/Business). |
| **Git**, **Python 3.10+** og **Railway CLI** | Assistenten installerer dem. Mac: `xcode-select --install` og `brew install python railway`. Windows: `winget install Git.Git Python.Python.3.12` og `npm i -g @railway/cli`. Linux: `sudo apt install git python3 python3-venv` og `npm i -g @railway/cli`. |
| **Railway-konto** (hosting) | `railway login` opretter kontoen i browseren, hvis du ikke har en (log ind med GitHub eller e-mail). Deploy kræver Hobby-planen: et lille månedligt beløb, der inkluderer forbrug, se [railway.com/pricing](https://railway.com/pricing). Du vælger planen i Railway-dashboardet første gang. |
| **e-conomic-regnskab med API-adgang** | Intet regnskab endnu: opret en gratis prøveperiode på [e-conomic.dk](https://www.e-conomic.dk) eller test med `demo`-tokens (kræver intet). Har du et regnskab, er API-adgang med i de fleste pakker; bliver appen afvist med en besked om API/integrationer, så bed e-conomic support om at slå API-adgang til. Kun regnskabets ejer eller en administrator kan godkende appen i trin 1, så hav den person ved tastaturet. |
| **Konto til personligt login** (valgfrit) | Kun nødvendigt, hvis serveren skal deles som connector med hele organisationen via claude.ai. Bruger I Google Workspace: Google-login. Bruger I Microsoft 365: Microsoft-login. Ingen af delene: serverens egen e-mail-og-kodeord-login (trin 3C), ingen ekstern konto nødvendig. Til en lille gruppe i Claude Code/Codex klarer personlige adgangsnøgler det hele. |

---

## Trin 1: e-conomic API-tokens

e-conomic bruger to tokens: **AppSecretToken** (identificerer din app) og
**AgreementGrantToken** (giver appen adgang til ét bestemt regnskab).

1. **Opret en udvikleraftale** (gratis): gå til
   [e-conomic.com/developer](https://www.e-conomic.com/developer) og udfyld
   "Sign up for a developer agreement". Du får login til udvikleraftalen pr. e-mail.
   Udvikleraftalen indeholder ingen regnskabsdata; den bruges kun til at administrere apps.
2. **Opret en app**: log ind på udvikleraftalen → fanen **Apps** (øverst til venstre) →
   **New app** → giv den et navn, fx `MCP-server` → vælg en rolle. Rollen sætter
   loftet for hvad appen kan; vælg den mindste rolle der dækker dit behov (til test kan
   du bruge SuperUser og skifte senere). Gem **AppSecretToken** et sikkert sted. Det
   vises kun én gang.
3. **Giv appen adgang til dit regnskab**: klik **Tokens** på appen og kopiér
   installations-URL'en. Den ser sådan ud:
   `https://secure.e-conomic.com/secure/api1/requestaccess.aspx?appPublicToken=...`
   Åbn den i browseren, log ind med din e-conomic-bruger til **det rigtige regnskab** og
   godkend. Du får nu **AgreementGrantToken** (vises på siden, eller sendes som
   `token`-parameter til den redirect-URL du evt. har angivet).
4. **Test** at tokens virker (erstat værdierne):
   ```bash
   curl -s https://restapi.e-conomic.com/self \
     -H "X-AppSecretToken: DIN_APP_SECRET_TOKEN" \
     -H "X-AgreementGrantToken: DIT_AGREEMENT_GRANT_TOKEN"
   ```
   Svaret indeholder `agreementNumber` og firmanavnet.

**Vil du teste uden dit rigtige regnskab?** Brug `demo` som begge tokens. Det giver
læseadgang til e-conomics demodata (skrivning virker ikke). Du kan også oprette en
gratis "demo med data"-prøveaftale hos e-conomic og give din app adgang til den.

**Sikkerhed:** Tokens giver adgang til regnskabet. Læg dem aldrig i git, chat eller
skærmbilleder. Kan du undgå at sende dem gennem en chat med en AI-agent, så gør det:
indtast dem direkte i Railway (Variables) eller i din egen terminal.

---

## Trin 2: Deploy på Railway

Serveren starter kun, hvis der er sat en adgangsmetode. Den simpleste er **personlige
adgangsnøgler**: én variabel pr. person (`MCP_AUTH_TOKEN_CFO`, `MCP_AUTH_TOKEN_ANNA`), så
loggen viser hvem der gjorde hvad, og en person fjernes ved at slette variablen. Første
deploy laver du med din egen nøgle. Google- eller Microsoft-login (trin 3) er valgfrit og
mest relevant, når serveren skal deles med hele organisationen via claude.ai.

### 2A. Med Railway CLI fra din klon (anbefalet, kan køres af agenten)

```bash
git clone https://github.com/inbound-cph/economic-mcp-byinboundcph.git
cd economic-mcp-byinboundcph

railway login                          # åbner browseren
railway init --name economic-mcp       # opretter projektet og linker mappen

# Opret servicen med de første variabler (start med demo-tokens, skift senere)
railway add --service economic-mcp \
  --variables "MCP_READ_ONLY=true" \
  --variables "ECONOMIC_APP_SECRET_TOKEN=demo" \
  --variables "ECONOMIC_AGREEMENT_GRANT_TOKEN=demo"

# Volume: login-sessioner og krypterede tokens overlever deploys (nødvendig ved personligt login)
railway service economic-mcp               # linker servicen til mappen (volume-kommandoen kræver det)
railway volume add --mount-path /data

# Din egen adgangsnøgle: scriptet viser nøglen én gang og den kommando, der gemmer den
python scripts/new_key.py cfo --service economic-mcp      # brug dit eget navn i stedet for cfo
# ...kør derefter den viste "railway variable set MCP_AUTH_TOKEN_CFO --stdin"-kommando

railway domain --service economic-mcp  # giver dig https://economic-mcp-xxxx.up.railway.app
railway up --detach --service economic-mcp
railway logs --service economic-mcp    # vent på "Authentication: access key"
```

Første deploy tager typisk et halvt til to minutter. Et nyt domæne kan svare "Application
not found" det første minut, mens Railways netværk opdaterer; `doctor.py` prøver selv igen.
Vil du se domænet igen: `railway variable list --service economic-mcp --kv | grep RAILWAY_PUBLIC_DOMAIN`.

Dine rigtige e-conomic-tokens sætter du bagefter uden at de ryger i terminalhistorikken:

```bash
railway variable set ECONOMIC_APP_SECRET_TOKEN --stdin --service economic-mcp --skip-deploys
# indsæt token, tryk Enter, derefter Ctrl+D
railway variable set ECONOMIC_AGREEMENT_GRANT_TOKEN --stdin --service economic-mcp
```

Eller sæt dem i Railway-dashboardet under **Variables**. Railway deployer automatisk igen,
når variabler ændres.

### 2B. Fra Railway-dashboardet

1. Fork repoet til din egen GitHub-konto (eller push din klon til et privat repo).
2. På railway.com: **New Project → Deploy from GitHub repo** → vælg repoet.
3. Åbn servicen → **Variables** → tilføj:
   `ECONOMIC_APP_SECRET_TOKEN`, `ECONOMIC_AGREEMENT_GRANT_TOKEN`, `MCP_READ_ONLY=true`
   og `MCP_AUTH_TOKEN_<DITNAVN>` (32+ tilfældige tegn, fx fra `python scripts/new_key.py <navn>`).
4. **Settings → Networking → Generate Domain**.
5. Vent på deploy. Fordelen ved denne vej: Railway deployer automatisk, når du
   opdaterer dit fork.

### Tjek

```bash
curl https://<dit-domæne>/health
# {"status":"healthy","service":"economic-mcp","auth":"token","readOnly":true}

python scripts/doctor.py --public-url https://<dit-domæne>
```

`doctor.py` bekræfter, at `/mcp` afviser ukendte kald, og udskriver de præcise
kommandoer til at forbinde dine klienter.

### Flere personer

Kør `python scripts/new_key.py anna` for hver person, der skal have adgang, og gem
variablen som scriptet viser. Giv personen nøglen gennem en sikker kanal (password
manager, ikke e-mail). Skal en person ikke længere have adgang, så slet variablen
`MCP_AUTH_TOKEN_ANNA` i Railway; serveren genstarter selv. Til automatiseringer (scripts,
n8n og lignende) bruges `MCP_AUTH_TOKEN` uden navn.

### Volumen

Volumen fra kommandoerne ovenfor er der, serveren gemmer login-sessioner (krypterede tokens
ved Google/Microsoft, hashede refresh-tokens ved e-mail-login). Uden den skulle alle logge
ind igen ved hver deploy, også når en kollega bliver oprettet. Serveren finder selv volumen
via `RAILWAY_VOLUME_MOUNT_PATH`; ingen variabler skal sættes. Bruger du dashboardet
(2B): servicen → *Settings → Volumes → Add volume*, mount path `/data`.

---

## Hvem har adgang? Sådan virker porten

MCP-serveren er porten foran dit regnskab. e-conomic-tokens ligger kun på serveren, og
ingen klient kommer igennem uden enten en personlig adgangsnøgle eller et godkendt login.
Hvert kald logges med personens navn eller e-mail.

| Situation | Vælg | Sådan styres adgangen |
|---|---|---|
| 2–10 navngivne personer (CFO, økonomi, direktion) med Claude Code, Codex, Cursor eller Claude Desktop | **Personlige adgangsnøgler** (trin 2) | Én variabel pr. person. Slet variablen for at fjerne adgang. Ingen login-tjeneste nødvendig. |
| Serveren deles med hele organisationen som *connector* i claude.ai eller Claude Desktop (Team/Enterprise) | **Google- eller Microsoft-login** (trin 3A/3B), eller **e-mail og kodeord** (trin 3C) hvis I ikke har nogen af delene | Connectors kræver et login. Alle kan se connectoren, men kun e-mails på allowlisten, i jeres Microsoft-tenant eller i `MCP_USER_*`-listen kommer ind. |
| Automatiseringer (scripts, n8n, Make) | `MCP_AUTH_TOKEN` uden navn | Logges som `service-token`. |

De to første kan kombineres: nøgler til de få og login til resten.

**Hvem må skrive?** Med `MCP_READ_ONLY=true` kan ingen. Slår du skrivning til, så sæt
`MCP_WRITE_USERS=cfo,anna@firma.dk` (nøglenavne eller e-mails). Kun de nævnte ser og kan
bruge skriveværktøjerne; alle andre har fortsat kun læseadgang.

---

## Trin 3: Personligt login (valgfrit)

Med personligt login logger hver bruger ind i browseren med sin arbejdskonto, første
gang klienten forbinder. Kun konti på din allowlist (eller i din Microsoft-organisation)
kommer igennem, både ved login og ved hvert efterfølgende kald. Adgangsnøglerne kan du
beholde ved siden af.

| Metode | Vælg den hvis | Krav |
|---|---|---|
| **Google login** | I bruger Google Workspace (eller Gmail) | OAuth-klient i Google Cloud + allowlist (`MCP_ALLOWED_DOMAINS`/`MCP_ALLOWED_EMAILS`) |
| **Microsoft login** | I bruger Microsoft 365 / Entra ID | App-registrering i Entra; dit tenant-ID begrænser til jeres organisation |
| **E-mail og kodeord** | I har hverken Google Workspace eller Microsoft 365 | Én variabel pr. bruger (`MCP_USER_<NAVN>`), ingen ekstern tjeneste. Serveren har sin egen login-side. |

Vælg én af de tre. Adgangsnøgler kan bruges ved siden af alle tre.

Redirect-URI'en, som Google/Microsoft skal kende, er altid:

```
https://<dit-domæne>/auth/callback
```

### 3A. Google login

1. Gå til [console.cloud.google.com](https://console.cloud.google.com) og vælg eller opret et projekt.
2. **APIs & Services → OAuth consent screen** (hedder i nyere konsoller *Google Auth
   Platform → Branding/Audience*). Vælg **Internal**, hvis I har Google Workspace: så kan
   kun jeres organisation overhovedet logge ind. Ellers **External** og tilføj brugerne
   som testbrugere under *Audience* (op til 100, uden Google-verificering).
3. **Credentials → Create credentials → OAuth client ID** → type **Web application** →
   under *Authorized redirect URIs* tilføj `https://<dit-domæne>/auth/callback` → Create.
   Kopiér **Client ID** og **Client secret**.
4. Sæt variabler på Railway:
   ```bash
   railway variable set GOOGLE_OAUTH_CLIENT_ID=<client-id> --service economic-mcp --skip-deploys
   railway variable set GOOGLE_OAUTH_CLIENT_SECRET --stdin --service economic-mcp --skip-deploys
   railway variable set MCP_ALLOWED_DOMAINS=firma.dk --service economic-mcp
   # og/eller: MCP_ALLOWED_EMAILS=revisor@ekstern.dk,bogholder@firma.dk
   ```
   Allowlisten er obligatorisk for Google login. Uden den kunne enhver med en Google-konto
   logge ind på dit regnskab.

### 3B. Microsoft login

1. Gå til [portal.azure.com](https://portal.azure.com) → **Microsoft Entra ID → App registrations → New registration**.
   Navn fx `e-conomic MCP`. Vælg **Accounts in this organizational directory only**.
   Redirect URI: platform **Web**, værdi `https://<dit-domæne>/auth/callback`. → Register.
2. Notér **Application (client) ID** og **Directory (tenant) ID** fra oversigten.
3. **Expose an API → Add** (Application ID URI; accepter standarden `api://<client-id>`) →
   **Add a scope**: navn `access_as_user`, *Who can consent: Admins and users*, udfyld
   visningsnavn og beskrivelse → Add scope.
4. **Manifest**: sæt `"requestedAccessTokenVersion": 2` (ligger under `api` i nyere
   portaler) og gem.
5. **API permissions → Add a permission → My APIs** → vælg appen → `access_as_user` →
   Add. Klik **Grant admin consent** for at spare brugerne for en ekstra dialog.
6. **Certificates & secrets → New client secret** → kopiér **Value** (vises kun én gang).
7. Sæt variabler på Railway:
   ```bash
   railway variable set AZURE_CLIENT_ID=<client-id> AZURE_TENANT_ID=<tenant-id> --service economic-mcp --skip-deploys
   railway variable set AZURE_CLIENT_SECRET --stdin --service economic-mcp
   ```
   Valgfrit: `MCP_ALLOWED_EMAILS` for at begrænse yderligere inden for organisationen.
   Har du kaldt scopet noget andet end `access_as_user`, så sæt `AZURE_API_SCOPE`.

### 3C. E-mail og kodeord (uden Google og Microsoft)

Serveren viser sin egen login-side, når en klient forbinder. Brugerne er variabler, og
kodeordene gemmes kun som hash.

1. Opret en bruger:
   ```bash
   python scripts/new_user.py anna anna@firma.dk --service economic-mcp
   ```
   Scriptet viser Annas kodeord én gang og den `railway variable set MCP_USER_ANNA ...`-
   kommando, der gemmer brugeren. Giv Anna kodeordet gennem en sikker kanal.
2. Gentag for hver person. Slet variablen for at fjerne en bruger; kør scriptet igen for at
   give et nyt kodeord.
3. Første gang Anna forbinder (connector i claude.ai, Claude Desktop, `/mcp` i Claude Code
   eller `codex mcp login`), åbner login-siden i browseren. Siden viser altid, hvilken
   adresse brugeren sendes tilbage til (fx `https://claude.ai` eller `http://localhost`);
   genkender man den ikke, skal man ikke logge ind. Bruger I kun Claude, så sæt
   `MCP_ALLOWED_CLIENT_REDIRECT_URIS=http://localhost:*,http://127.0.0.1:*,https://claude.ai/*`,
   så andre destinationer afvises helt. Fem forkerte forsøg låser e-mailen i 15 minutter.
4. Sessioner: klienten fornyer adgangen i baggrunden, så brugeren ser intet. Et login
   holder 30 dage og forlænges hver gang det bruges; bruger man serveren mindst én gang
   om måneden, logger man aldrig ind igen. Justér med `MCP_LOGIN_SESSION_DAYS` (1–365) og
   `MCP_LOGIN_ACCESS_TOKEN_MINUTES` (5–1440, standard 60). Kræver volumen fra trin 2.

Sikkerhedsmæssigt er det et hak under Google og Microsoft: der er ingen to-faktor, og
"glemt kodeord" klares af administratoren. Har I Workspace eller Microsoft 365, så brug dem.

### Tjek igen

```bash
python scripts/doctor.py --public-url https://<dit-domæne>
railway logs --service economic-mcp     # "Authentication: Google login, allowlist: ..." eller "e-mail login for 3 user(s)"
```

Ved login viser serveren først en kort samtykkeside (hvilken klient der vil forbinde),
derefter Google/Microsofts login. Afviste konti får beskeden *access_denied*.

---

## Trin 4: Forbind dine klienter

Serverens MCP-adresse er `https://<dit-domæne>/mcp`.

**Claude Code**
```bash
claude mcp add --transport http --scope user economic https://<dit-domæne>/mcp
```
Kør derefter `/mcp` i Claude Code og vælg *economic* for at logge ind i browseren.
Bruger du adgangsnøgle: tilføj `--header "Authorization: Bearer <din nøgle>"`.

**claude.ai og Claude Desktop**
Settings → **Connectors** → **Add custom connector** → indsæt adressen → Add → **Connect**
og log ind. På Team/Enterprise tilføjer en ejer connectoren under *Organization settings →
Connectors*, hvorefter hvert medlem klikker Connect. Custom connectors kræver personligt
login (Google/Microsoft); adgangsnøgle alene virker her kun via `mcp-remote`
(se README).

**Codex (CLI og IDE)**
```bash
codex mcp add economic --url https://<dit-domæne>/mcp
codex mcp login economic
```
Med adgangsnøgle: sæt `bearer_token_env_var = "ECONOMIC_MCP_TOKEN"` under
`[mcp_servers.economic]` i `~/.codex/config.toml` og eksportér variablen i din shell.

**Cursor, Windsurf og andre med Streamable HTTP** (`.mcp.json` / `mcp.json`):
```json
{
  "mcpServers": {
    "economic": { "type": "http", "url": "https://<dit-domæne>/mcp" }
  }
}
```
Med adgangsnøgle tilføjes `"headers": {"Authorization": "Bearer ${ECONOMIC_MCP_TOKEN}"}`.

---

## Trin 5: Første test, og hvornår du slår skrivning til

Prøv i din klient:

- *"Hvad hedder mit firma i e-conomic, og hvilket aftalenummer har det?"*
- *"Vis mine forfaldne fakturaer sorteret efter beløb."*
- *"Hvad er saldoen på konto 1010 i regnskabsåret 2026?"*

Serveren kører i **read-only** indtil du ændrer det. Når du er tryg ved svarene og har
testet i et demo- eller prøveregnskab:

```bash
railway variable set MCP_READ_ONLY=false --service economic-mcp
```

Skriveværktøjerne (opret kunde/produkt/fakturakladde, bogfør, slet, bilag) bliver
synlige. Begræns dem til de personer, der faktisk bogfører:

```bash
railway variable set MCP_WRITE_USERS=cfo,anna@firma.dk --service economic-mcp
```

Alle andre beholder læseadgang. Klienterne får at vide, at værktøjerne ændrer data, og vil
normalt bede dig bekræfte. Slå aldrig automatisk godkendelse af skriveværktøjer til.
**Bogføring (`book_draft_invoice`, `register_invoice_as_sent`) kan ikke fortrydes.**

---

## Trin 5b: Installér de færdige skills

Repoet indeholder syv skills, der gør assistenten til en bedre regnskabsmedhjælper:
debitoropfølgning med rykkerudkast, månedsrapport, kundeoverblik, kontoudtog og
afstemning, præcise datasvar, fakturakladder og finansbilag. Se
[skills/README.md](skills/README.md) for detaljer.

**Claude Code** (som plugin, én gang pr. maskine):

```
/plugin marketplace add inbound-cph/economic-mcp-byinboundcph
/plugin install economic@economic-mcp
```

**Claude Code og Codex** (kopiér som personlige skills):

```bash
python scripts/install_skills.py
```

Herefter kan du fx skrive *"lav en debitoropfølgning"* eller *"opret en fakturakladde
til Nordisk Byg på 3 timers rådgivning"*, og assistenten følger den rigtige arbejdsgang.
Skriveskills viser altid et forslag først og bogfører aldrig uden et udtrykkeligt ja.

---

## Trin 6: Sikkerhedstjekliste

- [ ] `MCP_ALLOWED_DOMAINS`/`MCP_ALLOWED_EMAILS` indeholder kun de personer, der skal have adgang.
- [ ] e-conomic-appen har den mindste rolle, der dækker behovet.
- [ ] Hver person har sin egen adgangsnøgle (`MCP_AUTH_TOKEN_<NAVN>`), og nøgler til folk, der er stoppet, er slettet.
- [ ] `MCP_READ_ONLY=true` indtil skriveflowet er testet, og derefter `MCP_WRITE_USERS` med kun dem, der bogfører.
- [ ] `.env` er ikke i git (er dækket af `.gitignore`).
- [ ] Der er en Railway-volume (`/data`), så login-sessioner ikke nulstilles ved deploy.
- [ ] Du ved hvordan du trækker adgang tilbage: fjern personen fra allowlisten, roter
      client secret hos Google/Microsoft, eller tilbagekald appens adgang i e-conomic.
- [ ] Du kigger i `railway logs` af og til: hvert kald logges med bruger, værktøj og resultat.

---

## Kør lokalt (uden Railway)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Sæt i `.env` enten en adgangsnøgle (`MCP_AUTH_TOKEN_<DITNAVN>`, 32+ tegn) eller, kun til leg på din egen maskine,
`MCP_ALLOW_UNAUTHENTICATED=true` (serveren lytter så kun på 127.0.0.1). Start:

```bash
python server.py
python scripts/doctor.py
```

Adressen er `http://127.0.0.1:8000/mcp`. Personligt login kan også testes lokalt med
`MCP_PUBLIC_URL=http://localhost:8000` og redirect-URI `http://localhost:8000/auth/callback`
hos Google/Microsoft.

---

## Opdatering

Kører du fra en klon med Railway CLI: `git pull` efterfulgt af `railway up --detach`.
Kører du fra et fork på GitHub: hent ændringerne ind i dit fork; Railway deployer selv.

---

## Fejlfinding

| Symptom | Årsag og løsning |
|---|---|
| Deploy crasher med *"refuses to start"* | Ingen adgangsmetode sat. Tilføj en `MCP_AUTH_TOKEN_<NAVN>`-nøgle eller Google/Microsoft-variabler. |
| *"Invalid authentication configuration: ..."* i loggen | Beskeden fortæller præcis hvilken variabel der mangler eller er ugyldig. |
| Login-siden siger *access_denied* | Kontoen er ikke på allowlisten (eller e-mailen er ikke verificeret hos Google). Tilføj adressen/domænet. |
| E-mail-login: *For mange forsøg* | Fem forkerte kodeord låste e-mailen/IP-adressen i 15 minutter. |
| E-mail-login: *Login-siden er udløbet* | Linket gælder 10 minutter og én gang. Start forbindelsen igen fra klienten. |
| Google: *redirect_uri_mismatch* | Redirect-URI'en i Google Cloud skal være præcis `https://<dit-domæne>/auth/callback`. |
| Microsoft: *AADSTS65001* eller *AADSTS650057* | Scopet mangler under *API permissions*, eller `requestedAccessTokenVersion` er ikke 2. |
| Klienten bliver ved med at bede om login efter deploy | Ingen volume: login-sessioner nulstilles. Tilføj en volume (trin 2). |
| `401` fra e-conomic | Forkerte tokens, eller adgangen er tilbagekaldt. Test med `curl .../self` (trin 1). |
| Skriveværktøjer mangler i klienten | `MCP_READ_ONLY=true`. Det er med vilje; se trin 5. |
| `429`/`5xx` fra e-conomic | Serveren prøver selv igen med backoff. Vedvarende fejl: se `logId` i fejlbeskeden og kontakt e-conomic. |
