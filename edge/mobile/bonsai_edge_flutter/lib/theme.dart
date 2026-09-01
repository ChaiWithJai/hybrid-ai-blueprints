// The design tokens (edge/mobile/design/tokens.css) ported to Flutter.
// Same rules: warm paper + ink, one marigold accent reserved for the act
// of speaking, state colors always paired with icon + word, 18px body
// floor, 56px touch floor (88px for the mic — the mic IS the app).

import 'package:flutter/material.dart';

class Tokens {
  // light
  static const paper = Color(0xFFFDF6EA);
  static const card = Color(0xFFFFFDF8);
  static const sand = Color(0xFFF2E5CD);
  static const ink = Color(0xFF2B2016);
  static const inkSoft = Color(0xFF6B5A48);
  static const inkFaint = Color(0xFFA08B74);
  static const line = Color(0xFFE5D5BB);
  static const marigold = Color(0xFFE07B28);
  static const marigoldDeep = Color(0xFFB85E17);
  static const marigoldSoft = Color(0xFFFBE8D3);
  static const leaf = Color(0xFF2F7D4F);
  static const leafSoft = Color(0xFFDFF0E4);
  static const sky = Color(0xFF3778B8);
  static const skySoft = Color(0xFFE3EEFA);
  static const clay = Color(0xFFB8452E);
  static const claySoft = Color(0xFFF9E2DC);
  static const wait = Color(0xFF8A6D3B);
  static const waitSoft = Color(0xFFF4EAD2);

  // dark
  static const paperD = Color(0xFF211A12);
  static const cardD = Color(0xFF2A2218);
  static const sandD = Color(0xFF352B1E);
  static const inkD = Color(0xFFF4EAD9);
  static const inkSoftD = Color(0xFFCBB99F);
  static const marigoldD = Color(0xFFEF9247);
  static const leafD = Color(0xFF5CB984);
  static const skyD = Color(0xFF6EA9DD);
  static const waitD = Color(0xFFC8A262);
  static const waitSoftD = Color(0xFF3B321F);
  static const leafSoftD = Color(0xFF253C2E);
  static const skySoftD = Color(0xFF23344A);
  static const marigoldSoftD = Color(0xFF462D1A);

  static const tap = 56.0;
  static const tapHero = 88.0;
  static const radius = 18.0;
}

/// Per-brightness role lookup so widgets never hardcode a side.
class Roles {
  final Color paper, card, sand, ink, inkSoft, inkFaint, marigold,
      marigoldSoft, leaf, leafSoft, sky, skySoft, wait, waitSoft;
  const Roles._({
    required this.paper, required this.card, required this.sand,
    required this.ink, required this.inkSoft, required this.inkFaint,
    required this.marigold, required this.marigoldSoft,
    required this.leaf, required this.leafSoft,
    required this.sky, required this.skySoft,
    required this.wait, required this.waitSoft,
  });

  static const light = Roles._(
    paper: Tokens.paper, card: Tokens.card, sand: Tokens.sand,
    ink: Tokens.ink, inkSoft: Tokens.inkSoft, inkFaint: Tokens.inkFaint,
    marigold: Tokens.marigold, marigoldSoft: Tokens.marigoldSoft,
    leaf: Tokens.leaf, leafSoft: Tokens.leafSoft,
    sky: Tokens.sky, skySoft: Tokens.skySoft,
    wait: Tokens.wait, waitSoft: Tokens.waitSoft,
  );

  static const dark = Roles._(
    paper: Tokens.paperD, card: Tokens.cardD, sand: Tokens.sandD,
    ink: Tokens.inkD, inkSoft: Tokens.inkSoftD, inkFaint: Tokens.inkFaint,
    marigold: Tokens.marigoldD, marigoldSoft: Tokens.marigoldSoftD,
    leaf: Tokens.leafD, leafSoft: Tokens.leafSoftD,
    sky: Tokens.skyD, skySoft: Tokens.skySoftD,
    wait: Tokens.waitD, waitSoft: Tokens.waitSoftD,
  );

  static Roles of(BuildContext context) =>
      Theme.of(context).brightness == Brightness.dark ? dark : light;
}

ThemeData buildTheme(Brightness brightness) {
  final r = brightness == Brightness.dark ? Roles.dark : Roles.light;
  final base = ThemeData(
    brightness: brightness,
    useMaterial3: true,
    scaffoldBackgroundColor: r.paper,
    colorScheme: ColorScheme.fromSeed(
      seedColor: r.marigold,
      brightness: brightness,
      surface: r.paper,
    ),
    fontFamilyFallback: const [
      'SF Pro Rounded', 'Segoe UI', 'Roboto',
      'Noto Sans', 'Noto Sans Bengali', 'Noto Nastaliq Urdu',
      'Noto Sans Devanagari',
    ],
  );
  // The 18px body floor is enforced by explicit sizes at every content
  // text site (a global fontSizeFactor asserts on null-size styles).
  return base.copyWith(
    textTheme: base.textTheme.apply(bodyColor: r.ink, displayColor: r.ink),
  );
}
