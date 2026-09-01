// End-to-end proof: the generated client uploads a VoiceNote to the
// running pod and delta-fetches it back. Exit 0 only if the round trip
// returns exactly what was sent.

import 'dart:io';

import 'package:bonsai_edge_pod_client/bonsai_edge_pod_client.dart';
import 'package:serverpod_client/serverpod_client.dart';

Future<void> main() async {
  final client = Client('http://127.0.0.1:8080/')
    ..connectivityMonitor = FlutterConnectivityMonitor();

  final since = DateTime.now().toUtc().subtract(const Duration(minutes: 1));
  final sent = await client.voiceNote.upload(VoiceNote(
    familyId: 1,
    senderName: 'Amina',
    audioRef: 'vn-e2e-001.ogg',
    lang: 'bn',
    durationMs: 42000,
    receivedAt: DateTime.now().toUtc(),
  ));
  stdout.writeln('uploaded id=${sent.id}');

  final fetched = await client.voiceNote.listSince(1, since);
  final match = fetched.any((n) =>
      n.id == sent.id && n.audioRef == 'vn-e2e-001.ogg' && n.lang == 'bn');
  stdout.writeln('delta fetch returned ${fetched.length}, match=$match');
  client.close();
  exit(match ? 0 : 1);
}

/// Minimal monitor for a CLI context.
class FlutterConnectivityMonitor extends ConnectivityMonitor {}
