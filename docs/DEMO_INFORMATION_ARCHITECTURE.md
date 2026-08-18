# Prism Vault demo page structure

Status: approved design for the current demo  
Date: August 17, 2026

## Design rule

Every page must answer three questions without explanation:

1. Where am I?
2. What can I do here?
3. What should I do next?

The deal room has one root job. The team must decide whether to advance, pause,
or stop a deal, and know what must happen next. Every segment and phrase must
support that job. The full defense is in
[`DEAL_ROOM_CONTENT_GRAPH.md`](DEAL_ROOM_CONTENT_GRAPH.md).

## Critical path

The critical path is:

1. Open a deal room.
2. Confirm the decision question.
3. Read the decision status and reason.
4. Open the few files that can resolve the question.
5. Record Advance, Pause, or Stop with the next action.
6. Ask a follow up question or share the room.

The interface must not send the user through benchmark, pricing, runtime, or
governance pages during this path.

## Application frame

### Room rail

The rail shows only the current room and an Open folder action. Other rooms do
not help with the active decision, so they do not appear here.

### Room header

The header shows the deal name, a short deal scope, file count, file origin,
Copy link, and Room details. Model and runtime state stay inside Room details.

### Main navigation

The main navigation contains:

* Overview
* Sources
* Activity

Decision notes and Technical details are available from Room details. The main
navigation contains no benchmark or pricing work.

## Overview

Before a review exists, the page asks, "What should the team decide?" It has
one Review deal room button. The input describes the decision and the facts
that would change it.

After a review, the page follows the decision order:

1. Decision status
2. Why the review is paused
3. Decision question
4. Review next
5. Team decision

Review next groups repeated citations into one action per priority file. Each
action opens the exact cited passage. Raw excerpts do not appear on Overview.

## Sources

Sources lists the deal room files. Each item shows its file name, type, and
size. Selecting a cited file opens the passage used in the review.

## Activity

Activity holds team questions and notes at the canonical room URL. The user can
ask Bonsai as an explicit choice. Transport and trace identifiers stay out of
the message body.

## Secondary views

Decision notes preserve the team's saved record. Technical details support
troubleshooting. Both open from Room details because neither should compete
with the current deal decision.

## Content rules

Use deal, room, file, source, question, review, decision, and note. Keep
provider, relay, trace, parser, benchmark, and network language outside the
primary path. Remove a phrase if its absence would not change the next action
or confidence in that action.

## Acceptance checks

The demo passes when:

1. A first time user can name the next action from the initial screen.
2. The initial screen has one primary button.
3. The status, reason, question, priority files, and team action appear in that order.
4. The user can reach a cited passage in one action.
5. The main navigation contains no benchmark or pricing work.
6. Strategy and runtime state stay behind Room details.
7. The page works at 390, 768, and 1440 pixel widths.
8. Keyboard focus follows the visible task order.
9. The browser reports no console, request, or HTTP errors during the critical path.
