---
name: economic-debitorer
description: Prioriteret overblik over forfaldne og ubetalte fakturaer i e-conomic med aldersfordeling, kontaktoplysninger og udkast til rykkere. Brug dette skill hver gang brugeren nævner forfaldne fakturaer, debitorer, rykkere, udestående, restancer, manglende betaling, betalingsopfølgning, aldersfordeling, "hvem skylder os penge", "hvad har vi til gode" eller overdue/unpaid invoices – også når de ikke siger e-conomic, men har e-conomic-værktøjerne tilgængelige.
---

# Debitoropfølgning i e-conomic

Målet er en liste, brugeren kan handle på i dag: hvem skylder hvad, hvor længe har det
stået, og hvad er det rigtige næste skridt pr. kunde. Tallene skal være komplette og
sporbare, for brugeren ringer måske til kunden med dem.

## Spilleregler

- Brug e-conomic MCP-værktøjerne til alle tal. Gæt aldrig, og udelad ingen sider:
  værktøjerne returnerer højst `page_size` rækker (op til 1000) og en `pagination`-blok.
  Forøg `skip_pages`, indtil `pagination.nextPage` mangler, før du summerer.
- Summer og aldersfordeling regnes i basisvaluta (`remainderInBaseCurrency`), så
  fakturaer i fx USD og DKK kan lægges sammen. Vis den enkelte faktura i sin egen
  valuta (`remainder` + `currency`) og nævn omregningen.
- Skriv altid hvilken dato tallene er hentet. Betalinger, der er registreret i dag, kan
  mangle i e-conomic, så bed brugeren tjekke banken før rykker nr. 2.
- Talformat følger modtageren: dansk format (12.345,00 DKK) i rapporten og i danske
  udkast, engelsk format (DKK 12,345.00) i udkast på engelsk.
- Dette skill sender aldrig noget. Det laver udkast, som brugeren selv sender.

## Fremgangsmåde

1. **Overblik først**: `get_invoice_totals` giver samlet ubetalt og forfaldent for
   aftalen (`overdue.grossRemainderInBaseCurrency`). Brug det som kontrolsum for din
   egen sammentælling, og skriv om de stemmer.
2. **Hent alle forfaldne fakturaer** med `list_overdue_invoices(page_size=1000)` og
   paginer. Felter pr. faktura: `bookedInvoiceNumber`, `date`, `dueDate`, `remainder`,
   `remainderInBaseCurrency`, `grossAmount`, `currency`, `customer.customerNumber`,
   `recipient.name`.
   - **Kreditnotaer** optræder med negativt `remainder`. Tag dem ud af rykkerlisten,
     vis dem separat, og foreslå modregning mod kundens åbne fakturaer.
   - **Delvist betalte** fakturaer har `remainder` mindre end `grossAmount`. Vis
     restbeløbet og nævn, at der er betalt en del.
   Vil brugeren også se ikke-forfaldne ubetalte, så brug `list_unpaid_invoices`.
3. **Beregn** dage siden forfald (dags dato minus `dueDate`) pr. faktura og placér i
   intervaller, der matcher anbefalingerne: 1–14, 15–30, 31–60, over 60 dage. Gruppér
   pr. kunde med antal fakturaer, samlet restbeløb i basisvaluta, ældste forfaldsdato og
   "Dage" = dage siden ældste forfald. Sortér efter samlet restbeløb. Kundens
   `dueAmount` fra `get_customer` er et godt krydstjek pr. kunde.
4. **Kontaktoplysninger** hentes kun for de kunder, brugeren vil kontakte:
   `get_customer(customer_number)` giver `email`, `telephoneAndFaxNumber`, `balance`
   og `dueAmount`. Interne noter ligger på kontaktpersonerne:
   `list_customer_contacts(customer_number)` giver `name`, `email`, `phone` og `notes`
   (fx "skriv på engelsk" eller "fakturaer til kreditorbogholderiet"). Læs dem, før du
   skriver et udkast, og følg dem.
5. **Anbefal et næste skridt pr. kunde** ud fra alder og beløb: venlig påmindelse
   (1–14 dage), rykker 1 (15–30 dage), rykker 2 med gebyr (31–60 dage), telefonopkald
   og inkassovarsel (over 60 dage eller store beløb). Store, mangeårige kunder
   fortjener et opkald frem for en automatisk rykker. Sig det, når det er relevant.
6. **Skriv udkast** til de påmindelser/rykkere, brugeren beder om. Kort, venligt og
   konkret: fakturanummer, fakturadato, beløb, forfaldsdato, betalingsoplysninger og
   hvad der sker næste gang. Afsendervirksomhed og bankoplysninger findes i
   `get_company_info` (`company.name`, `settings.baseCurrency` og `bankInformation` med
   `bankName`, `bankSortCode` (reg.nr.), `bankAccountNumber`, `ibanNumber`, `swiftCode`).
   Skriv, at brugeren bør tjekke, at de matcher det, der står på fakturaen, før udkastet
   sendes.

## Dansk praksis for rykkere

Efter rentelovens § 9b må der opkræves rykkergebyr på højst 100 kr. pr. rykker, højst
tre rykkere for samme ydelse, og der skal gå mindst 10 dage mellem rykkerne. Nævn
gebyret i udkastet til rykker 2 og 3, ikke i den første venlige påmindelse. Er brugeren
i tvivl om renter eller inkasso, så henvis til deres revisor eller inkassofirma frem
for at gætte.

## Rapportformat

Brug denne struktur:

```
# Debitoropfølgning – <dags dato>

## Hovedtal
- Forfaldent i alt: <beløb i basisvaluta> fordelt på <n> fakturaer hos <k> kunder
  (stemmer med get_invoice_totals: ja/nej)
- Ubetalt i alt (inkl. ikke-forfaldent): <beløb>
- Kreditnotaer til modregning: <beløb> (<n> stk.)

## Aldersfordeling (dage siden forfald)
| 1–14 | 15–30 | 31–60 | over 60 |

## Pr. kunde (sorteret efter restbeløb)
| Kunde (nr.) | Fakturaer | Restbeløb | Ældste forfald | Dage | Anbefaling |

## Udkast
<påmindelser/rykkere efter behov, på modtagerens sprog>

## Forbehold
- Tal hentet <tidspunkt>. Betalinger registreret i dag kan mangle.
- <valutaomregning, delvise betalinger, kreditnotaer>
```

Hvis der ikke er noget forfaldent, så sig det kort og vis i stedet, hvad der forfalder
inden for de næste 14 dage (fra `list_not_due_invoices`), så brugeren kan komme foran.
