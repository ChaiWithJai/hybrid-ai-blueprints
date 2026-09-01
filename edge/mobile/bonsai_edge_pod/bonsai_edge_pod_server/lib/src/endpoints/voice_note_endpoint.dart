// Family voice-note sync: upload metadata, delta-fetch since a timestamp.
// The client treats streams as an optimization over listSince — this
// endpoint is the poll-fallback path the asymptote guardrails require.

import 'package:serverpod/serverpod.dart';

import '../generated/protocol.dart';

class VoiceNoteEndpoint extends Endpoint {
  Future<VoiceNote> upload(Session session, VoiceNote note) async {
    final saved = await VoiceNote.db.insertRow(session, note);
    session.messages.postMessage('family_${note.familyId}', saved);
    return saved;
  }

  Future<List<VoiceNote>> listSince(
      Session session, int familyId, DateTime since) async {
    return VoiceNote.db.find(
      session,
      where: (t) => t.familyId.equals(familyId) & (t.receivedAt > since),
      orderBy: (t) => t.receivedAt,
    );
  }
}
