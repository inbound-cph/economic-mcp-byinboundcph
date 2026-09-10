---
name: economic-kundeoverblik
description: Komplet overblik over én kunde i e-conomic – stamdata, kontaktpersoner, saldo, fakturahistorik pr. år, åbne poster, kladder, tilbud og ordrer. Brug dette skill når brugeren nævner en kundes navn eller kundenummer og vil vide noget om kunden, forbereder et kundemøde eller en forhandling, spørger "hvad har vi solgt til X", "skylder X os noget", "hvornår handlede X sidst", "hvad er X's e-mail/CVR", eller beder om en kundeprofil eller kundehistorik.
---

# Kundeoverblik fra e-conomic

Brugeren skal kunne gå ind til mødet eller telefonsamtalen med det hele på én side:
hvem kunden er, hvad de køber, hvad de skylder, og om noget kræver handling.

## Spilleregler

- Slå kunden op, gæt ikke. Er der flere match, så vis dem (nummer, navn, by, saldo)
  og spørg, hvem der menes.
- Paginer alle lister, indtil `pagination.nextPage` mangler. Kundens fakturahistorik
  kan være lang; brug `page_size=1000`.
- Beløb i kundens valuta (`currency` på kunden) med dansk format og to decimaler.
- Personoplysninger (kontaktpersoners e-mail og telefon) er til brugerens eget arbejde
  med kunden. Kopiér dem ikke ind i output, der skal videre til tredjepart.

## Fremgangsmåde

1. **Find kunden**: `list_customers(filter="name$like:<del af navn>")`. Kendes
   kundenummer eller CVR, brug `customerNumber$eq:<nr>` eller
   `corporateIdentificationNumber$eq:<cvr>`.
2. **Stamdata**: `get_customer(customer_number)` giver `name`, `address`, `zip`,
   `city`, `country`, `email`, `telephoneAndFaxNumber`, `corporateIdentificationNumber`,
   `currency`, `paymentTerms`, `vatZone`, `customerGroup`, `creditLimit`, `balance`
   (skyldigt i alt), `dueAmount` (forfaldent) og `lastUpdated`.
3. **Kontaktpersoner**: `list_customer_contacts(customer_number)` giver `name`, `email`,
   `phone` og `notes`. Interne noter om kunden (sprog, hvem der skal have fakturaer,
   særlige aftaler) ligger her og ikke på kunden selv; vis dem under "Værd at bemærke".
4. **Økonomi**: `get_customer_totals(customer_number)` for bogført/kladde-totaler.
   `get_customer_booked_invoices(customer_number, page_size=1000)` for historikken:
   gruppér `netAmountInBaseCurrency` pr. år (så flere valutaer kan lægges sammen; vis
   fakturaens egen valuta i lister), find første og seneste fakturadato, gennemsnitlig
   fakturastørrelse, og list åbne fakturaer (`remainder > 0`) med `dueDate`. Negative
   `remainder` er kreditnotaer; vis dem som "til modregning".
   e-conomic oplyser ikke betalingsdato via disse værktøjer; sig det, hvis brugeren
   spørger om betalingsmønster, og brug i stedet forfald vs. restbeløb som indikator.
5. **Igangværende**: `get_customer_draft_invoices(customer_number)`,
   `list_draft_quotes(filter="customer.customerNumber$eq:<nr>")`,
   `list_sent_quotes`, `list_draft_orders` og `list_sent_orders` filtreret på samme
   måde, når de findes på aftalen.
6. **Hvad kunden køber**: Hent linjer for de seneste 5–10 fakturaer med
   `get_booked_invoice(booked_invoice_number)` og opsummer produkter/ydelser. Spring
   dette over, hvis brugeren kun vil have tal.
7. **Signalér handling**: forfaldne beløb, overskredet kreditmaksimum
   (`balance` vs. `creditLimit`), længe siden sidste køb, manglende e-mail/CVR.

## Format

```
# <Kundenavn> (kundenr. <nr>)
Hentet fra e-conomic <dato/tid>.

## Stamdata
Adresse · CVR · E-mail · Telefon · Betalingsbetingelse · Valuta · Kundegruppe · Kreditmaks

## Kontaktpersoner
| Navn | E-mail | Telefon | Note |

## Økonomi
- Saldo: <beløb>  · Forfaldent: <beløb>
- Omsætning pr. år: <tabel>
- Første faktura: <dato> · Seneste faktura: <dato> · Gns. faktura: <beløb>

## Åbne poster
| Fakturanr. | Dato | Forfald | Restbeløb |

## Igangværende (kladder, tilbud, ordrer)

## Det køber kunden typisk

## Værd at bemærke
- <handlingspunkter>
```

Bed brugeren om lov, før du opretter eller ændrer noget på kunden. Dette skill er et
opslag, ikke en redigering.
