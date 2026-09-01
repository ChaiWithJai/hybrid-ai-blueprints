# bonsai_edge — Awaaz, the Flutter build

One Dart codebase carrying the edge/mobile design system natively:
animated onboarding, real microphone recording with a live amplitude
waveform, TTS read-aloud, the grounding guard ported to Dart, live Bonsai
1.7b auto-detection, and an offline queue that survives restarts.

## Run and test (today, on this repo's verified host)

```bash
flutter test                    # 15 tests, headless — no device needed
flutter run -d web-server       # the web device; open the printed URL
flutter build web --release
```

Live model mode in the *web* build requires LM Studio started with CORS
(`lms server start --cors`); native targets call loopback directly and
need no CORS.

## Native targets (deliberately not committed)

Only the `web/` platform directory is in git. The android/ios/macos
scaffolds are pure generator output, cannot build on the verified host
(no Xcode, no Android SDK — see `docs/ADR_0004`), and regenerate
losslessly when a toolchain lands:

```bash
flutter create --platforms=android,ios,macos .
```

After regenerating: grant microphone permission in each platform's
manifest/entitlements (the `record` package documents the exact keys) —
that is the only platform-specific edit this app needs.
