---
name: design
description: Form a complete, provider-independent visual design from a brief and optional corpus reference. Use for the design stage before any image-model prompt is written.
---

# Design

Act as the designer of the complete image. Resolve what the finished design looks like before
another skill translates it for an image model.

## Completion standard

The `design_description` is the primary deliverable. Write it so that a reader can form a
coherent mental image of the finished work without seeing a rendering. After reading it, the
reader should be able to picture:

- the canvas and overall arrangement;
- every important subject and supporting element;
- which body parts, objects, words, and ornaments belong to one another;
- pose, orientation, placement, relative scale, depth, overlap, and negative space;
- the focal hierarchy and the path the eye follows;
- the placement and visual character of exact copy;
- the medium, palette, line, material, lighting, texture, and degree of realism;
- how all parts form one image rather than a list of motifs.

Abstract qualities such as elegant, premium, dynamic, or refined do not make a design visible.
Whenever they matter, realize them through concrete visual decisions. Make entity identity and
part-whole relationships explicit when a different reading would produce a different image.

Before finishing, perform a physical and viewpoint consistency pass. Every spatial, anatomical,
material, lighting, and camera statement must be mutually compatible. For example, the named side
of a hand or wrist must agree with the visible nails, palm, watch face, and camera angle; an object
cannot be simultaneously behind and in front of the same element; and contact or attachment must
remain possible in the described pose. Revise contradictory details instead of expecting the
renderer to choose which instruction to ignore.

## Context references

Read the selected objective policy in `references/objectives/` and the selected deliverable
policies in `references/deliverables/`. Apply only the references selected by the active profile;
do not load unrelated objective or deliverable variants.

## Boundaries

- Design the image; do not write an image-model prompt or `image_spec`.
- Do not optimize wording for GPT Image or any other renderer.
- Preserve required subjects, exact visible copy, constraints, and the user's chosen purpose.
- Reference material provides visual knowledge, not additional user requirements.
- Distinguish transferable design knowledge from work-specific content that should not be copied.
- Keep the rationale concise and human-reviewable. Put visible decisions in
  `design_description`, not only in the rationale.
- Mark the proposal ready only when no blocking source or clarification issue remains.
