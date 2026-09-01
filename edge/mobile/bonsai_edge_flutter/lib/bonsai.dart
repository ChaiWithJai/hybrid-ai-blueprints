// The on-device intelligence seam: a loopback-only LM Studio client,
// a deterministic fixture provider, and the grounding guard — the same
// contract the Python pipeline enforces (edge/mobile/demos/01/app.py),
// ported so a summary that shares no content word with its transcript
// never reaches the family. The model speaks about what others sent, or
// it does not speak.

import 'dart:convert';

import 'package:http/http.dart' as http;

const kBonsaiBase = 'http://127.0.0.1:1234';
const kBonsaiModel = '1.7b';

abstract class Provider {
  String get mode;
  String get model;
  Future<String> chat(String system, String user, {int maxTokens = 160});
}

class BonsaiProvider implements Provider {
  @override
  final String mode = 'live';
  @override
  final String model;
  final String baseUrl;
  final http.Client _client;

  BonsaiProvider({this.baseUrl = kBonsaiBase, this.model = kBonsaiModel,
      http.Client? client})
      : _client = client ?? http.Client() {
    if (!baseUrl.startsWith('http://127.0.0.1') &&
        !baseUrl.startsWith('http://[::1]')) {
      throw ArgumentError('local provider must be a loopback address');
    }
  }

  static Future<bool> available(
      {String baseUrl = kBonsaiBase, String model = kBonsaiModel}) async {
    try {
      final resp = await http
          .get(Uri.parse('$baseUrl/v1/models'))
          .timeout(const Duration(seconds: 3));
      final ids = (jsonDecode(resp.body)['data'] as List)
          .map((m) => m['id'] as String);
      return ids.contains(model);
    } catch (_) {
      return false;
    }
  }

  @override
  Future<String> chat(String system, String user,
      {int maxTokens = 160}) async {
    final resp = await _client.post(
      Uri.parse('$baseUrl/v1/chat/completions'),
      headers: {'Content-Type': 'application/json'},
      body: jsonEncode({
        'model': model,
        'messages': [
          {'role': 'system', 'content': system},
          {'role': 'user', 'content': user},
        ],
        'max_tokens': maxTokens,
        'temperature': 0.2,
      }),
    );
    final body = jsonDecode(utf8.decode(resp.bodyBytes));
    return (body['choices'][0]['message']['content'] as String).trim();
  }
}

/// Deterministic provider: first key found in the prompt wins; a missing
/// fixture throws — silent fallthrough would hide broken routing.
class FixtureProvider implements Provider {
  @override
  final String mode = 'fixture';
  @override
  final String model = 'fixture';
  final Map<String, String> responses;
  final List<String> calls = [];

  FixtureProvider(this.responses);

  @override
  Future<String> chat(String system, String user,
      {int maxTokens = 160}) async {
    calls.add(user);
    for (final entry in responses.entries) {
      if (entry.key != 'default' && user.contains(entry.key)) {
        return entry.value;
      }
    }
    final fallback = responses['default'];
    if (fallback != null) return fallback;
    throw StateError('no fixture matches prompt: $user');
  }
}

// ---- the grounding guard (ported verbatim in spirit from app.py) ----

/// Split on whitespace/punctuation, never on character class: \w-style
/// tokenizing shatters Bengali/Devanagari combining marks — the round-1
/// Python bug, kept fixed here by construction.
Set<String> contentWords(String text, {int minLen = 4}) {
  final parts = text.split(RegExp(r"[\s,।؛۔;:.!?()\[\]{}" '"' r"'«»—–-]+"));
  return parts.where((w) => w.length >= minLen).toSet();
}

class SummaryResult {
  final String summary;
  final bool needsReply;
  final String summaryMode; // model | fallback | own
  const SummaryResult(this.summary, this.needsReply, this.summaryMode);
}

const summarizeSystem =
    'You summarize one family voice message. Reply in the SAME language as '
    'the message, in exactly this format and nothing else:\n'
    'SUMMARY: <one line, under 28 words>\n'
    'NEEDS_REPLY: <yes or no>';

(String, bool) parseSummary(String raw) {
  var summary = '';
  var needsReply = true;
  for (final line in raw.split('\n')) {
    final upper = line.toUpperCase();
    if (upper.startsWith('SUMMARY:')) {
      summary = line.substring(line.indexOf(':') + 1).trim();
    } else if (upper.startsWith('NEEDS_REPLY:')) {
      needsReply =
          line.substring(line.indexOf(':') + 1).trim().toLowerCase().contains('yes');
    }
  }
  return (summary, needsReply);
}

bool grounded(String summary, String transcript, {int minOverlap = 1}) {
  if (summary.isEmpty) return false;
  final overlap =
      contentWords(summary).intersection(contentWords(transcript));
  return overlap.length >= minOverlap;
}

/// The full pipeline step: model call -> parse -> guard -> honest result.
Future<SummaryResult> summarize(
    Provider provider, String audioRef, String lang, String transcript) async {
  final raw = await provider.chat(
      summarizeSystem, '[$audioRef] ($lang) $transcript');
  final (summary, needsReply) = parseSummary(raw);
  if (grounded(summary, transcript)) {
    return SummaryResult(summary, needsReply, 'model');
  }
  // Evidence-safe fallback, visibly labeled — never silent.
  final excerpt = transcript.length > 140
      ? transcript.substring(0, 140)
      : transcript;
  return SummaryResult('[transcript excerpt] $excerpt', true, 'fallback');
}
