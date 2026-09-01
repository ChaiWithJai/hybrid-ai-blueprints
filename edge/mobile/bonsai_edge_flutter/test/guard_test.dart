// The grounding guard and queue semantics, tested headless — including
// the two regression lessons from the web round: the Bengali tokenizer
// and the state-visibility contract.

import 'package:bonsai_edge/bonsai.dart';
import 'package:bonsai_edge/store.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

void main() {
  group('content words (the combining-marks lesson)', () {
    test('Bengali words survive tokenization intact', () {
      final words = contentWords('মা, আমি এই মাসের টাকা বিকাশে পাঠিয়ে দিয়েছি');
      expect(words, contains('টাকা'));
      expect(words, contains('বিকাশে'));
    });

    test('Urdu with danda/urdu punctuation splits cleanly', () {
      final words = contentWords('عدنان کو ساتھ لے جائیں۔');
      expect(words, contains('عدنان'));
    });
  });

  group('grounding guard', () {
    test('grounded summary passes', () {
      expect(grounded('টাকা বিকাশে পাঠানো হয়েছে', 'আমি টাকা বিকাশে পাঠিয়েছি'),
          isTrue);
    });

    test('ungrounded summary fails — the evaluator can fail', () {
      expect(grounded('qqxyzzy unrelated nonsense', 'আমি টাকা পাঠিয়েছি'),
          isFalse);
    });

    test('empty summary fails', () {
      expect(grounded('', 'anything at all here'), isFalse);
    });
  });

  group('summarize pipeline', () {
    test('off-topic model output lands in labeled fallback', () async {
      final bad = FixtureProvider(
          {'default': 'SUMMARY: zzz unrelated\nNEEDS_REPLY: no'});
      final r = await summarize(bad, 'x.ogg', 'es',
          'Mamá, ya deposité tres mil pesos en Spin.');
      expect(r.summaryMode, 'fallback');
      expect(r.summary, startsWith('[transcript excerpt]'));
      expect(r.needsReply, isTrue); // fallbacks always ask for attention
    });

    test('grounded model output passes with parsed needsReply', () async {
      final good = FixtureProvider({
        'default': 'SUMMARY: Depositó tres mil pesos en Spin.\nNEEDS_REPLY: yes'
      });
      final r = await summarize(good, 'x.ogg', 'es',
          'Mamá, ya deposité tres mil pesos en Spin.');
      expect(r.summaryMode, 'model');
      expect(r.needsReply, isTrue);
    });

    test('missing fixture throws instead of silently passing', () {
      final empty = FixtureProvider(const {});
      expect(() => empty.chat('s', 'nothing matches'), throwsStateError);
    });
  });

  group('offline queue (persisted)', () {
    setUp(() => SharedPreferences.setMockInitialValues({}));

    test('note created offline queues; going online syncs it', () async {
      final store = FamilyStore();
      await store.load();
      await store.setOnline(false);
      final n = store.add(
          audioRef: 'r1', lang: 'bn', durationMs: 900, senderName: 'You',
          transcript: 'টাকা পেয়েছি মা', asrMode: 'fixture', direction: 'out');
      expect(n.syncState, 'queued');
      expect(store.queuedCount, 1);
      await store.setOnline(true);
      expect(store.notes.single.syncState, 'synced');
    });

    test('queue survives a restart (the offline promise is structural)',
        () async {
      final store = FamilyStore();
      await store.load();
      await store.setOnline(false);
      store.add(
          audioRef: 'r1', lang: 'bn', durationMs: 900, senderName: 'You',
          transcript: 'টাকা পেয়েছি মা', asrMode: 'fixture', direction: 'out');
      // brief settle: add() persists fire-and-forget
      await Future<void>.delayed(const Duration(milliseconds: 10));

      final reborn = FamilyStore();
      await reborn.load();
      expect(reborn.queuedCount, 1);
      expect(reborn.online, isFalse);
    });

    test('own outgoing note never needs a model or a reply', () async {
      final store = FamilyStore();
      await store.load();
      final n = store.add(
          audioRef: 'r1', lang: 'es', durationMs: 900, senderName: 'You',
          transcript: 'Recibido, mija.', asrMode: 'fixture', direction: 'out');
      final neverCalled = FixtureProvider(const {});
      await store.digest(neverCalled, n); // would throw if it hit the model
      expect(n.summaryMode, 'own');
      expect(n.needsReply, isFalse);
      expect(neverCalled.calls, isEmpty);
    });
  });
}
