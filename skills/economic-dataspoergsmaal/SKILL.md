---
name: economic-dataspoergsmaal
description: Besvar ad hoc-spørgsmål om regnskabsdata i e-conomic præcist – antal, summer, lister, sammenligninger og opslag på tværs af kunder, leverandører, produkter, fakturaer, tilbud, ordrer, konti og posteringer. Brug dette skill når brugeren stiller et konkret dataspørgsmål til e-conomic ("hvor mange fakturaer sendte vi i august", "hvilke produkter sælger bedst", "hvem er vores største leverandør", "hvad skylder vi i moms"), og intet mere specifikt e-conomic-skill passer. Brug det også når svaret kræver flere værktøjskald, filtre, pagination eller det generiske API-værktøj economic_api_request.
---

# Dataspørgsmål til e-conomic

Et regnskabstal, der er 3 % forkert, er værre end intet tal, fordi brugeren handler
på det. Hent derfor komplette data, brug den rigtige kilde, og vis hvordan tallet er
fundet, så brugeren kan tjekke det.

## Spilleregler

- Paginer altid: `page_size=1000`, forøg `skip_pages` indtil `pagination.nextPage`
  mangler. Sum aldrig på én side.
- Filtrér i e-conomic frem for at hente alt og filtrere selv, når det kan lade sig gøre.
- Skriv svaret først, derefter grundlaget. Angiv periode, hentetidspunkt, valuta og om
  beløb er ekskl. (`netAmount`) eller inkl. moms (`grossAmount`). Summer på tværs af
  fakturaer i basisvaluta (`...InBaseCurrency`-felterne), aldrig ved at lægge
  forskellige valutaer sammen.
- Ved usikkerhed (fx hvilke konti der udgør "omsætning"), så vis hvad du har antaget
  og tilbyd en alternativ opgørelse.

## Hvor tallene bor

| Spørgsmål om | Værktøj | Bemærk |
|---|---|---|
| Fakturaer sendt/bogført i en periode | `list_booked_invoices(filter="date$gte:..$and:date$lte:..")` | `netAmount`/`grossAmount` i fakturaens valuta, `netAmountInBaseCurrency`/`grossAmountInBaseCurrency`/`remainderInBaseCurrency` til summer; kreditnotaer har negative beløb; `customer.customerNumber`, `recipient.name` |
| Ubetalt/forfaldent | `get_invoice_totals`, `list_unpaid_invoices`, `list_overdue_invoices` | brug skillet `economic-debitorer` til opfølgning |
| Fakturatotaler for en periode (facit) | `economic_api_request("GET", "/invoices/totals/last-month")` – også `this-month`, `this-year`, `last-year` | antal og beløb for bogførte fakturaer; brug som uafhængig kontrol af egne summer |
| Fakturalinjer/produkter solgt | `get_booked_invoice(nr)` pr. faktura (linjer) | dyrt ved mange fakturaer; begræns perioden |
| Kunder | `list_customers(filter=...)`, `get_customer` | `balance`, `dueAmount`, `customerGroup` |
| Leverandører | `list_suppliers`, `get_supplier` | leverandørfakturaer/betalinger ligger som posteringer (`entryType` `supplierInvoice`/`supplierPayment`) |
| Produkter og priser | `list_products`, `get_product` | `salesPrice`, `productGroup` |
| Tilbud og ordrer | `list_draft_quotes`, `list_sent_quotes`, `list_archived_quotes`, `list_draft_orders`, `list_sent_orders`, `list_archived_orders` | |
| Resultat/omsætning pr. konto | `get_accounting_period_totals`, `get_accounting_year_totals` | returnerer kun kontonumre; slå navne og `accountType` op i `list_accounts`. Indtægter er negative; vend fortegnet |
| Posteringer | `get_account_entries`, `get_accounting_year_entries` | kræver `year` fra `list_accounting_years` |
| Moms | `list_vat_accounts` + periodetotaler på momskontiene | skyldig moms = udgående minus indgående; henvis til momsangivelsen i e-conomic som facit |
| Stamdata | `list_payment_terms`, `list_vat_zones`, `list_currencies`, `list_layouts`, `list_units`, `list_departments`, `list_employees` | |
| Alt andet | `economic_api_request(method, path, params, body)` | se https://restdocs.e-conomic.com – hold dig til GET medmindre brugeren beder om andet |

## Filtersyntaks

`felt$operator:værdi`, kombineret med `$and:` / `$or:`. Operatorer: `$eq`, `$ne`,
`$gt`, `$gte`, `$lt`, `$lte`, `$like` (delvis match), `$in:[a,b,c]`, `$nin:[a,b,c]`
(lister i firkantede klammer; parenteser giver en syntaksfejl).
Datoer som `YYYY-MM-DD`. Nestede felter med punktum: `customer.customerNumber$eq:42`,
`account.accountNumber$in:[1000,1010]`. Eksempel:
`date$gte:2026-08-01$and:date$lte:2026-08-31$and:customer.customerNumber$eq:42`.

## Store svar

Et kald med `page_size=1000` kan give over 100.000 tegn, som Claude Code gemmer i en fil i
stedet for at vise. Læs ikke den slags råt: aggregér med et lille Python- eller jq-script
(sum, antal, gruppering pr. kunde/konto), og vis kun resultatet. Filtrér så tæt på
spørgsmålet som muligt, så datasættet bliver lille fra start.

## Når to kilder giver forskellige tal

Omsætning ifølge bogførte fakturaer og omsætning ifølge omsætningskontiene stemmer
sjældent helt: kontiene indeholder også manuelle posteringer, periodiseringer og
fakturaer med anden bogføringsdato. Vis begge tal, forklar forskellen kort, og lad
brugeren vælge den definition, der passer til formålet (salgstal vs. regnskab).

"Antal fakturaer" i `list_booked_invoices` inkluderer kreditnotaer (negative beløb).
Rapportér fakturaer og kreditnotaer hver for sig.

Giver et `name$like`-filter uventet 0 resultater, kan navnet indeholde usynlige tegn eller
en anden stavemåde; søg på en anden del af navnet eller list alle og filtrér selv.

## Fremgangsmåde

1. Omsæt spørgsmålet til: hvilke objekter, hvilken periode, hvilket mål (antal, sum,
   gennemsnit, top-N), hvilken valuta.
2. Vælg kilden i tabellen ovenfor. Kræver spørgsmålet linjer fra mange fakturaer, så
   fortæl hvor mange kald det bliver, og spørg om perioden kan begrænses.
3. Hent alle sider, beregn, og krydstjek med en uafhængig total, hvor en findes
   (`get_invoice_totals`, kontototaler, `pagination.results`).
4. Svar kort, vis tabellen, og afslut med "Sådan er tallet fundet" i to-tre linjer plus
   forbehold (ubogførte kladder, valuta, moms, forskudt regnskabsår).

## Format

```
**Svar:** <ét klart tal eller udsagn>

| ... |

Sådan er tallet fundet: <værktøjer, filter, antal poster, periode>
Forbehold: <hvad der ikke er med>
```
