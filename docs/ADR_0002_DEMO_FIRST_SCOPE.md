# ADR 0002: Customer demo scope

Status: accepted for the current goal  
Date: August 17, 2026  

## Decision

The current goal is a customer demo that makes one deal room workflow easy to
understand and easy to show. Accuracy certification and commercial proof are
outside the current goal.

The project will keep the existing benchmark and pricing records as historical
work. They will not appear in the main navigation, control demo completion, or
compete with the deal workflow on the page.

The demo is complete when a new person can:

1. Open a deal room.
2. State the decision they need to make.
3. Read the decision status and reason.
4. Check the priority files that can resolve the question.
5. Record Advance, Pause, or Stop with the next action.
6. Discuss the decision with the team.
7. Copy a stable room link.

## Reason

The previous product plan gave equal weight to product use, model evaluation,
benchmark governance, pricing evidence, runtime proof, and security proof. A
customer had to understand the system before using it.

The demo needs one visible task. Source and system details remain available,
but they appear only when a person asks for them.

## Product claim

The demo claim is narrow:

> Point Prism at a deal room, ask a deal question, and review a source linked
> brief with your team while Bonsai runs on the local machine.

The demo does not claim certified accuracy, willingness to pay, production
security, an air gap, or general document fidelity.

## Consequences

The main room navigation contains Overview, Sources, Activity, and Evaluation.
Decision notes and Technical details remain secondary views inside Room
details. Evaluation stays in the room because reviewers judge the same signed
conversation that the team reads in Activity.

The product header shows the room name, short scope, file count, file origin,
and link actions. The local model appears inside Room details.

The overview gives one action priority. The user states the decision and runs
the analysis. The brief then becomes the main content.

The source panel opens beside the brief when a user selects a citation. Long
source excerpts stay collapsed until requested.

The old benchmark and pricing routes remain available by direct URL for
historical inspection. They are not part of the demo.

## shadcn decision

The current browser client uses plain HTML, CSS, and JavaScript. The current
project has no React or Tailwind build system. Adding shadcn now would require a
client migration before it changes the information structure.

The demo will use the component structure associated with shadcn, including a
sidebar, tabs, cards, a source sheet, dialogs, buttons, badges, and disclosure
controls. Prism will implement those parts in its current client so the team
owns the markup and styles.

If Prism later adopts React, the same page structure can move to shadcn without
changing the user flow.

Official references:

* [shadcn manual installation](https://ui.shadcn.com/docs/installation/manual)
* [shadcn tabs](https://ui.shadcn.com/docs/components/base/tabs)
* [shadcn sheet](https://ui.shadcn.com/docs/components/base/sheet)
