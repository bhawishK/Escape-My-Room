# Escape My Room

A shared spatial interaction prototype for the IEEE VR 3DUI Contest. A mobile master participates from a recognizable reconstructed room while a remote VR solver explores and interacts with its virtual content.

The chosen stack is **WebXR browser clients and Python services**. The starting interaction candidate uses selection, hold, phone translation, and release to manipulate virtual objects. The technique will develop through connected-device testing; the escape-room scenario provides its application context.

## Project documents

- [Prototype specification](<Escape My Room Prototype Spec.md>) — agreed scope, interaction candidate, open implementation decisions, and testing boundary.
- [Approved ticket breakdown](<Escape My Room Ticket Breakdown.md>) — milestones and dependencies for the 17 implementation tickets.
- [Related research](<Escape My Room Related Research.md>) — primary-source findings and limits of the related-work review.
- [Original proposal](<Escape My Room.docx>) — source proposal; later decisions in the specification and approved tickets take precedence.

## Implementation tickets

The [17 published local tickets](.scratch/escape-my-room/issues/) are the implementation tracker. Each has a technical approach, acceptance criteria, scope boundary, and blocking dependencies. Their initial status is `ready-for-agent`; a ticket can start only when its blockers are complete.

Start with [Ticket 01: Connect mobile and VR through Python with a tracked pose](.scratch/escape-my-room/issues/01-connected-webxr-pose.md). Once it is complete, room loading (02) and voice communication (13) become available.

## Current state

This repository contains the planning documents and approved implementation tickets. Application code has not been implemented. Supporting library choices are proposed defaults in the tickets; target-device support and the exact interaction behavior still require implementation and testing.
