---
name: economic-maanedsrapport
description: Ledelsesrapport for en måned, et kvartal eller et regnskabsår ud fra e-conomic – omsætning, resultat, udvikling mod forrige periode, debitorer, likviditet og største kunder. Brug dette skill når brugeren beder om månedsrapport, kvartalsrapport, årsoverblik, "hvordan gik sidste måned", resultatopgørelse, P&L, nøgletal, omsætning pr. kunde eller periode, budgetopfølgning, eller en status til ledelsen, bestyrelsen, banken eller revisoren. Brug det også ved løsere formuleringer som "giv mig et overblik over økonomien".
---

# Måneds- og periodeoverblik fra e-conomic

En god rapport svarer på tre spørgsmål: Hvordan gik det? Hvordan står vi? Hvad skal
vi holde øje med? Tallene skal kunne føres tilbage til e-conomic, og alle forbehold
skal stå tydeligt, for rapporten bliver måske sendt videre til en bank eller bestyrelse.

## Spilleregler

- Alle tal kommer fra e-conomic MCP-værktøjerne. Paginer, indtil `pagination.nextPage`
  mangler; brug `page_size=1000` på totaler og posteringer.
- e-conomics fortegn: indtægter (omsætning) står som negative beløb på kontototaler,
  udgifter som positive. Vend fortegnet, når du præsenterer, og skriv det i forbeholdene.
- Regnskabsår kan være forskudte (`"2025/2026"`). Brug altid `year`-strengen præcis
  som `list_accounting_years` returnerer den.
- Ubogførte fakturakladder og kassekladdeposter er ikke med i totalerne. Tæl dem og
  nævn det.
- Angiv altid periode, hentetidspunkt og valuta (aftalens basisvaluta fra
  `get_company_info` → `settings.baseCurrency`).
- Kontototaler og fakturalister med `page_size=1000` bliver store (over 100.000 tegn).
  Aggregér dem med et lille Python- eller jq-script i stedet for at læse dem råt.

## Fremgangsmåde

1. **Afklar perioden.** Standard er sidste hele måned. Find regnskabsåret med
   `list_accounting_years` og perioden med `list_accounting_year_periods(year)`;
   perioder har `periodNumber`, `fromDate`, `toDate`. Kvartaler og år-til-dato er
   summer af perioder.
2. **Kontoplan**: `list_accounts(page_size=1000)` giver `accountNumber`, `name`,
   `accountType` (`profitAndLoss`, `status`, `heading`, `totalFrom`, `sumInterval`,
   `sumAlpha`), `balance` og `totalFromAccount`. Sum-konti (`totalFrom`/`sumInterval`)
   følger virksomhedens egen opstilling ("Omsætning i alt", "Bruttoresultat",
   "Resultat før skat"). Brug dem til hovedtallene i stedet for at opfinde din egen
   gruppering, og vis de underliggende konti kun, hvor det forklarer noget.
3. **Resultat for perioden**: `get_accounting_period_totals(year, period_number,
   page_size=1000)` giver `totalInBaseCurrency` pr. konto. Gør det samme for
   sammenligningsperioden (forrige måned og samme måned året før, hvis den findes).
   For kvartal/år: summer periodetotaler eller brug `get_accounting_year_totals`.
4. **Balance og likviditet**: `balance` på statuskonti fra `list_accounts` er saldoen
   i dag (ikke ved periodens slutning). Vis bank/kasse, debitorer (fx konto for
   tilgodehavender) og kreditorer, og skriv at det er dags dato-saldi.
5. **Debitorer**: `get_invoice_totals` (ubetalt, forfaldent). Nævn de tre største
   forfaldne poster fra `list_overdue_invoices`, hvis der er nogen.
6. **Kunder**: `list_booked_invoices(filter="date$gte:<fra>$and:date$lte:<til>",
   page_size=1000)`, gruppér `netAmountInBaseCurrency` pr. `customer.customerNumber`
   (kreditnotaer er negative og skal med) og navngiv via `recipient.name`. Top 5 og
   deres andel af omsætningen.
7. **Kontrol**: `economic_api_request("GET", "/invoices/totals/last-month")` (også
   `this-month`, `this-year`, `last-year`) giver antal og beløb for bogførte fakturaer og
   er et uafhængigt facit for salgstallene. Afviger fakturaomsætningen fra
   omsætningskontiene, så vis begge og forklar kort (manuelle posteringer,
   periodiseringer, bogføringsdatoer). Tæl desuden `list_draft_invoices` og ubogførte
   poster med `list_journals` + `get_journal_vouchers`; er der mange, så advar om at
   tallene ikke er endelige.
8. **Skriv rapporten** med korte forklaringer af de største afvigelser. Fremhæv
   ting brugeren bør reagere på (faldende omsætning, stigende forfald, lav likviditet).

## Rapportformat

```
# <Virksomhed> – <periode>
Hentet fra e-conomic <dato/tid>. Beløb i <valuta>, ekskl. moms.

## Hovedtal
| | <periode> | <forrige periode> | <samme periode året før> | Ændring |
| Omsætning | | | | |
| Bruttoresultat | | | | |
| Resultat før skat | | | | |

## Resultatopgørelse (sammendrag efter kontoplanens sum-konti)

## Debitorer og likviditet (saldi dags dato)

## Største kunder i perioden
| Kunde | Omsætning | Andel |

## Bemærkelsesværdigt
- <3–6 punkter: afvigelser, engangsposter, risici>

## Datagrundlag og forbehold
- <ubogførte kladder, forskudt regnskabsår, fortegn, hvad der mangler>
```

Bliver brugeren bedt om at sende rapporten videre, så tilbyd også en kort version på
fem linjer, som kan stå øverst i en mail.
