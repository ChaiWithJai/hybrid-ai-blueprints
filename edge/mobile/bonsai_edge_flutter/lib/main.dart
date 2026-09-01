// Awaaz — the Flutter build. One codebase for web/Android/iOS/macOS;
// web runs today on this machine, native targets compile once their
// toolchains land (docs/ADR_0004). Live Bonsai 1.7b when LM Studio is
// up; deterministic fixtures otherwise — the mode is always shown.

import 'package:flutter/material.dart';

import 'bonsai.dart';
import 'inbox.dart';
import 'onboarding.dart';
import 'store.dart';
import 'theme.dart';

const fixtureSummaries = {
  'vn-001.ogg':
      'SUMMARY: টাকা বিকাশে পাঠানো হয়েছে, পাঁচশো দিরহাম; ওষুধ কেনার পর বাকিটা রাখতে বলেছে।\nNEEDS_REPLY: no',
  'vn-002.ogg':
      'SUMMARY: مکان کے کاغذات وکیل کے پاس، جمعرات کو دستخط کے لیے عدنان کے ساتھ جانا ہے۔\nNEEDS_REPLY: yes',
  'vn-003.ogg':
      'SUMMARY: अगले हफ्ते छुट्टी, मंगलवार की फ्लाइट, बस से आएगा, एयरपोर्ट आने की ज़रूरत नहीं।\nNEEDS_REPLY: no',
  'vn-004.ogg':
      'SUMMARY: Depositó tres mil pesos en Spin; apartar quinientos para las medicinas y avisar cuando llegue.\nNEEDS_REPLY: yes',
  'vn-005.ogg':
      "SUMMARY: L'argent est parti par Wave, cent cinquante mille francs; il appelle dimanche.\nNEEDS_REPLY: no",
};

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  final store = FamilyStore();
  await store.load();
  final Provider provider = await BonsaiProvider.available()
      ? BonsaiProvider()
      : FixtureProvider(fixtureSummaries);
  runApp(AwaazApp(store: store, provider: provider));
}

class AwaazApp extends StatelessWidget {
  final FamilyStore store;
  final Provider provider;
  const AwaazApp({super.key, required this.store, required this.provider});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Awaaz',
      debugShowCheckedModeBanner: false,
      theme: buildTheme(Brightness.light),
      darkTheme: buildTheme(Brightness.dark),
      home: ListenableBuilder(
        listenable: store,
        builder: (context, _) => store.onboarded
            ? InboxScreen(store: store, provider: provider)
            : Onboarding(onDone: store.completeOnboarding),
      ),
    );
  }
}
