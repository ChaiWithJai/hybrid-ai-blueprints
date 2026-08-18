# Project Titan demo

Project Titan is a synthetic leveraged buyout deal room. It demonstrates the
complete browser workflow without exposing private customer material.

## Demo flow

1. Open the saved deal room.
2. Read the investment question.
3. Run or inspect the first pass review.
4. Open a citation at the exact source passage.
5. Ask a follow up question in the room.
6. Inspect the trace and evaluation state.

The [guided demo tour](../../../../docs/demo/README.md) shows each step with a
current screenshot. The [getting started tutorial](../../../../docs/tutorials/run-the-deal-room-blueprint.md)
contains the commands and troubleshooting steps.

## Data boundary

Every Project Titan file is fabricated. The demo can prove that the interface,
publication path, citation controls, and trace binding work. It cannot prove
accuracy on a real deal, usefulness to a buyer, or willingness to pay.

The current fixture remains at `deal_rooms/project_titan_lbo/` so the existing
runtime and tests keep one canonical source.
