/* AUTOMATICALLY GENERATED CODE DO NOT MODIFY */
/*   To generate run: "serverpod generate"    */

// ignore_for_file: implementation_imports
// ignore_for_file: library_private_types_in_public_api
// ignore_for_file: non_constant_identifier_names
// ignore_for_file: public_member_api_docs
// ignore_for_file: type_literal_in_constant_pattern
// ignore_for_file: use_super_parameters
// ignore_for_file: invalid_use_of_internal_member

// ignore_for_file: no_leading_underscores_for_library_prefixes

import 'package:serverpod_client/serverpod_client.dart' as _i1;

abstract class VoiceNote implements _i1.SerializableModel {
  VoiceNote._({
    this.id,
    required this.familyId,
    required this.senderName,
    required this.audioRef,
    required this.lang,
    required this.durationMs,
    required this.receivedAt,
  });

  factory VoiceNote({
    int? id,
    required int familyId,
    required String senderName,
    required String audioRef,
    required String lang,
    required int durationMs,
    required DateTime receivedAt,
  }) = _VoiceNoteImpl;

  factory VoiceNote.fromJson(Map<String, dynamic> jsonSerialization) {
    return VoiceNote(
      id: jsonSerialization['id'] as int?,
      familyId: jsonSerialization['familyId'] as int,
      senderName: jsonSerialization['senderName'] as String,
      audioRef: jsonSerialization['audioRef'] as String,
      lang: jsonSerialization['lang'] as String,
      durationMs: jsonSerialization['durationMs'] as int,
      receivedAt: _i1.DateTimeJsonExtension.fromJson(
        jsonSerialization['receivedAt'],
      ),
    );
  }

  /// The database id, set if the object has been inserted into the
  /// database or if it has been fetched from the database. Otherwise,
  /// the id will be null.
  int? id;

  int familyId;

  String senderName;

  String audioRef;

  String lang;

  int durationMs;

  DateTime receivedAt;

  /// Returns a shallow copy of this [VoiceNote]
  /// with some or all fields replaced by the given arguments.
  @_i1.useResult
  VoiceNote copyWith({
    int? id,
    int? familyId,
    String? senderName,
    String? audioRef,
    String? lang,
    int? durationMs,
    DateTime? receivedAt,
  });
  @override
  Map<String, dynamic> toJson() {
    return {
      '__className__': 'VoiceNote',
      if (id != null) 'id': id,
      'familyId': familyId,
      'senderName': senderName,
      'audioRef': audioRef,
      'lang': lang,
      'durationMs': durationMs,
      'receivedAt': receivedAt.toJson(),
    };
  }

  @override
  String toString() {
    return _i1.SerializationManager.encode(this);
  }
}

class _Undefined {}

class _VoiceNoteImpl extends VoiceNote {
  _VoiceNoteImpl({
    int? id,
    required int familyId,
    required String senderName,
    required String audioRef,
    required String lang,
    required int durationMs,
    required DateTime receivedAt,
  }) : super._(
         id: id,
         familyId: familyId,
         senderName: senderName,
         audioRef: audioRef,
         lang: lang,
         durationMs: durationMs,
         receivedAt: receivedAt,
       );

  /// Returns a shallow copy of this [VoiceNote]
  /// with some or all fields replaced by the given arguments.
  @_i1.useResult
  @override
  VoiceNote copyWith({
    Object? id = _Undefined,
    int? familyId,
    String? senderName,
    String? audioRef,
    String? lang,
    int? durationMs,
    DateTime? receivedAt,
  }) {
    return VoiceNote(
      id: id is int? ? id : this.id,
      familyId: familyId ?? this.familyId,
      senderName: senderName ?? this.senderName,
      audioRef: audioRef ?? this.audioRef,
      lang: lang ?? this.lang,
      durationMs: durationMs ?? this.durationMs,
      receivedAt: receivedAt ?? this.receivedAt,
    );
  }
}
