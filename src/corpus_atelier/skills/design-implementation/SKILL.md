---
name: design-implementation
description: Implement one approved design direction as a complete provider-independent visual design before any image-model prompt is written.
---

# Design Implementation

Act as the implementation stage of the design process. Turn one approved direction into a
complete, provider-independent description of the finished image.

The approved direction is authoritative. Preserve its design thesis, objective strategy, and
direction decisions. Resolve only the choices delegated through `implementation_freedom`; do not
replace the direction, select a different style, or reopen portfolio planning.

## Completion standard

The `design_description` is the primary deliverable. Write it so that a reader can form a coherent
mental image of the finished work without seeing a rendering. Resolve the decisions that carry the
concept, protect the requirements, or keep the image physically and perceptually coherent. Do not
mechanically fill every possible category or invent details merely to make the description longer.

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

Preserve controlled freedom where the design does not depend on a choice. Do not fix an arbitrary
side, count, coordinate, camera setting, material, or decorative feature solely because it could be
specified. A complete design resolves what matters and identifies meaningful latitude; it does not
turn every optional detail into a requirement.

Where the approved direction intentionally leaves implementation freedom, make restrained choices
that strengthen its governing idea, perceptual unity, and practical legibility. The completed
proposal should present one resolved design rather than alternatives, questions, placeholders, or
requests for further material.

## Boundaries

- Implement the approved direction; do not plan alternative directions.
- Do not write an image-model prompt or `image_spec`.
- Do not optimize wording for GPT Image or any other renderer.
- Preserve required subjects, exact visible copy, constraints, and the user's chosen purpose.
- Treat `exact_copy` as the exhaustive list of readable wording. Do not add headings, labels,
  captions, signs, symbols made from letters, or other visible wording absent from that list.
- Keep the rationale concise and human-reviewable. Put visible decisions in
  `design_description`, not only in the rationale.
- Output only the object required by the supplied schema.
