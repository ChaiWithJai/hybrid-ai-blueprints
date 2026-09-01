# Demo 06 — Remittance ledger

The money conversation, remembered. Rides the transfer rails; owns the
record and the family context they all lack.

## Targets (ride and partner, not kill)

| Target | Their position | The unclaimed layer |
| --- | --- | --- |
| Remitly / Wise / WU / Ria | ~$90B+/quarter public-company volume | Apps open ~1-2x/month to transact; no family context, no record recall |
| Félix Pago | $1B+ moved inside WhatsApp; the proof-of-thesis | Same surface, cloud-side; competes for money-as-conversation |
| GCash, bKash, easypaisa/JazzCash, Wave, EcoCash, OPay, Spin, Korona | 300M+ combined actives on the receiving side | Text-first, official-language-only, transactional — their user is our household |

## The user and the moment

"What did we send for Ammi's medicine in March?" Today the answer is a
scroll through three apps and a chat thread. The moment we win: the
question is asked out loud in Urdu, and the phone answers from the family's
own records — extracted from the conversation itself, on-device, with the
source message shown.

## Business use case (violet-rails style)

- Namespace: `remittance_records`
- Resources: `RemittanceRecord { familyId, amount, currency, date, channel,
  purposeTags[], sourceRef, extractionConfidence, humanConfirmed: bool }`
- Actions:
  - client `on-message` (from demos 01/03 stores, or share-sheet/screenshot
    import): `extract` — Bonsai 1.7B single-turn structured output with
    grammar-constrained decoding (the BFCL finding: single-turn only);
    below-threshold confidence routes to a one-tap confirm card, never a
    silent write
  - client `on-question`: `recall` — RAG over confirmed records; every
    answer cites its source record (publication-guard discipline)
  - server `on-sync` (opt-in): encrypted family ledger backup; a
    `send_web_request`-class action posts a monthly family summary into
    the family-line channel — the one server-side ApiAction in the suite
- No money movement, no license: records and recall only. Integration with
  wallets is a partnership surface (their API receipts -> our records),
  and the displacement vector if partnership fails.

## Serverpod design

```yaml
class: RemittanceRecord
table: remittance_record
fields:
  familyId: int
  amountMinor: int
  currency: String
  occurredAt: DateTime
  channel: String            # remitly|wise|wu|wallet|cash|informal
  purposeTags: List<String>
  sourceRef: String          # envelope/voice-note id — grounding is mandatory
  extractionConfidence: double
  humanConfirmed: bool
indexes:
  remittance_family_date_idx:
    fields: familyId, occurredAt
```

Endpoints: `syncRecords` (opt-in, encrypted), `monthlySummary` future call
(the cron-style ExternalApiClient analog). Recall runs entirely on-device
against the local store; the server never answers questions.

## Bonsai role

Extraction is the fine-tune tier: a LoRA on synthetic + confirmed-real
remittance chatter per corridor (amounts, currencies, hawala vocabulary,
purpose phrases). Recall is RAG over typed records — parametric memory is
never trusted for money facts; unconfirmed extractions are visibly
provisional in every surface.

## Offline behavior

Extraction and recall are fully offline. Sync and the monthly summary are
connected-only conveniences. Informal channels (cash carried home — >50%
in the Zimbabwe corridor, >80% Lesotho) enter by voice: "I sent five
hundred with Tendai" is a first-class record, which is precisely what no
wallet can capture.

## Eval gates

- Extraction F1 on a preregistered multilingual remittance-chatter corpus,
  with a wrong-amount mutation set proving the evaluator can fail
  (benchmark-card conventions from the deal room apply)
- Zero unconfirmed records in any recall answer without a "provisional" mark
- The metric that matters: recall answers grounded 100% in confirmed
  records, and time-to-answer vs scrolling three apps

## Milestones

1. Extraction LoRA v0 (es + ur) over synthetic corpus; F1 baseline
2. Confirm-card loop + grounded recall CLI
3. Serverpod opt-in sync + monthly summary future call
4. Wallet-receipt import spike (share-sheet first; APIs with partners)
