// Widget tests: the state-visibility contract the design review taught —
// a chip's absence must be provable in the tree, and mutually exclusive
// states must never render together.

import 'package:bonsai_edge/bonsai.dart';
import 'package:bonsai_edge/inbox.dart';
import 'package:bonsai_edge/store.dart';
import 'package:bonsai_edge/theme.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

Future<FamilyStore> seededStore() async {
  SharedPreferences.setMockInitialValues({});
  final store = FamilyStore();
  await store.load();
  store.settings = FamilySettings(familyName: 'Test family', lang: 'hi');
  store.onboarded = true;
  return store;
}

Widget app(FamilyStore store, Provider provider) => MaterialApp(
      theme: buildTheme(Brightness.light),
      home: InboxScreen(store: store, provider: provider),
    );

void main() {
  testWidgets('outgoing card never shows the needs-reply chip',
      (tester) async {
    final store = await seededStore();
    final n = store.add(
        audioRef: 'r1', lang: 'es', durationMs: 900, senderName: 'You',
        transcript: 'Recibido, mija.', asrMode: 'fixture', direction: 'out');
    await store.digest(FixtureProvider(const {}), n);

    await tester.pumpWidget(app(store, FixtureProvider(const {})));
    await tester.pump();
    expect(find.text('Waiting to hear back'), findsNothing);
    expect(find.text('Arrived'), findsOneWidget);
  });

  testWidgets('queued outgoing card says it will send by itself',
      (tester) async {
    final store = await seededStore();
    await store.setOnline(false);
    final n = store.add(
        audioRef: 'r1', lang: 'es', durationMs: 900, senderName: 'You',
        transcript: 'Recibido, mija.', asrMode: 'fixture', direction: 'out');
    await store.digest(FixtureProvider(const {}), n);

    await tester.pumpWidget(app(store, FixtureProvider(const {})));
    await tester.pump();
    expect(find.textContaining('will send by itself'), findsOneWidget);
    expect(find.textContaining('Everything here still works'), findsOneWidget);
  });

  testWidgets('fallback and model marks are mutually exclusive',
      (tester) async {
    final store = await seededStore();
    final n = store.add(
        audioRef: 'vn-x.ogg', lang: 'es', durationMs: 5000,
        senderName: 'Lupita',
        transcript: 'Mamá, ya deposité tres mil pesos en Spin.',
        asrMode: 'fixture', direction: 'in');
    final bad =
        FixtureProvider({'default': 'SUMMARY: zzz\nNEEDS_REPLY: no'});
    await store.digest(bad, n);

    await tester.pumpWidget(app(store, bad));
    await tester.pump();
    expect(find.textContaining("I couldn't catch this"), findsOneWidget);
    expect(find.text('MADE ON THIS PHONE'), findsNothing);
  });

  testWidgets('needs-reply chip appears only on grounded incoming asks',
      (tester) async {
    final store = await seededStore();
    final n = store.add(
        audioRef: 'vn-y.ogg', lang: 'es', durationMs: 5000,
        senderName: 'Lupita',
        transcript: 'Mamá, ya deposité tres mil pesos en Spin.',
        asrMode: 'fixture', direction: 'in');
    final good = FixtureProvider({
      'default': 'SUMMARY: Depositó tres mil pesos en Spin.\nNEEDS_REPLY: yes'
    });
    await store.digest(good, n);

    await tester.pumpWidget(app(store, good));
    await tester.pump();
    expect(find.text('Waiting to hear back'), findsOneWidget);
    expect(find.text('MADE ON THIS PHONE'), findsOneWidget);
  });
}
