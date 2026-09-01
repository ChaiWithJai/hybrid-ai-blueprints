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

import 'package:serverpod/serverpod.dart' as _i1;

abstract class VoiceNote
    implements _i1.TableRow<int?>, _i1.ProtocolSerialization {
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

  static final t = VoiceNoteTable();

  static const db = VoiceNoteRepository._();

  @override
  int? id;

  int familyId;

  String senderName;

  String audioRef;

  String lang;

  int durationMs;

  DateTime receivedAt;

  @override
  _i1.Table<int?> get table => t;

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
  Map<String, dynamic> toJsonForProtocol() {
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

  static VoiceNoteInclude include() {
    return VoiceNoteInclude._();
  }

  static VoiceNoteIncludeList includeList({
    _i1.WhereExpressionBuilder<VoiceNoteTable>? where,
    int? limit,
    int? offset,
    _i1.OrderByBuilder<VoiceNoteTable>? orderBy,
    bool orderDescending = false,
    _i1.OrderByListBuilder<VoiceNoteTable>? orderByList,
    VoiceNoteInclude? include,
  }) {
    return VoiceNoteIncludeList._(
      where: where,
      limit: limit,
      offset: offset,
      orderBy: orderBy?.call(VoiceNote.t),
      orderDescending: orderDescending,
      orderByList: orderByList?.call(VoiceNote.t),
      include: include,
    );
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

class VoiceNoteUpdateTable extends _i1.UpdateTable<VoiceNoteTable> {
  VoiceNoteUpdateTable(super.table);

  _i1.ColumnValue<int, int> familyId(int value) => _i1.ColumnValue(
    table.familyId,
    value,
  );

  _i1.ColumnValue<String, String> senderName(String value) => _i1.ColumnValue(
    table.senderName,
    value,
  );

  _i1.ColumnValue<String, String> audioRef(String value) => _i1.ColumnValue(
    table.audioRef,
    value,
  );

  _i1.ColumnValue<String, String> lang(String value) => _i1.ColumnValue(
    table.lang,
    value,
  );

  _i1.ColumnValue<int, int> durationMs(int value) => _i1.ColumnValue(
    table.durationMs,
    value,
  );

  _i1.ColumnValue<DateTime, DateTime> receivedAt(DateTime value) =>
      _i1.ColumnValue(
        table.receivedAt,
        value,
      );
}

class VoiceNoteTable extends _i1.Table<int?> {
  VoiceNoteTable({super.tableRelation}) : super(tableName: 'voice_note') {
    updateTable = VoiceNoteUpdateTable(this);
    familyId = _i1.ColumnInt(
      'familyId',
      this,
    );
    senderName = _i1.ColumnString(
      'senderName',
      this,
    );
    audioRef = _i1.ColumnString(
      'audioRef',
      this,
    );
    lang = _i1.ColumnString(
      'lang',
      this,
    );
    durationMs = _i1.ColumnInt(
      'durationMs',
      this,
    );
    receivedAt = _i1.ColumnDateTime(
      'receivedAt',
      this,
    );
  }

  late final VoiceNoteUpdateTable updateTable;

  late final _i1.ColumnInt familyId;

  late final _i1.ColumnString senderName;

  late final _i1.ColumnString audioRef;

  late final _i1.ColumnString lang;

  late final _i1.ColumnInt durationMs;

  late final _i1.ColumnDateTime receivedAt;

  @override
  List<_i1.Column> get columns => [
    id,
    familyId,
    senderName,
    audioRef,
    lang,
    durationMs,
    receivedAt,
  ];
}

class VoiceNoteInclude extends _i1.IncludeObject {
  VoiceNoteInclude._();

  @override
  Map<String, _i1.Include?> get includes => {};

  @override
  _i1.Table<int?> get table => VoiceNote.t;
}

class VoiceNoteIncludeList extends _i1.IncludeList {
  VoiceNoteIncludeList._({
    _i1.WhereExpressionBuilder<VoiceNoteTable>? where,
    super.limit,
    super.offset,
    super.orderBy,
    super.orderDescending,
    super.orderByList,
    super.include,
  }) {
    super.where = where?.call(VoiceNote.t);
  }

  @override
  Map<String, _i1.Include?> get includes => include?.includes ?? {};

  @override
  _i1.Table<int?> get table => VoiceNote.t;
}

class VoiceNoteRepository {
  const VoiceNoteRepository._();

  /// Returns a list of [VoiceNote]s matching the given query parameters.
  ///
  /// Use [where] to specify which items to include in the return value.
  /// If none is specified, all items will be returned.
  ///
  /// To specify the order of the items use [orderBy] or [orderByList]
  /// when sorting by multiple columns.
  ///
  /// The maximum number of items can be set by [limit]. If no limit is set,
  /// all items matching the query will be returned.
  ///
  /// [offset] defines how many items to skip, after which [limit] (or all)
  /// items are read from the database.
  ///
  /// ```dart
  /// var persons = await Persons.db.find(
  ///   session,
  ///   where: (t) => t.lastName.equals('Jones'),
  ///   orderBy: (t) => t.firstName,
  ///   limit: 100,
  /// );
  /// ```
  Future<List<VoiceNote>> find(
    _i1.DatabaseSession session, {
    _i1.WhereExpressionBuilder<VoiceNoteTable>? where,
    int? limit,
    int? offset,
    _i1.OrderByBuilder<VoiceNoteTable>? orderBy,
    bool orderDescending = false,
    _i1.OrderByListBuilder<VoiceNoteTable>? orderByList,
    _i1.Transaction? transaction,
    _i1.LockMode? lockMode,
    _i1.LockBehavior? lockBehavior,
  }) async {
    return session.db.find<VoiceNote>(
      where: where?.call(VoiceNote.t),
      orderBy: orderBy?.call(VoiceNote.t),
      orderByList: orderByList?.call(VoiceNote.t),
      orderDescending: orderDescending,
      limit: limit,
      offset: offset,
      transaction: transaction,
      lockMode: lockMode,
      lockBehavior: lockBehavior,
    );
  }

  /// Returns the first matching [VoiceNote] matching the given query parameters.
  ///
  /// Use [where] to specify which items to include in the return value.
  /// If none is specified, all items will be returned.
  ///
  /// To specify the order use [orderBy] or [orderByList]
  /// when sorting by multiple columns.
  ///
  /// [offset] defines how many items to skip, after which the next one will be picked.
  ///
  /// ```dart
  /// var youngestPerson = await Persons.db.findFirstRow(
  ///   session,
  ///   where: (t) => t.lastName.equals('Jones'),
  ///   orderBy: (t) => t.age,
  /// );
  /// ```
  Future<VoiceNote?> findFirstRow(
    _i1.DatabaseSession session, {
    _i1.WhereExpressionBuilder<VoiceNoteTable>? where,
    int? offset,
    _i1.OrderByBuilder<VoiceNoteTable>? orderBy,
    bool orderDescending = false,
    _i1.OrderByListBuilder<VoiceNoteTable>? orderByList,
    _i1.Transaction? transaction,
    _i1.LockMode? lockMode,
    _i1.LockBehavior? lockBehavior,
  }) async {
    return session.db.findFirstRow<VoiceNote>(
      where: where?.call(VoiceNote.t),
      orderBy: orderBy?.call(VoiceNote.t),
      orderByList: orderByList?.call(VoiceNote.t),
      orderDescending: orderDescending,
      offset: offset,
      transaction: transaction,
      lockMode: lockMode,
      lockBehavior: lockBehavior,
    );
  }

  /// Finds a single [VoiceNote] by its [id] or null if no such row exists.
  Future<VoiceNote?> findById(
    _i1.DatabaseSession session,
    int id, {
    _i1.Transaction? transaction,
    _i1.LockMode? lockMode,
    _i1.LockBehavior? lockBehavior,
  }) async {
    return session.db.findById<VoiceNote>(
      id,
      transaction: transaction,
      lockMode: lockMode,
      lockBehavior: lockBehavior,
    );
  }

  /// Inserts all [VoiceNote]s in the list and returns the inserted rows.
  ///
  /// The returned [VoiceNote]s will have their `id` fields set.
  ///
  /// This is an atomic operation, meaning that if one of the rows fails to
  /// insert, none of the rows will be inserted.
  ///
  /// If [ignoreConflicts] is set to `true`, rows that conflict with existing
  /// rows are silently skipped, and only the successfully inserted rows are
  /// returned.
  Future<List<VoiceNote>> insert(
    _i1.DatabaseSession session,
    List<VoiceNote> rows, {
    _i1.Transaction? transaction,
    bool ignoreConflicts = false,
  }) async {
    return session.db.insert<VoiceNote>(
      rows,
      transaction: transaction,
      ignoreConflicts: ignoreConflicts,
    );
  }

  /// Inserts a single [VoiceNote] and returns the inserted row.
  ///
  /// The returned [VoiceNote] will have its `id` field set.
  Future<VoiceNote> insertRow(
    _i1.DatabaseSession session,
    VoiceNote row, {
    _i1.Transaction? transaction,
  }) async {
    return session.db.insertRow<VoiceNote>(
      row,
      transaction: transaction,
    );
  }

  /// Updates all [VoiceNote]s in the list and returns the updated rows. If
  /// [columns] is provided, only those columns will be updated. Defaults to
  /// all columns.
  /// This is an atomic operation, meaning that if one of the rows fails to
  /// update, none of the rows will be updated.
  Future<List<VoiceNote>> update(
    _i1.DatabaseSession session,
    List<VoiceNote> rows, {
    _i1.ColumnSelections<VoiceNoteTable>? columns,
    _i1.Transaction? transaction,
  }) async {
    return session.db.update<VoiceNote>(
      rows,
      columns: columns?.call(VoiceNote.t),
      transaction: transaction,
    );
  }

  /// Updates a single [VoiceNote]. The row needs to have its id set.
  /// Optionally, a list of [columns] can be provided to only update those
  /// columns. Defaults to all columns.
  Future<VoiceNote> updateRow(
    _i1.DatabaseSession session,
    VoiceNote row, {
    _i1.ColumnSelections<VoiceNoteTable>? columns,
    _i1.Transaction? transaction,
  }) async {
    return session.db.updateRow<VoiceNote>(
      row,
      columns: columns?.call(VoiceNote.t),
      transaction: transaction,
    );
  }

  /// Updates a single [VoiceNote] by its [id] with the specified [columnValues].
  /// Returns the updated row or null if no row with the given id exists.
  Future<VoiceNote?> updateById(
    _i1.DatabaseSession session,
    int id, {
    required _i1.ColumnValueListBuilder<VoiceNoteUpdateTable> columnValues,
    _i1.Transaction? transaction,
  }) async {
    return session.db.updateById<VoiceNote>(
      id,
      columnValues: columnValues(VoiceNote.t.updateTable),
      transaction: transaction,
    );
  }

  /// Updates all [VoiceNote]s matching the [where] expression with the specified [columnValues].
  /// Returns the list of updated rows.
  Future<List<VoiceNote>> updateWhere(
    _i1.DatabaseSession session, {
    required _i1.ColumnValueListBuilder<VoiceNoteUpdateTable> columnValues,
    required _i1.WhereExpressionBuilder<VoiceNoteTable> where,
    int? limit,
    int? offset,
    _i1.OrderByBuilder<VoiceNoteTable>? orderBy,
    _i1.OrderByListBuilder<VoiceNoteTable>? orderByList,
    bool orderDescending = false,
    _i1.Transaction? transaction,
  }) async {
    return session.db.updateWhere<VoiceNote>(
      columnValues: columnValues(VoiceNote.t.updateTable),
      where: where(VoiceNote.t),
      limit: limit,
      offset: offset,
      orderBy: orderBy?.call(VoiceNote.t),
      orderByList: orderByList?.call(VoiceNote.t),
      orderDescending: orderDescending,
      transaction: transaction,
    );
  }

  /// Deletes all [VoiceNote]s in the list and returns the deleted rows.
  /// This is an atomic operation, meaning that if one of the rows fail to
  /// be deleted, none of the rows will be deleted.
  Future<List<VoiceNote>> delete(
    _i1.DatabaseSession session,
    List<VoiceNote> rows, {
    _i1.Transaction? transaction,
  }) async {
    return session.db.delete<VoiceNote>(
      rows,
      transaction: transaction,
    );
  }

  /// Deletes a single [VoiceNote].
  Future<VoiceNote> deleteRow(
    _i1.DatabaseSession session,
    VoiceNote row, {
    _i1.Transaction? transaction,
  }) async {
    return session.db.deleteRow<VoiceNote>(
      row,
      transaction: transaction,
    );
  }

  /// Deletes all rows matching the [where] expression.
  Future<List<VoiceNote>> deleteWhere(
    _i1.DatabaseSession session, {
    required _i1.WhereExpressionBuilder<VoiceNoteTable> where,
    _i1.Transaction? transaction,
  }) async {
    return session.db.deleteWhere<VoiceNote>(
      where: where(VoiceNote.t),
      transaction: transaction,
    );
  }

  /// Counts the number of rows matching the [where] expression. If omitted,
  /// will return the count of all rows in the table.
  Future<int> count(
    _i1.DatabaseSession session, {
    _i1.WhereExpressionBuilder<VoiceNoteTable>? where,
    int? limit,
    _i1.Transaction? transaction,
  }) async {
    return session.db.count<VoiceNote>(
      where: where?.call(VoiceNote.t),
      limit: limit,
      transaction: transaction,
    );
  }

  /// Acquires row-level locks on [VoiceNote] rows matching the [where] expression.
  Future<void> lockRows(
    _i1.DatabaseSession session, {
    required _i1.WhereExpressionBuilder<VoiceNoteTable> where,
    required _i1.LockMode lockMode,
    required _i1.Transaction transaction,
    _i1.LockBehavior lockBehavior = _i1.LockBehavior.wait,
  }) async {
    return session.db.lockRows<VoiceNote>(
      where: where(VoiceNote.t),
      lockMode: lockMode,
      lockBehavior: lockBehavior,
      transaction: transaction,
    );
  }
}
