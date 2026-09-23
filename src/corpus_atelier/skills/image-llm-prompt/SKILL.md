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

Use targeted negative constraints only for plausible misreadings of this design. Do not append a
generic catalog of defects. Prefer a positive, unambiguous scene description, supported by a few
specific exclusions where necessary.

Before returning the specification, run a consistency pass across subject identity, anatomy,
viewpoint, depth, attachment, lighting, and materials. Do not mechanically preserve two details
that cannot be true in the same image. When the intended whole is unambiguous, reconcile a
low-level contradiction in favor of that whole while changing as little as possible. Never solve
a contradiction by splitting one entity into multiple subjects or by adding a new visual idea.

## Authority

You may clarify what the design already entails. For example, if one woman wears one watch, you
may state that the visible wrist belongs to that same woman and exclude a detached display hand.
You may not add a second subject, new symbol, different composition, new copy, or alternate style.

Return only the requested structured object. The result must stand on its own for the renderer;
do not rely on the design rationale or private reasoning.

Before compiling, apply the failure patterns in
[references/semantic-disambiguation.md](references/semantic-disambiguation.md). Apply the target
model guidance in the relevant provider reference. When preparing the final renderer request,
apply [references/generation-boundaries.md](references/generation-boundaries.md).
