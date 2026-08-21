# Sourcing reference audio from Restream

How to get usable clone reference audio out of a Restream recording library.
For what to do with it afterwards, see
[VOICE_CLONE_SETUP.md](VOICE_CLONE_SETUP.md).

This is one convenient source, not a requirement — any clean recording of your
own voice works.

## Use "Split audio tracks", not the mixed audio

Each recording's download dialog offers several formats. The important one is
**Split audio tracks (ZIP)**: Restream stores **each participant's microphone as
its own file**, named by participant:

```
Jai Bhagat — Camera — Audio 1.m4a        <- one speaker, isolated
Audio — Background Music — Audio 1.m4a   <- music on a separate track
Jai & Guest — Camera — Audio 1.m4a      <- MIXED, two speakers: unusable
```

This matters more than any processing step: it removes the need for speaker
diarization entirely, and it separates background music from speech. On a
recording with music, the music lands on its own track and the voice track is
clean.

**Check the track names before trusting the file count.** A ZIP containing one
file is not necessarily one speaker — a two-person episode produced a single
`Jai & Guest` track, which is a mix and cannot be used as a reference. Solo
episodes are the reliable source.

The plain **Audio (M4A)** download is the full mix; it is fine when the episode
is a solo recording, and useless when it is not.

## Downloading

The dialog's own download buttons work and require no API access. Two practical
notes:

- **Browser-automation download helpers often time out** on files of this size
  (audio 90–200 MB, video 1.5–2.5 GB) while the browser's own downloader keeps
  going and completes. Trigger the download, then poll `~/Downloads` rather than
  waiting on the automation call.
- **Programmatic download is gated.** `streaming-recordings.restream.io`
  exposes `/recordings/{suid}` and `/studio-recordings/{suid}/metadata`, and the
  latter returns per-track **pre-signed S3 URLs** (24 h expiry, no auth needed
  to fetch) — ideal for `curl`. But the metadata calls require an
  `x-axsrf-token` header that is not in cookies or storage, so replaying them
  outside the page did not work. The UI path is the supported route.

Recording ids appear in the page's thumbnail URLs as `{user_id}-{recording_id}`
if you need to enumerate a library.

## Picking a segment

Restream recordings are long (45–105 min) and mostly unsuitable — the usable
part is a stretch of uninterrupted speech.

```bash
# candidate runs, bounded by real pauses
ffmpeg -i "Jai Bhagat — Camera — Audio 1.m4a" \
  -af "pan=mono|c0=0.5*c0+0.5*c1,silencedetect=noise=-33dB:d=0.6" \
  -f null - 2>&1 | grep silence_
```

Guidance from measuring 963 segments across 10 recordings:

- **Skip the first ~10 minutes.** Intros, level checks and greetings are atypical
  of normal delivery.
- **Within-recording variance is as large as between-recording variance.** One
  recording produced both the 5th-best and the 23rd-best clone of 24 candidates.
  Do not judge a session by one clip.
- **Watch the peak level.** Several recordings peaked at −0.2 to −0.9 dBFS,
  meaning the stream was hard-limited; squashed dynamics make a poorer
  reference. Prefer clips with real headroom.
- **A clip ending mid-sentence measurably hurts**, and no acoustic metric shows
  it. Read the transcript, or have a model read it.

Then follow
[VOICE_CLONE_SETUP.md § Building a reference](VOICE_CLONE_SETUP.md#building-a-reference)
to cut, normalise and transcribe it, and
[§ Choosing between candidates](VOICE_CLONE_SETUP.md#choosing-between-candidates)
to pick between them by measurement rather than by ear alone.

## Privacy

Downloaded recordings and any clips cut from them are biometric data. Keep them
outside the repository (`app/voices/` is gitignored) and do not commit them. See
[SECURITY.md](../../SECURITY.md).
