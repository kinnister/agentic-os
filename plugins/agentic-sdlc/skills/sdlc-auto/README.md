# sdlc-auto

Kicks off a hands-off agentic-sdlc run: the pipeline clears its own judgment gates and only stops you for a genuine risk flag.

## Use It For

- Carrying a ticket from intake to a branch-ready diff without step-by-step check-ins.
- "Factory mode" runs on features that are small, well-understood, and low-risk.
- Driving the whole development cycle — requirements, planning, implementation, QA — end to end.
- Spinning up a greenfield proof of concept where the pipeline owns every phase itself.

## How To Ask

- "Take this and run with it, don't stop to check with me."
- "Factory mode on TICKET-789."
- "Just ship it, don't ask me anything."
- Call the skill directly with a greenfield idea: `sdlc-auto --greenfield "internal changelog generator"`.

## What It Needs

- `.agentic/guides/project.md`, `.agentic/guides/git-workflow.md`, and `.agentic/guides/quality-gates.md` — run `repo-guides` first if these aren't there yet.
- superpowers plugin >= 6.1.0.
- A clean working tree, either already on a feature branch or on a base branch the run can branch from.
