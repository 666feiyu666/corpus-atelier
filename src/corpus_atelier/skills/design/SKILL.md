---
name: design
description: Form a complete, provider-independent visual design from a brief and optional corpus reference. Use for the design stage before any image-model prompt is written.
---

# Design

Act as the designer of the complete image. Resolve what the finished design looks like before
another skill translates it for an image model.

## Completion standard

The `design_description` is the primary deliverable. Write it so that a reader can form a
coherent mental image of the finished work without seeing a rendering. Resolve the decisions
that carry the concept, protect the requirements, or keep the image physically and perceptually
coherent. Do not mechanically fill every possible category or invent details merely to make the
description longer.

As relevant to the work, make clear:

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

Before finishing, perform a physical and viewpoint consistency pass. Check that entity identity
and count remain stable; parts belong to the intended wholes; depth, overlap, contact, attachment,
pose, and orientation can coexist; the stated viewpoint agrees with the surfaces that are visible;
and material and lighting statements describe one scene. Revise contradictory details instead of
expecting the renderer to choose which instruction to ignore.

Preserve controlled freedom where the concept does not depend on a choice. Do not fix an arbitrary
side, count, coordinate, camera setting, material, or decorative feature solely because it could be
specified. A complete design resolves what matters and identifies meaningful latitude; it does not
turn every optional detail into a requirement.

## Supplied profile policies

The runtime prompt already supplies the active profile's complete objective and deliverable
policies in explicitly labeled sections. Treat those supplied sections as authoritative and
sufficient. Do not request repository paths, files under `references/objectives/` or
`references/deliverables/`, or any other internal skill resources.

Use `needs_sources` only when the user's requirements explicitly depend on work-specific external
material that is absent from both the prompt and the supplied visual references. A requested
artistic style, genre, medium, or general body of cultural knowledge is not by itself a missing
source.

## Boundaries

- Design the image; do not write an image-model prompt or `image_spec`.
- Do not optimize wording for GPT Image or any other renderer.
- Preserve required subjects, exact visible copy, constraints, and the user's chosen purpose.
- Treat `exact_copy` as the exhaustive list of readable wording. Do not add headings, labels,
  captions, signs, symbols made from letters, or other visible wording that is absent from that
  list. If a constraint requires readable wording that `exact_copy` does not supply, return
  `needs_clarification` and identify the missing copy instead of inventing it.
- Reference material provides visual knowledge, not additional user requirements.
- Distinguish transferable design knowledge from work-specific content that should not be copied.
- Keep the rationale concise and human-reviewable. Put visible decisions in
  `design_description`, not only in the rationale.
- Mark the proposal ready only when no blocking source or clarification issue remains.
