---
name: economic-bilag
description: Registrér manuelle posteringer (finansbilag) i en e-conomic kassekladde: omposteringer, periodiseringer, småudgifter uden leverandørfaktura, bankgebyrer, mellemregning og rettelser af fejlposteringer. Brug dette skill når brugeren vil bogføre eller registrere et bilag, lave en postering eller ompostering, "flyt 5.000 kr. fra konto 3600 til 3610", "bogfør bankgebyret", rette en fejlpostering, eller arbejder med kassekladden, journalen eller ubogførte poster.
---

# Finansbilag i e-conomic kassekladden

Et bilag oprettet her lander som en ubogført post i kassekladden. Selve bogføringen
sker i e-conomic-brugerfladen, så en bogholder altid kan kigge på den først. Det gør
værktøjet forholdsvis sikkert, men en forkert post i kladden koster stadig andres tid,
så forslaget skal være rigtigt første gang.

## Spilleregler

- Vis altid posteringen som debet/kredit med kontonumre og -navne, og vent på ja, før
  du opretter den.
- Gæt aldrig konti. Slå dem op og vis kandidaterne, hvis der er flere.
- Fortegn: `amount` er positivt for debet på `account`; `contra_account_number`
  modtager automatisk kredit. Skal noget krediteres på hovedkontoen, brug negativt beløb.
- Moms: `create_finance_voucher` sætter ingen momskode. Er posteringen momsbelagt,
  brug `create_journal_voucher` med udtrykkelig `vatAccount`, så momsen ikke glemmes.
- Rettelser laves som modposteringer, ikke ved at slette noget bogført.
- Mangler skriveværktøjerne, kører serveren i read-only eller med demo-tokens; forklar det.

## Fremgangsmåde

1. **Afklar**: dato (standard i dag), beløb, tekst (kort, søgbar, gerne med bilagsref.),
   debetkonto, kreditkonto, moms ja/nej, og om der er et bilag/kvittering brugeren vil
   vedhæfte bagefter i e-conomic.
2. **Kassekladden**: `list_journals` giver `journalNumber` og `name`. Er der én, brug
   den. Er der flere (fx "Kassekladde", "Bank", "Lønninger"), så spørg eller vælg den,
   hvis navn matcher posteringens art, og sig det.
3. **Konti**: `list_accounts(filter="name$like:<ord>", page_size=1000)`. Tjek
   `accountType` (`profitAndLoss` eller `status`; aldrig `heading`/sum-konti) og at
   `blockDirectEntries` er `false`. Vis kontoens `vatAccount` (standardmoms).
4. **Regnskabsår**: vælg det år fra `list_accounting_years`, som datoen falder i, og
   tjek at året ikke er `closed` og perioden ikke er spærret
   (`list_accounting_year_periods`, felterne `barred`/`closed`).
5. **Momskode** ved momsbelagte posteringer: `list_vat_accounts` giver `vatCode`
   (fx `I25` indgående, `U25` udgående) og `ratePercentage`.
6. **Vis forslaget**:
   ```
   Kassekladde: <navn> (nr. <n>) · Dato <dato> · Regnskabsår <year>
   Debet  <konto nr. navn>   <beløb> <valuta>   moms: <kode/ingen>
   Kredit <konto nr. navn>   <beløb> <valuta>
   Tekst: "<tekst>"
   Opretter jeg posten i kassekladden? (Den bogføres ikke automatisk.)
   ```
7. **Opret**:
   - Uden moms: `create_finance_voucher(journal_number, accounting_year, account_number,
     amount, currency, date, text, contra_account_number)`.
   - Med moms eller flere linjer: `create_journal_voucher(journal_number, voucher)` med
     ```json
     {"accountingYear": {"year": "2026"},
      "entries": {"financeVouchers": [
        {"account": {"accountNumber": 2800}, "contraAccount": {"accountNumber": 5820},
         "amount": 1250.00, "currency": {"code": "DKK"}, "date": "2026-09-05",
         "text": "Kontorartikler, bilag 1043", "vatAccount": {"vatCode": "I25"}}]}}
     ```
     Flere linjer i samme bilag skal balancere: sum af debet = sum af kredit.
8. **Bekræft** med `get_journal_vouchers(journal_number)` og rapportér
   `voucherNumber`, dato, beløb og konti. Mind brugeren om at bogføre kassekladden i
   e-conomic og vedhæfte bilaget der.

## Typiske posteringer

| Situation | Debet | Kredit | Moms |
|---|---|---|---|
| Småudgift betalt privat/kort | Omkostningskonto | Mellemregning/bank | Ja, hvis kvittering med moms |
| Bankgebyr | Gebyrkonto | Bank | Nej |
| Ompostering af fejl | Rigtig konto | Forkert konto | Som originalen |
| Periodisering | Periodeafgrænsning (status) | Omkostningskonto | Nej |

Er brugeren i tvivl om kontering eller moms, så sig det og anbefal at spørge deres
bogholder eller revisor, i stedet for at vælge for dem.
