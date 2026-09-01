// The Awaaz inbox — the critical workflow, deep:
// voice notes arrive, transcripts and summaries are made on the phone,
// replies are RECORDED with the real microphone (live amplitude
// waveform), read-alouds are real TTS, and everything survives a
// restart. Elder mode makes the whole screen spoken and huge.

import 'dart:async';

import 'package:audioplayers/audioplayers.dart';
import 'package:flutter/material.dart';
import 'package:flutter_tts/flutter_tts.dart';
import 'package:record/record.dart';

import 'bonsai.dart';
import 'sprites.dart';
import 'store.dart';
import 'theme.dart';

// The same five-note corpus the Python demo proved (bn/ur/hi/es/fr),
// plus the reply scripts. ASR is not on this machine; incoming
// transcripts are fixtures and are labeled asrMode=fixture — recorded,
// never faked (repo evidence-boundary convention).
const incomingCorpus = [
  ('vn-001.ogg', 'bn', 42000, 'Amina',
      'মা, আমি এই মাসের টাকা বিকাশে পাঠিয়ে দিয়েছি, পাঁচশো দিরহাম। ওষুধ কেনার পর বাকিটা রেখে দিও। শুক্রবার ফোন করব।'),
  ('vn-002.ogg', 'ur', 35000, 'Bilal',
      'امی، مکان کے کاغذات وکیل کے پاس ہیں۔ جمعرات کو دستخط کے لیے جانا ہے۔ عدنان کو ساتھ لے جائیں۔'),
  ('vn-003.ogg', 'hi', 28000, 'Suresh',
      'पापा, अगले हफ्ते छुट्टी मिल गई है। मंगलवार की फ्लाइट है। एयरपोर्ट आने की ज़रूरत नहीं, मैं बस से आ जाऊँगा।'),
  ('vn-004.ogg', 'es', 51000, 'Lupita',
      'Mamá, ya deposité lo de este mes en Spin, son tres mil pesos. Aparta quinientos para las medicinas de la abuela y me avisas cuando llegue.'),
  ('vn-005.ogg', 'fr', 39000, 'Moussa',
      "Tonton, l'argent est parti par Wave ce matin. Cent cinquante mille francs. Dis à maman que j'appelle dimanche après la prière."),
];

const replyScripts = [
  ('bn', 'টাকা পেয়েছি মা, ওষুধ কাল কিনব। চিন্তা কোরো না।'),
  ('es', 'Recibido, mija. Aparto lo de las medicinas y te aviso.'),
  ('ur', 'ٹھیک ہے بیٹا، جمعرات کو عدنان کے ساتھ چلی جاؤں گی۔'),
];

const rtlLangs = {'ur', 'ar'};

class InboxScreen extends StatefulWidget {
  final FamilyStore store;
  final Provider provider;
  const InboxScreen({super.key, required this.store, required this.provider});

  @override
  State<InboxScreen> createState() => _InboxScreenState();
}

class _InboxScreenState extends State<InboxScreen> {
  final _recorder = AudioRecorder();
  final _player = AudioPlayer();
  final _tts = FlutterTts();
  final List<double> _amplitudes = [];
  StreamSubscription<Amplitude>? _ampSub;
  bool _recording = false;
  DateTime? _recordStart;
  int _incomingIdx = 0;
  int _replyIdx = 0;
  int _busyNoteId = -1;

  FamilyStore get store => widget.store;

  @override
  void dispose() {
    _ampSub?.cancel();
    _recorder.dispose();
    _player.dispose();
    super.dispose();
  }

  Future<void> _receiveNext() async {
    if (_incomingIdx >= incomingCorpus.length) return;
    final (ref, lang, dur, sender, transcript) =
        incomingCorpus[_incomingIdx++];
    final note = store.add(
        audioRef: ref, lang: lang, durationMs: dur, senderName: sender,
        transcript: transcript, asrMode: 'fixture', direction: 'in');
    setState(() => _busyNoteId = note.id);
    await store.digest(widget.provider, note);
    setState(() => _busyNoteId = -1);
    if (store.settings.elderMode && note.summaryMode == 'model') {
      _speak(note.summary, note.lang);
    }
  }

  Future<void> _toggleRecord() async {
    if (_recording) {
      final path = await _recorder.stop();
      await _ampSub?.cancel();
      final elapsed = DateTime.now()
          .difference(_recordStart ?? DateTime.now())
          .inMilliseconds;
      setState(() => _recording = false);
      final (lang, transcript) = replyScripts[_replyIdx % replyScripts.length];
      _replyIdx++;
      final note = store.add(
        audioRef: 'reply-${_replyIdx.toString().padLeft(3, '0')}',
        lang: lang,
        durationMs: elapsed < 800 ? 800 : elapsed,
        senderName: 'You',
        transcript: transcript,
        asrMode: 'fixture', // no on-device ASR on this host — labeled
        direction: 'out',
        audioDataUrl: path,
      );
      await store.digest(widget.provider, note);
      return;
    }
    if (!await _recorder.hasPermission()) return;
    _amplitudes.clear();
    _recordStart = DateTime.now();
    await _recorder.start(const RecordConfig(encoder: AudioEncoder.wav),
        path: 'reply.wav');
    _ampSub = _recorder
        .onAmplitudeChanged(const Duration(milliseconds: 120))
        .listen((a) {
      setState(() {
        _amplitudes.add(((a.current + 45) / 45).clamp(0.05, 1.0));
        if (_amplitudes.length > 28) _amplitudes.removeAt(0);
      });
    });
    setState(() => _recording = true);
  }

  Future<void> _play(VoiceNote note) async {
    if (note.audioDataUrl != null) {
      await _player.play(UrlSource(note.audioDataUrl!));
    } else {
      // Incoming fixtures carry no audio artifact; speak the transcript —
      // real TTS, honestly framed as "read aloud", not playback.
      _speak(note.transcript, note.lang);
    }
  }

  Future<void> _speak(String text, String lang) async {
    await _tts.setLanguage(switch (lang) {
      'bn' => 'bn-BD', 'ur' => 'ur-PK', 'hi' => 'hi-IN',
      'es' => 'es-MX', 'fr' => 'fr-FR', _ => 'en-US',
    });
    await _tts.speak(text);
  }

  @override
  Widget build(BuildContext context) {
    final r = Roles.of(context);
    final elder = store.settings.elderMode;
    final scale = elder ? 1.35 : 1.0;
    final notes = store.notes.reversed.toList();

    return Scaffold(
      backgroundColor: r.paper,
      body: SafeArea(
        child: Column(children: [
          _header(r),
          if (!store.online) _offlineBanner(r),
          Expanded(
            child: notes.isEmpty
                ? _empty(r)
                : MediaQuery(
                    data: MediaQuery.of(context)
                        .copyWith(textScaler: TextScaler.linear(scale)),
                    child: ListView.separated(
                      padding: const EdgeInsets.fromLTRB(16, 8, 16, 130),
                      itemCount: notes.length,
                      separatorBuilder: (_, _) => const SizedBox(height: 14),
                      itemBuilder: (_, i) => _card(r, notes[i], elder),
                    ),
                  ),
          ),
        ]),
      ),
      floatingActionButtonLocation: FloatingActionButtonLocation.centerFloat,
      floatingActionButton: _micDock(r),
      bottomNavigationBar: _devStrip(r),
    );
  }

  Widget _header(Roles r) => Padding(
        padding: const EdgeInsets.fromLTRB(20, 14, 20, 8),
        child: Row(children: [
          Peep('Amma', size: 44, ink: r.ink),
          const SizedBox(width: 12),
          Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(
                store.settings.familyName.isEmpty
                    ? 'Awaaz'
                    : store.settings.familyName,
                style: const TextStyle(
                    fontSize: 24, fontWeight: FontWeight.w700)),
            Text('Family voices, kept close',
                style: TextStyle(fontSize: 13, color: r.inkSoft)),
          ]),
          const Spacer(),
          _pill(
            r,
            icon: store.online ? Icons.done_all : Icons.cloud_off,
            label: store.online ? 'Connected' : 'Offline',
            fg: store.online ? r.leaf : r.wait,
            bg: store.online ? r.leafSoft : r.waitSoft,
          ),
        ]),
      );

  Widget _offlineBanner(Roles r) => Container(
        margin: const EdgeInsets.fromLTRB(16, 0, 16, 6),
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
        decoration: BoxDecoration(
            color: r.waitSoft,
            borderRadius: BorderRadius.circular(Tokens.radius)),
        child: Row(children: [
          Icon(Icons.cloud_off, size: 20, color: r.wait),
          const SizedBox(width: 10),
          Expanded(
              child: Text(
                  'No internet right now. Everything here still works.',
                  style: TextStyle(color: r.wait, fontSize: 14))),
        ]),
      );

  Widget _empty(Roles r) => Center(
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          Peep('Amma', size: 128, ink: r.ink),
          const SizedBox(height: 14),
          Text('When family speaks, it lands here.',
              style: TextStyle(color: r.inkSoft, fontSize: 17)),
          const SizedBox(height: 8),
          Text('Try "receive next note" below.',
              style: TextStyle(color: r.inkFaint, fontSize: 13)),
        ]),
      );

  Widget _card(Roles r, VoiceNote n, bool elder) {
    final out = n.direction == 'out';
    final rtl = rtlLangs.contains(n.lang);
    final busy = n.id == _busyNoteId || n.summaryMode == 'pending';
    return AnimatedContainer(
      duration: const Duration(milliseconds: 200),
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: out ? r.marigoldSoft : r.card,
        borderRadius: BorderRadius.circular(Tokens.radius),
        boxShadow: [
          BoxShadow(
              color: Colors.black.withValues(alpha: 0.07),
              blurRadius: 10, offset: const Offset(0, 2)),
        ],
      ),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          Peep(n.senderName, size: 48, ink: r.ink),
          const SizedBox(width: 12),
          Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(n.senderName,
                style: const TextStyle(
                    fontSize: 17, fontWeight: FontWeight.w600)),
            Text('${(n.durationMs / 1000).round()}s · voice note',
                style: TextStyle(fontSize: 13, color: r.inkFaint)),
          ]),
        ]),
        const SizedBox(height: 10),
        Row(children: [
          SizedBox(
            width: Tokens.tap, height: Tokens.tap,
            child: IconButton.filledTonal(
              style: IconButton.styleFrom(backgroundColor: r.sand),
              onPressed: () => _play(n),
              icon: Icon(
                  n.audioDataUrl != null ? Icons.play_arrow : Icons.hearing,
                  color: r.ink),
              tooltip: n.audioDataUrl != null
                  ? 'Play the recording'
                  : 'Hear it read aloud',
            ),
          ),
          const SizedBox(width: 10),
          Expanded(child: _staticWave(r, n.id)),
        ]),
        if (!out) ...[
          const SizedBox(height: 10),
          busy
              ? Row(children: [
                  SizedBox(
                      width: 16, height: 16,
                      child: CircularProgressIndicator(
                          strokeWidth: 2, color: r.sky)),
                  const SizedBox(width: 10),
                  Text('Making sense of it on this phone…',
                      style: TextStyle(color: r.inkSoft, fontSize: 14)),
                ])
              : _summaryBlock(r, n, rtl),
        ],
        const SizedBox(height: 10),
        Wrap(spacing: 8, runSpacing: 8, children: [
          if (!out && n.needsReply && !busy)
            _pill(r, icon: Icons.hearing, label: 'Waiting to hear back',
                fg: r.wait, bg: r.waitSoft),
          if (out)
            _pill(
              r,
              icon: n.syncState == 'queued'
                  ? Icons.schedule_send
                  : Icons.done_all,
              label: n.syncState == 'queued'
                  ? 'Waiting for network — will send by itself'
                  : 'Arrived',
              fg: n.syncState == 'queued' ? r.wait : r.leaf,
              bg: n.syncState == 'queued' ? r.waitSoft : r.leafSoft,
            ),
          if (!out && !elder && !busy)
            TextButton(
              onPressed: () => _showTranscript(r, n, rtl),
              child: Text('Read every word',
                  style: TextStyle(
                      color: r.sky, fontWeight: FontWeight.w600)),
            ),
        ]),
      ]),
    );
  }

  Widget _summaryBlock(Roles r, VoiceNote n, bool rtl) {
    final fallback = n.summaryMode == 'fallback';
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
      decoration: BoxDecoration(
          color: fallback ? r.sand : r.skySoft,
          borderRadius: BorderRadius.circular(14)),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          Icon(fallback ? Icons.hearing : Icons.auto_awesome,
              size: 15, color: fallback ? r.wait : r.sky),
          const SizedBox(width: 6),
          Flexible(
            child: Text(
              fallback
                  ? "I couldn't catch this — play the voice instead"
                  : 'MADE ON THIS PHONE',
              style: TextStyle(
                  fontSize: 11.5,
                  fontWeight: FontWeight.w700,
                  letterSpacing: fallback ? 0 : 0.6,
                  color: fallback ? r.wait : r.sky),
            ),
          ),
        ]),
        const SizedBox(height: 4),
        Directionality(
          textDirection: rtl ? TextDirection.rtl : TextDirection.ltr,
          child: Text(n.summary, style: const TextStyle(fontSize: 16.5)),
        ),
      ]),
    );
  }

  void _showTranscript(Roles r, VoiceNote n, bool rtl) {
    showModalBottomSheet<void>(
      context: context,
      backgroundColor: r.card,
      shape: const RoundedRectangleBorder(
          borderRadius: BorderRadius.vertical(top: Radius.circular(20))),
      builder: (_) => Padding(
        padding: const EdgeInsets.all(24),
        child: Column(mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text('Every word from ${n.senderName}',
                  style: const TextStyle(
                      fontSize: 18, fontWeight: FontWeight.w700)),
              const SizedBox(height: 4),
              Text('transcribed ${n.asrMode == 'fixture' ? 'from a fixture — no on-device ASR on this machine yet' : 'on this phone'}',
                  style: TextStyle(fontSize: 12, color: r.inkFaint)),
              const SizedBox(height: 14),
              Directionality(
                textDirection: rtl ? TextDirection.rtl : TextDirection.ltr,
                child: Text(n.transcript,
                    style: const TextStyle(fontSize: 19, height: 1.6)),
              ),
              const SizedBox(height: 16),
              FilledButton.tonalIcon(
                onPressed: () => _speak(n.transcript, n.lang),
                icon: const Icon(Icons.hearing),
                label: const Text('Hear it read aloud'),
              ),
            ]),
      ),
    );
  }

  Widget _staticWave(Roles r, int seed) => SizedBox(
        height: 34,
        child: Row(children: [
          for (var i = 0; i < 24; i++) ...[
            Expanded(
              child: Container(
                height: 8.0 + ((seed * (i + 3) * 7919) % 22),
                decoration: BoxDecoration(
                    color: r.inkFaint,
                    borderRadius: BorderRadius.circular(2)),
              ),
            ),
            if (i < 23) const SizedBox(width: 3),
          ],
        ]),
      );

  Widget _micDock(Roles r) => Column(mainAxisSize: MainAxisSize.min, children: [
        if (_recording)
          Container(
            margin: const EdgeInsets.only(bottom: 10),
            padding:
                const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
            decoration: BoxDecoration(
                color: r.card,
                borderRadius: BorderRadius.circular(Tokens.radius),
                boxShadow: const [
                  BoxShadow(color: Colors.black26, blurRadius: 12)
                ]),
            child: SizedBox(
              width: 200, height: 30,
              child: Row(
                  mainAxisAlignment: MainAxisAlignment.center,
                  crossAxisAlignment: CrossAxisAlignment.center,
                  children: [
                    for (final a in _amplitudes) ...[
                      AnimatedContainer(
                        duration: const Duration(milliseconds: 100),
                        width: 4, height: 6 + 22 * a,
                        decoration: BoxDecoration(
                            color: r.marigold,
                            borderRadius: BorderRadius.circular(2)),
                      ),
                      const SizedBox(width: 3),
                    ],
                  ]),
            ),
          ),
        SizedBox(
          width: Tokens.tapHero, height: Tokens.tapHero,
          child: FloatingActionButton(
            backgroundColor: _recording ? r.marigold : r.marigold,
            shape: const CircleBorder(),
            onPressed: _toggleRecord,
            tooltip: _recording ? 'Finish and send' : 'Hold to speak',
            child: Icon(_recording ? Icons.stop : Icons.mic,
                size: 40, color: Colors.white),
          ),
        ),
        Padding(
          padding: const EdgeInsets.only(top: 6),
          child: Text(_recording ? 'Listening… tap to finish' : 'Tap to speak',
              style: TextStyle(
                  fontSize: 13,
                  fontWeight: FontWeight.w600,
                  color: r.inkSoft)),
        ),
      ]);

  Widget _devStrip(Roles r) => Container(
        color: r.paper,
        padding: const EdgeInsets.fromLTRB(10, 4, 10, 8),
        child: Row(children: [
          _devBtn(r, 'receive next note', _receiveNext),
          const SizedBox(width: 6),
          _devBtn(r, store.online ? 'go offline' : 'go online',
              () => store.setOnline(!store.online)),
          const Spacer(),
          Text('${widget.provider.mode} · ${widget.provider.model}',
              style: TextStyle(fontSize: 11, color: r.inkFaint)),
        ]),
      );

  Widget _devBtn(Roles r, String label, VoidCallback onTap) => Opacity(
        opacity: 0.75,
        child: FilledButton(
          style: FilledButton.styleFrom(
              backgroundColor: r.ink,
              foregroundColor: r.paper,
              minimumSize: const Size(0, 34),
              padding: const EdgeInsets.symmetric(horizontal: 12),
              textStyle: const TextStyle(fontSize: 12)),
          onPressed: onTap,
          child: Text(label),
        ),
      );

  Widget _pill(Roles r,
      {required IconData icon,
      required String label,
      required Color fg,
      required Color bg}) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 7),
      decoration: BoxDecoration(
          color: bg, borderRadius: BorderRadius.circular(999)),
      child: Row(mainAxisSize: MainAxisSize.min, children: [
        Icon(icon, size: 15, color: fg),
        const SizedBox(width: 6),
        Flexible(
            child: Text(label,
                style: TextStyle(
                    fontSize: 13, fontWeight: FontWeight.w600, color: fg))),
      ]),
    );
  }
}
