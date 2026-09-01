// Three screens, one decision each. The reader may not read well, so
// every choice is a big tappable card with a picture, and the words obey
// COPY.md: one idea per line, eight words is a long line.

import 'package:flutter/material.dart';

import 'sprites.dart';
import 'store.dart';
import 'theme.dart';

class Onboarding extends StatefulWidget {
  final Future<void> Function(FamilySettings) onDone;
  const Onboarding({super.key, required this.onDone});

  @override
  State<Onboarding> createState() => _OnboardingState();
}

class _OnboardingState extends State<Onboarding> {
  final _page = PageController();
  final _settings = FamilySettings();
  final _nameCtl = TextEditingController();
  int _step = 0;

  static const _langs = [
    ('hi', 'हिन्दी', 'Hindi'),
    ('bn', 'বাংলা', 'Bangla'),
    ('ur', 'اردو', 'Urdu'),
    ('es', 'Español', 'Spanish'),
    ('fr', 'Français', 'French'),
  ];

  void _next() {
    if (_step < 2) {
      _page.nextPage(
          duration: const Duration(milliseconds: 260), curve: Curves.easeOut);
    } else {
      _settings.familyName =
          _nameCtl.text.trim().isEmpty ? 'My family' : _nameCtl.text.trim();
      widget.onDone(_settings);
    }
  }

  @override
  Widget build(BuildContext context) {
    final r = Roles.of(context);
    return Scaffold(
      backgroundColor: r.paper,
      body: SafeArea(
        child: Column(children: [
          Expanded(
            child: PageView(
              controller: _page,
              physics: const NeverScrollableScrollPhysics(),
              onPageChanged: (i) => setState(() => _step = i),
              children: [
                _pane(
                  r,
                  hero: Row(mainAxisAlignment: MainAxisAlignment.center,
                      children: [
                        Peep('Amma', size: 96, ink: r.ink),
                        const SizedBox(width: 12),
                        Peep('Bilal', size: 96, ink: r.ink),
                      ]),
                  title: 'Who is this family?',
                  child: Padding(
                    padding: const EdgeInsets.symmetric(horizontal: 32),
                    child: TextField(
                      controller: _nameCtl,
                      textAlign: TextAlign.center,
                      style: const TextStyle(fontSize: 22),
                      decoration: InputDecoration(
                        hintText: 'Bhatti family',
                        filled: true,
                        fillColor: r.card,
                        border: OutlineInputBorder(
                            borderRadius: BorderRadius.circular(Tokens.radius),
                            borderSide: BorderSide.none),
                      ),
                    ),
                  ),
                ),
                _pane(
                  r,
                  hero: Icon(Icons.record_voice_over,
                      size: 84, color: r.marigold),
                  title: 'Which language feels like home?',
                  child: Wrap(
                    alignment: WrapAlignment.center,
                    spacing: 10,
                    runSpacing: 10,
                    children: [
                      for (final (code, native, en) in _langs)
                        ChoiceChip(
                          label: Padding(
                            padding: const EdgeInsets.symmetric(
                                horizontal: 8, vertical: 6),
                            child: Column(children: [
                              Text(native,
                                  style: const TextStyle(fontSize: 20)),
                              Text(en,
                                  style: TextStyle(
                                      fontSize: 12, color: r.inkSoft)),
                            ]),
                          ),
                          selected: _settings.lang == code,
                          selectedColor: r.marigoldSoft,
                          backgroundColor: r.card,
                          onSelected: (_) =>
                              setState(() => _settings.lang = code),
                        ),
                    ],
                  ),
                ),
                _pane(
                  r,
                  hero: Peep('Amma', size: 96, ink: r.ink),
                  title: 'Make everything bigger and spoken aloud?',
                  child: Column(children: [
                    _bigChoice(r, 'Yes — speak everything to me',
                        Icons.hearing, _settings.elderMode == true,
                        () => setState(() => _settings.elderMode = true)),
                    const SizedBox(height: 10),
                    _bigChoice(r, 'No — I will read', Icons.chrome_reader_mode,
                        _settings.elderMode == false,
                        () => setState(() => _settings.elderMode = false)),
                  ]),
                ),
              ],
            ),
          ),
          Padding(
            padding: const EdgeInsets.all(24),
            child: SizedBox(
              width: double.infinity,
              height: Tokens.tap,
              child: FilledButton(
                style: FilledButton.styleFrom(
                    backgroundColor: r.marigold,
                    foregroundColor: Colors.white,
                    textStyle: const TextStyle(
                        fontSize: 18, fontWeight: FontWeight.w700)),
                onPressed: _next,
                child: Text(_step < 2 ? 'Next' : 'Open $_familyLabel'),
              ),
            ),
          ),
        ]),
      ),
    );
  }

  String get _familyLabel =>
      _nameCtl.text.trim().isEmpty ? 'Awaaz' : _nameCtl.text.trim();

  Widget _pane(Roles r,
      {required Widget hero, required String title, required Widget child}) {
    return Padding(
      padding: const EdgeInsets.all(24),
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          hero,
          const SizedBox(height: 28),
          Text(title,
              textAlign: TextAlign.center,
              style:
                  const TextStyle(fontSize: 26, fontWeight: FontWeight.w600)),
          const SizedBox(height: 24),
          child,
        ],
      ),
    );
  }

  Widget _bigChoice(
      Roles r, String label, IconData icon, bool selected, VoidCallback onTap) {
    return SizedBox(
      width: double.infinity,
      height: 72,
      child: OutlinedButton.icon(
        style: OutlinedButton.styleFrom(
          backgroundColor: selected ? r.marigoldSoft : r.card,
          side: BorderSide(
              color: selected ? r.marigold : Colors.transparent, width: 2),
          foregroundColor: r.ink,
          textStyle: const TextStyle(fontSize: 18),
        ),
        icon: Icon(icon, size: 28),
        onPressed: onTap,
        label: Text(label),
      ),
    );
  }
}
