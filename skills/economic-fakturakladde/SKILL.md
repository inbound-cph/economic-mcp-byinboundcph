---
name: economic-fakturakladde
description: Opret en fakturakladde i e-conomic ud fra en beskrivelse af kunde, ydelser eller produkter, antal, priser og datoer, med korrekte referencer (kundenummer, produktnummer, layout, betalingsbetingelse, momszone) og en kontrol før noget oprettes. Brug dette skill når brugeren vil fakturere, oprette, lave, skrive eller sende en faktura eller regning, fakturere timer, et projekt eller et abonnement, rette en fakturakladde, hente en faktura som PDF, eller bogføre og sende en kladde – også ved korte beskeder som "send en faktura til X på 12.500 kr".
---

# Fakturakladde i e-conomic

En fakturakladde er ufarlig: den kan rettes og slettes, og den påvirker ikke
regnskabet før den bogføres. Bogføring er derimod endelig. Hele skillet er bygget op om
den forskel: vær hurtig og hjælpsom med kladden, og vær omhyggelig og eksplicit, før
noget bogføres.

## Spilleregler

- Opret aldrig noget, før brugeren har set et forslag med kunde, linjer og totaler og
  sagt ja. Ét ja gælder én kladde (eller én liste af kladder, hvis brugeren har bedt om
  flere på én gang).
- Bogfør kun (`book_draft_invoice`, `register_invoice_as_sent`) når brugeren
  udtrykkeligt beder om det for en bestemt kladde. Gentag nummer, kunde og beløb i
  spørgsmålet, og skriv at det ikke kan fortrydes.
- Gæt ikke referencer. Kundenummer, produktnummer, layout, betalingsbetingelse og
  momszone slås op. Findes de ikke, så spørg eller foreslå at oprette dem.
- Mangler skriveværktøjerne, kører serveren i read-only (`MCP_READ_ONLY=true`) eller
  med demo-tokens. Forklar det i stedet for at prøve igen.
- Priser er ekskl. moms (`unitNetPrice`). Sig det, når du viser totaler.

## Fremgangsmåde

1. **Afklar det nødvendige** (spørg kun om det, der mangler): kunde, linjer
   (beskrivelse, antal, enhedspris, evt. rabat), fakturadato (standard i dag),
   betalingsbetingelse (standard kundens egen), eventuel overskrift/tekst, valuta
   (standard kundens).
2. **Kunden**: `list_customers(filter="name$like:<navn>")`; ved flere match vis
   dem og spørg. `get_customer(customer_number)` giver `name`, `currency`,
   `paymentTerms.paymentTermsNumber`, `vatZone.vatZoneNumber`, `layout.layoutNumber`
   og `email`. Har kunden intet layout, så hent `list_layouts` og vælg standardlayoutet
   eller spørg.
3. **Produkter**: hver linje skal have et `productNumber`, der findes på aftalen.
   Søg med `list_products(filter="name$like:<ord>")`. Mange virksomheder har et generelt
   produkt som "Konsulenttimer" eller "Diverse"; foreslå det, hvis intet præcist findes.
   Findes intet brugbart, så foreslå `create_product` (kræver produktgruppe fra
   `list_product_groups`) og vent på ja.
4. **Vis forslaget** i denne form og vent på bekræftelse:
   ```
   Fakturakladde til <kunde> (kundenr. <nr>), dato <dato>, <betalingsbetingelse>
   | Produktnr. | Beskrivelse | Antal | Enhedspris | Rabat | Linjetotal |
   Netto <beløb> · Moms (<sats> %, <momszone>) ca. <beløb> · Brutto ca. <beløb>
   Opretter jeg kladden? (Den bogføres ikke.)
   ```
5. **Opret** med `create_draft_invoice(customer_number, currency, date, layout_number,
   payment_terms_number, recipient_name, recipient_vat_zone_number, lines, notes_heading)`.
   `lines` er en liste af `{"productNumber": "...", "description": "...", "quantity": 2,
   "unitNetPrice": 1250.0, "discountPercentage": 10}` (rabat er valgfri).
6. **Rapportér** resultatet: `draftInvoiceNumber`, `netAmount`, `vatAmount`,
   `grossAmount`, `dueDate`. Tilbyd PDF: `get_draft_invoice_pdf(draft_invoice_number)`
   returnerer base64; gem den som `faktura-kladde-<nr>.pdf` og fortæl hvor.
7. **Rettelser**: `update_draft_invoice(draft_invoice_number, updates)`. Ændres linjer,
   skal hele `lines`-listen sendes med igen; hent kladden først med `get_draft_invoice`.
   Slet med `delete_draft_invoice` kun på udtrykkelig anmodning.
8. **Bogføring og afsendelse**, kun når brugeren beder om det:
   - `book_draft_invoice(draft_invoice_number)` bogfører uden at sende.
   - `register_invoice_as_sent(draft_invoice_number, send_by="Email")` bogfører og
     sender via e-conomic til kundens fakturamail; `send_by="ean"` sender som e-faktura
     (kræver EAN-nummer på kunden).
   Spørg: "Skal jeg bogføre kladde nr. <nr> til <kunde> på <brutto>? Det kan ikke
   fortrydes." Bogfør først efter et klart ja. Rapportér `bookedInvoiceNumber`.

## Flere fakturaer på én gang

Ved fx "fakturér alle kunder på listen": lav én samlet oversigt over alle kladder,
få ét ja, opret dem én ad gangen og vis en tabel med kladdenummer og beløb pr. kunde.
Stopper e-conomic med en valideringsfejl, så vis fejlens `developerHint` og fortsæt
med de øvrige, medmindre brugeren siger stop.
