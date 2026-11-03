# GPT Image 2.5 prompt guidance

GPT Image 2.5 responds well to a precise brief and needs less scaffolding than GPT Image 2. Write
a tighter prompt and reserve detail for what the design actually depends on.

- Lead with the deliverable, ratio, and layout zones; then the resolved scene.
- Keep one coherent sentence flow. Avoid checklist-style fragments and repeated emphasis.
- For dense text, UI panels, diagrams, or multi-panel boards, list every required string and its
  zone explicitly, and say that characters must stay correct and unwarped.
- For photographs and product scenes, state light direction, contact, and material; leave retouch
  limits as one short clause rather than a long list.
- Reference-image edits: name the base image, the single requested change, and the invariants that
  must remain identical. Do not restate the unchanged content in detail.
- Do not carry over GPT Image 2 habits that add bulk: no duplicated subject description, no
  generic quality adjectives, no long exclusion list.
- Quality and size are set by the caller, never inside `prompt`. A "4K" word in the prompt does not
  set dimensions.

The two 2.5 variants take the same prompt shape: Flare favours speed and general generation,
Sunburst favours control in reference edits. Do not write variant-specific prompt syntax.
