// The family store: voice notes, the offline queue, and persistence.
// Same semantics the Python edgekit store proved: a note created while
// offline is 'queued' and moves to 'synced' only when connectivity
// returns and sync() runs. State survives app restarts (SharedPreferences
// — localStorage on web), so a queued reply outlives a reload: the
// offline promise is structural, not cosmetic.

import 'dart:convert';

import 'package:flutter/foundation.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'bonsai.dart';

class VoiceNote {
  final int id;
  final String audioRef;
  final String lang;
  final int durationMs;
  final String senderName;
  final String transcript;
  final String asrMode; // fixture | typed — recorded, never faked
  final String direction; // in | out
  String summary;
  bool needsReply;
  String summaryMode; // model | fallback | own | pending
  String syncState; // local | queued | synced
  final String? audioDataUrl; // real recorded audio (data: url), when out

  VoiceNote({
    required this.id,
    required this.audioRef,
    required this.lang,
    required this.durationMs,
    required this.senderName,
    required this.transcript,
    required this.asrMode,
    required this.direction,
    this.summary = '',
    this.needsReply = false,
    this.summaryMode = 'pending',
    this.syncState = 'local',
    this.audioDataUrl,
  });

  Map<String, dynamic> toJson() => {
        'id': id, 'audioRef': audioRef, 'lang': lang,
        'durationMs': durationMs, 'senderName': senderName,
        'transcript': transcript, 'asrMode': asrMode,
        'direction': direction, 'summary': summary,
        'needsReply': needsReply, 'summaryMode': summaryMode,
        'syncState': syncState, 'audioDataUrl': audioDataUrl,
      };

  factory VoiceNote.fromJson(Map<String, dynamic> j) => VoiceNote(
        id: j['id'] as int,
        audioRef: j['audioRef'] as String,
        lang: j['lang'] as String,
        durationMs: j['durationMs'] as int,
        senderName: j['senderName'] as String,
        transcript: j['transcript'] as String,
        asrMode: j['asrMode'] as String,
        direction: j['direction'] as String,
        summary: j['summary'] as String? ?? '',
        needsReply: j['needsReply'] as bool? ?? false,
        summaryMode: j['summaryMode'] as String? ?? 'pending',
        syncState: j['syncState'] as String? ?? 'local',
        audioDataUrl: j['audioDataUrl'] as String?,
      );
}

class FamilySettings {
  String familyName;
  String lang; // the reader's language for UI-adjacent choices
  bool elderMode;
  FamilySettings(
      {this.familyName = '', this.lang = 'hi', this.elderMode = false});

  Map<String, dynamic> toJson() =>
      {'familyName': familyName, 'lang': lang, 'elderMode': elderMode};
  factory FamilySettings.fromJson(Map<String, dynamic> j) => FamilySettings(
        familyName: j['familyName'] as String? ?? '',
        lang: j['lang'] as String? ?? 'hi',
        elderMode: j['elderMode'] as bool? ?? false,
      );
}

class FamilyStore extends ChangeNotifier {
  final List<VoiceNote> notes = [];
  FamilySettings settings = FamilySettings();
  bool online = true;
  bool onboarded = false;
  int _nextId = 1;
  SharedPreferences? _prefs;

  Future<void> load() async {
    _prefs = await SharedPreferences.getInstance();
    final raw = _prefs!.getString('awaaz.notes');
    if (raw != null) {
      notes
        ..clear()
        ..addAll((jsonDecode(raw) as List)
            .map((j) => VoiceNote.fromJson(j as Map<String, dynamic>)));
      _nextId = notes.isEmpty
          ? 1
          : notes.map((n) => n.id).reduce((a, b) => a > b ? a : b) + 1;
    }
    final s = _prefs!.getString('awaaz.settings');
    if (s != null) {
      settings = FamilySettings.fromJson(jsonDecode(s) as Map<String, dynamic>);
    }
    onboarded = _prefs!.getBool('awaaz.onboarded') ?? false;
    online = _prefs!.getBool('awaaz.online') ?? true;
    notifyListeners();
  }

  Future<void> _persist() async {
    await _prefs?.setString(
        'awaaz.notes', jsonEncode(notes.map((n) => n.toJson()).toList()));
    await _prefs?.setString('awaaz.settings', jsonEncode(settings.toJson()));
    await _prefs?.setBool('awaaz.onboarded', onboarded);
    await _prefs?.setBool('awaaz.online', online);
  }

  Future<void> completeOnboarding(FamilySettings s) async {
    settings = s;
    onboarded = true;
    await _persist();
    notifyListeners();
  }

  VoiceNote add({
    required String audioRef,
    required String lang,
    required int durationMs,
    required String senderName,
    required String transcript,
    required String asrMode,
    required String direction,
    String? audioDataUrl,
  }) {
    final note = VoiceNote(
      id: _nextId++,
      audioRef: audioRef,
      lang: lang,
      durationMs: durationMs,
      senderName: senderName,
      transcript: transcript,
      asrMode: asrMode,
      direction: direction,
      audioDataUrl: audioDataUrl,
      syncState: online ? 'synced' : 'queued',
    );
    notes.add(note);
    _persist();
    notifyListeners();
    return note;
  }

  /// Run the intelligence step for one note and persist the honest result.
  Future<void> digest(Provider provider, VoiceNote note) async {
    if (note.direction == 'out') {
      // Your own voice needs no summary — you said it.
      note
        ..summary = note.transcript.length > 140
            ? note.transcript.substring(0, 140)
            : note.transcript
        ..needsReply = false
        ..summaryMode = 'own';
    } else {
      final r =
          await summarize(provider, note.audioRef, note.lang, note.transcript);
      note
        ..summary = r.summary
        ..needsReply = r.needsReply
        ..summaryMode = r.summaryMode;
    }
    await _persist();
    notifyListeners();
  }

  Future<void> setOnline(bool value) async {
    online = value;
    if (online) {
      for (final n in notes.where((n) => n.syncState == 'queued')) {
        n.syncState = 'synced';
      }
    }
    await _persist();
    notifyListeners();
  }

  int get queuedCount =>
      notes.where((n) => n.syncState == 'queued').length;
}
