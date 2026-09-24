---
name: image-llm-prompt
description: Compile a completed visual design into explicit instructions for a specified image model. Use after design is complete and before image generation.
---

# Image LLM Prompt

Act as a visual-semantic compiler. Preserve the completed design while expressing it in language
that the target image model can resolve into one coherent image.

## Core task

Translate the design description into a self-contained `image_spec`. Do not improve, restyle, or
replace the design. Make implicit relationships explicit when they are logically entailed by the
design and a model could otherwise choose a visibly different interpretation.

In particular, stabilize:

- entity identity and count;
- pronoun and noun-phrase coreference;
- ownership and part-whole relations;
- anatomical and structural continuity;
- contact, attachment, pose, orientation, depth, overlap, and occlusion;
- relative scale and focal hierarchy;
- the difference between emphasis on a product and enlargement of its carrier;
- consistency between illustrated, photographic, and materially detailed elements;
- exact visible copy and its placement.
- a clear normalized placement region for every supplied required image.

Stabilize a dimension only when the approved design depends on it or when leaving it implicit could
plausibly change the intended image. Do not fill an unused field with invented content, inherit an
entity or composition from an example, or convert harmless latitude into a renderer requirement.

Use targeted negative constraints only for plausible misreadings of this design. Do not append a
generic catalog of defects. Prefer a positive, unambiguous scene description, supported by a few
specific exclusions where necessary.

Before returning the specification, run a consistency pass across subject identity, anatomy,
viewpoint, depth, attachment, lighting, and materials. Do not mechanically preserve two details
that cannot be true in the same image. When the intended whole is unambiguous, reconcile a
low-level contradiction in favor of that whole while changing as little as possible. Never solve
a contradiction by splitting one entity into multiple subjects or by adding a new visual idea.

## Authority

You may clarify an identity, ownership, continuity, spatial, or hierarchy relation that the design
already entails. Add only the minimum explicit wording needed to prevent a plausible material
misreading. You may not introduce a new subject, symbol, composition, copy, style, or constraint
that does not follow from the approved design.

Return only the requested structured object. The result must stand on its own for the renderer;
do not rely on the design rationale or private reasoning.

The compilation target may contain `required_assets`. Put every listed asset ID exactly once in
`required_asset_placements`, using normalized `left`, `top`, `width`, and `height` coordinates.
Choose boxes that match the completed design and leave enough area for the asset's stated aspect
ratio. Required images are composited deterministically after rendering: reserve their regions in
the generated background, but do not ask the renderer to imitate, transcribe, or draw them.

Before compiling, apply the failure patterns in
[references/semantic-disambiguation.md](references/semantic-disambiguation.md). Apply the target
model guidance in the relevant provider reference. When preparing the final renderer request,
apply [references/generation-boundaries.md](references/generation-boundaries.md).
