# Demo 02 — Offline translate

Own offline translation where no incumbent has ever shipped it.

## Kill targets

| Target | Their position | Their gap |
| --- | --- | --- |
| Google Translate offline tier | 1B+ installs; 249 languages online | Only 59 offline; Tajik, Wolof, Uzbek: zero offline coverage |
| Yandex Translate (Central Asia) | 10M+ downloads, regional default | Tajik/Kyrgyz experimental only, cloud-only |
| Microsoft Translator | 100M+ downloads | Tajik and Wolof absent even online |

## The user and the moment

Farrukh works a Moscow construction site; his wife in Khujand speaks Tajik
and reads Russian poorly. Every message between them crosses a language the
big translators only handle online — and her village connectivity is
intermittent. The moment we win: a Russian message arrives on a phone with
no data, and it renders in Tajik; her Tajik reply leaves the phone in
Russian.

## Business use case (violet-rails style)

- Namespace: `translations`
- Resources: `TranslationPair { srcLang, dstLang, engine, modelVersion }`,
  `TranslationJob { text, srcLang, dstLang, result, engine, onDevice: true }`
- Actions (client-side): `translate` routes by language tier —
  1. generative tier (es/fr/ru/hi/ar/vi/id): Bonsai 1.7B + corridor LoRA
  2. sidecar tier (tg/ky/wo/ha/yo/darija): NLLB-200-distilled-600M, GGUF,
     translation only, no generation
  3. compose mode: dictate in language A (whisper), deliver in language B —
     the pipeline the incumbents don't have even online
- Server-side actions: none required for core function. Server distributes
  model/LoRA packs (versioned artifacts) and collects opt-in eval samples.

## Serverpod design

The server here is a model registry + eval collector, deliberately thin:

```yaml
class: ModelPack
table: model_pack
fields:
  name: String            # e.g. nllb-600m-q8, bonsai-1p7b-ur-lora-v2
  langPair: String?       # null for base models
  version: String
  sha256: String          # artifact identity, per repo conventions
  sizeBytes: int
  minAppVersion: String
```

Endpoints: `latestPacks(langs)` for differential model updates;
`submitEvalSample(...)` gated behind explicit consent (mirrors the repo's
signed-consent cloud-route pattern). Distribution uses Serverpod's cloud
storage with byte-range resume — pack downloads must survive 2G.

## Bonsai role and honesty boundary

Bonsai 1.7B generates only in its serviceable tier. For sidecar languages
the UI must attribute output to NLLB and never present LLM prose in a
language the model cannot verify — same evidence-boundary discipline as the
deal-room analyst's publication guard.

## Offline behavior

First-run downloads the corridor pack (base + one pair, target under 1.5GB
total incl. ASR). After that, translation works in airplane mode
indefinitely. Pack updates are diffed, resumable, and Wi-Fi-only by default
(data poverty is the design constraint, not an edge case).

## Eval gates

- FLORES-200 devtest per shipped pair, scored offline, hashes recorded
- Round-trip degradation check as a cheap regression tripwire
- The kill metric: pairs shipped offline that Google/Yandex/Microsoft do
  not have offline (starting set: ru<->tg, ru<->ky, fr<->wo)

## Milestones

1. NLLB-600M GGUF running under llama.cpp on the M5 host; FLORES baseline
2. Bonsai + Urdu LoRA vs NLLB on ur<->en; pick per-pair winner empirically
3. Serverpod model-pack registry + resumable distribution
4. Flutter translate surface inside the demo shell; airplane-mode script
