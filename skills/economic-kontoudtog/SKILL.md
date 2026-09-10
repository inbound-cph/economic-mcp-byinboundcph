---
name: economic-kontoudtog
description: Træk posteringer for en konto eller et helt regnskabsår fra e-conomic, filtrér på periode, tekst, beløb eller bilagsnummer, summér, vis løbende bevægelser og afstem mod fx et bankudskrift. Brug dette skill når brugeren spørger om posteringer, kontoudtog, bevægelser eller saldo på en konto, kontoplanen, bilagsnumre, afstemning (bank, mellemregning, moms), "find posteringen på 4.500 kr.", "hvad er bogført på konto 2800 i august", eller vil have posteringer eksporteret til CSV eller Excel.
---

# Kontoudtog og afstemning i e-conomic

Bogholderen skal kunne stole på hver linje: rigtig konto, rigtigt regnskabsår, alle
sider hentet, og fortegn forklaret. Det vigtigste output er ofte ikke summen, men den
enkelte postering brugeren leder efter.

## Spilleregler

- Slå kontoen op i kontoplanen, før du henter posteringer. Kontonumre er ikke ens på
  tværs af virksomheder.
- `get_account_entries` kræver et regnskabsår. Brug `year`-strengen præcis som
  `list_accounting_years` returnerer den (fx `"2026"` eller `"2025/2026"`).
- Paginer, indtil `pagination.nextPage` mangler. Brug `page_size=1000`.
- Fortegn: debet er positivt, kredit negativt i `amount`/`amountInBaseCurrency`.
  Indtægtskonti har derfor negative bevægelser. Forklar det én gang i output.
- Åbningssaldo for en periode midt i året kan ikke slås direkte op med disse værktøjer.
  Vis periodens bevægelser og kontoens saldo dags dato (`balance` fra `get_account`),
  og skriv tydeligt hvad der er hvad.

## Fremgangsmåde

1. **Find kontoen**: `list_accounts(filter="name$like:<ord>", page_size=1000)` eller
   `filter="accountNumber$eq:<nr>"`. Felter: `accountNumber`, `name`, `accountType`,
   `balance`, `vatAccount`, `blockDirectEntries`. Er der flere kandidater, så vis dem.
2. **Vælg regnskabsår** med `list_accounting_years` (`year`, `fromDate`, `toDate`,
   `closed`). Spænder brugerens periode over to regnskabsår, så hent begge.
3. **Hent posteringer**: `get_account_entries(account_number, accounting_year,
   filter=..., page_size=1000)`. Felter pr. postering: `entryNumber`, `date`, `text`,
   `amount`, `amountInBaseCurrency`, `currency`, `voucherNumber`, `entryType`
   (fx `customerInvoice`, `supplierInvoice`, `financeVoucher`, `customerPayment`),
   `vatAccount`, samt `customer`/`supplier` hvor det giver mening.
   Nyttige filtre (kombinér med `$and:`):
   - Periode: `date$gte:2026-08-01$and:date$lte:2026-08-31`
   - Tekst: `text$like:Netto`
   - Beløb: `amount$eq:-4500` (husk fortegn) eller `amount$gte:4000$and:amount$lte:5000`
   - Bilag: `voucherNumber$eq:1234`
   På tværs af konti: `get_accounting_year_entries(year, filter="text$like:...")`
   eller `filter="account.accountNumber$in:[2800,2810]"` (firkantede klammer).
4. **Bearbejd**: sortér efter dato, vis løbende sum af bevægelser, gruppér pr. måned
   eller `entryType` hvis brugeren vil have overblik. Ved "find posteringen": vis alle
   match med bilagsnummer og modkonto, hvis den kan udledes af samme bilagsnummer via
   `get_accounting_year_entries(year, filter="voucherNumber$eq:<nr>")`.
5. **Afstemning** (bank, mellemregning, moms): bed om modpartens linjer (fx bank-CSV
   indsat i chatten eller som fil). Match på beløb og dato inden for ±3 dage, derefter
   på tekst. Vis tre lister: matchet, kun i e-conomic, kun i banken. Foreslå
   posteringer for det, der mangler, men opret dem ikke her; henvis til skillet
   `economic-bilag`.
6. **Eksport**: skriv en CSV med semikolon som separator og komma som decimaltegn
   (Excel på dansk åbner den direkte). Kolonner: Dato;Bilag;Tekst;Type;Beløb;Valuta;
   Løbende. Fortæl hvor filen ligger.

## Format

```
# Konto <nr> <navn> – <periode>
Regnskabsår <year>. Hentet fra e-conomic <dato/tid>. Debet positivt, kredit negativt.

Saldo dags dato: <balance>   ·   Bevægelser i perioden: <sum> (<n> posteringer)

| Dato | Bilag | Tekst | Type | Beløb | Løbende |

## Bemærkninger
- <fx dubletter, runde beløb uden tekst, posteringer på lukkede datoer>
```

Er kontoen spærret for direkte posteringer (`blockDirectEntries: true`), så nævn det,
hvis brugeren senere vil rette noget på den.
