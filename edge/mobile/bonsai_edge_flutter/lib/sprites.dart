// The Open-Peeps-spirit family characters from design/sprites.svg,
// as standalone SVG strings (flutter_svg has no <use>/<symbol> support).
// Ink strokes take the theme's ink color at build time so the peeps hold
// in both themes, same as currentColor did on the web.

import 'package:flutter/widgets.dart';
import 'package:flutter_svg/flutter_svg.dart';

String _amma(String ink) => '''
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 96 96">
<circle cx="48" cy="48" r="46" fill="#f2e5cd"/>
<path d="M20 90 Q24 62 48 62 Q72 62 76 90 Z" fill="#7d5ba6" stroke="$ink" stroke-width="3" stroke-linejoin="round"/>
<circle cx="48" cy="40" r="19" fill="#c68863" stroke="$ink" stroke-width="3"/>
<path d="M27 42 Q24 16 48 15 Q72 16 69 42 Q69 24 48 24 Q27 24 27 42 Z" fill="#e8b04b" stroke="$ink" stroke-width="3" stroke-linejoin="round"/>
<path d="M69 40 Q76 48 71 58" fill="none" stroke="$ink" stroke-width="3" stroke-linecap="round"/>
<circle cx="41" cy="39" r="1.8" fill="$ink"/><circle cx="55" cy="39" r="1.8" fill="$ink"/>
<path d="M38 35 q3 -2 6 0 M52 35 q3 -2 6 0" fill="none" stroke="$ink" stroke-width="2" stroke-linecap="round"/>
<path d="M42 49 q6 4 12 0" fill="none" stroke="$ink" stroke-width="2.5" stroke-linecap="round"/>
</svg>''';

String _worker(String ink) => '''
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 96 96">
<circle cx="48" cy="48" r="46" fill="#dff0e4"/>
<path d="M20 90 Q24 62 48 62 Q72 62 76 90 Z" fill="#3778b8" stroke="$ink" stroke-width="3" stroke-linejoin="round"/>
<circle cx="48" cy="41" r="18" fill="#9c6b45" stroke="$ink" stroke-width="3"/>
<path d="M29 36 Q31 20 48 20 Q65 20 67 36 L72 36 Q73 40 67 40 L29 40 Z" fill="#e07b28" stroke="$ink" stroke-width="3" stroke-linejoin="round"/>
<circle cx="41" cy="42" r="1.8" fill="$ink"/><circle cx="55" cy="42" r="1.8" fill="$ink"/>
<path d="M41 51 q7 4 14 -1" fill="none" stroke="$ink" stroke-width="2.5" stroke-linecap="round"/>
</svg>''';

String _mother(String ink) => '''
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 96 96">
<circle cx="48" cy="48" r="46" fill="#fbe8d3"/>
<path d="M20 90 Q24 62 48 62 Q72 62 76 90 Z" fill="#2f7d4f" stroke="$ink" stroke-width="3" stroke-linejoin="round"/>
<circle cx="48" cy="42" r="18" fill="#b57a50" stroke="$ink" stroke-width="3"/>
<circle cx="48" cy="18" r="8" fill="$ink"/>
<path d="M30 40 Q28 22 48 22 Q68 22 66 40 Q64 28 48 28 Q32 28 30 40 Z" fill="$ink" stroke="$ink" stroke-width="3" stroke-linejoin="round"/>
<circle cx="41" cy="43" r="1.8" fill="#fdf6ea"/><circle cx="41" cy="43" r="1.2" fill="$ink"/>
<circle cx="55" cy="43" r="1.8" fill="#fdf6ea"/><circle cx="55" cy="43" r="1.2" fill="$ink"/>
<path d="M40 51 q8 6 16 0" fill="none" stroke="$ink" stroke-width="2.5" stroke-linecap="round"/>
</svg>''';

String _kid(String ink) => '''
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 96 96">
<circle cx="48" cy="48" r="46" fill="#e3eefa"/>
<path d="M24 90 Q28 66 48 66 Q68 66 72 90 Z" fill="#e8b04b" stroke="$ink" stroke-width="3" stroke-linejoin="round"/>
<circle cx="48" cy="46" r="16" fill="#8a5a3b" stroke="$ink" stroke-width="3"/>
<circle cx="34" cy="34" r="7" fill="$ink"/><circle cx="46" cy="29" r="8" fill="$ink"/><circle cx="59" cy="33" r="7" fill="$ink"/>
<circle cx="42" cy="47" r="1.8" fill="#fdf6ea"/><circle cx="54" cy="47" r="1.8" fill="#fdf6ea"/>
<circle cx="42" cy="47" r="1.1" fill="$ink"/><circle cx="54" cy="47" r="1.1" fill="$ink"/>
<path d="M42 54 q6 5 12 0" fill="none" stroke="$ink" stroke-width="2.5" stroke-linecap="round"/>
</svg>''';

const _peepBySender = {
  'Amina': 'mother', 'Lupita': 'mother',
  'Bilal': 'worker', 'Suresh': 'worker', 'Moussa': 'worker',
  'You': 'amma', 'Amma': 'amma', 'Nia': 'kid',
};

class Peep extends StatelessWidget {
  final String sender;
  final double size;
  final Color ink;
  const Peep(this.sender,
      {super.key, this.size = 52, required this.ink});

  @override
  Widget build(BuildContext context) {
    final hex =
        '#${ink.toARGB32().toRadixString(16).padLeft(8, '0').substring(2)}';
    final which = _peepBySender[sender] ?? 'worker';
    final svg = switch (which) {
      'amma' => _amma(hex),
      'mother' => _mother(hex),
      'kid' => _kid(hex),
      _ => _worker(hex),
    };
    return SvgPicture.string(svg, width: size, height: size);
  }
}
