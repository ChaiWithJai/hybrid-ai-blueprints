BEGIN;

--
-- ACTION CREATE TABLE
--
CREATE TABLE "voice_note" (
    "id" bigserial PRIMARY KEY,
    "familyId" bigint NOT NULL,
    "senderName" text NOT NULL,
    "audioRef" text NOT NULL,
    "lang" text NOT NULL,
    "durationMs" bigint NOT NULL,
    "receivedAt" timestamp without time zone NOT NULL
);

-- Indexes
CREATE INDEX "voice_note_family_received_idx" ON "voice_note" USING btree ("familyId", "receivedAt");


--
-- MIGRATION VERSION FOR bonsai_edge_pod
--
INSERT INTO "serverpod_migrations" ("module", "version", "timestamp")
    VALUES ('bonsai_edge_pod', '20260901033012558', now())
    ON CONFLICT ("module")
    DO UPDATE SET "version" = '20260901033012558', "timestamp" = now();

--
-- MIGRATION VERSION FOR serverpod
--
INSERT INTO "serverpod_migrations" ("module", "version", "timestamp")
    VALUES ('serverpod', '20260129180959368', now())
    ON CONFLICT ("module")
    DO UPDATE SET "version" = '20260129180959368', "timestamp" = now();

--
-- MIGRATION VERSION FOR serverpod_auth_idp
--
INSERT INTO "serverpod_migrations" ("module", "version", "timestamp")
    VALUES ('serverpod_auth_idp', '20260213194423028', now())
    ON CONFLICT ("module")
    DO UPDATE SET "version" = '20260213194423028', "timestamp" = now();

--
-- MIGRATION VERSION FOR serverpod_auth_core
--
INSERT INTO "serverpod_migrations" ("module", "version", "timestamp")
    VALUES ('serverpod_auth_core', '20260129181112269', now())
    ON CONFLICT ("module")
    DO UPDATE SET "version" = '20260129181112269', "timestamp" = now();


COMMIT;
