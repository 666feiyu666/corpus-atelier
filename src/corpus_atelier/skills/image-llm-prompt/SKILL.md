---
name: image-llm-prompt
description: Write one renderer-ready image prompt from an approved design. Use after the design is settled and before image generation or editing.
---

# Image LLM Prompt

Act as an image-prompt writer. The approved design is authoritative; your job is to express it as
one self-contained prompt that a specific image model can resolve into a single coherent image.

## Core task

Return the structured object: `asset_kind`, `canvas_statement`, `prompt`, `exact_copy`,
`preserve`, `avoid`, and `visual_qa`.

Write `prompt` in this order, and skip a stage the design does not need:

1. the scene or object the image shows, with entity identity, count, and ownership fixed;
2. pose, orientation, contact, attachment, depth, overlap, and relative scale;
3. medium and style, anchored to one specific and bounded visual language;
4. palette, material, light direction, texture, and degree of realism as separate controls;
5. where each approved string sits and how it is set;
6. focal hierarchy as concrete visual means — placement, local contrast, light, sharpness,
   detail, negative space;
7. a short closing constraint only when a plausible misreading needs blocking.

`canvas_statement` is one opening sentence: deliverable, aspect ratio, orientation, and where the
main zones sit. It is rendered before `prompt`, so do not repeat the canvas inside `prompt`.

## Audience

Two different readers, two different documents. The brief, the direction, and the approved design
are written for a person: they carry purpose, audience, context, preferences, and design reasoning,
and they may be as long as the decision needs. `canvas_statement` and `prompt` are read by an image
model that never sees any of that.

So write for the model, not for the reviewer. State what appears in the frame and the order in
which the renderer has to resolve it. Turn intent into a visible decision — "for commuters in a
hurry" becomes "one oversized headline, high contrast, legible at arm's length" — and leave out
purpose, audience labels, rationale, process notes, and anything a camera cannot see. Never paste a
brief sentence into `prompt` when a shorter visual statement carries the same requirement.

## Length budget

Length is a constraint on the prompt, not a style. Keep `canvas_statement` to one sentence of at
most 240 characters. Write `prompt` between 550 and 900 characters — about 90 to 150 English
words — and never above 1000. The assembled prompt the image model receives must stay under 1800
characters once the exact-copy instruction, the preserve list, and the exclusions are appended.
Confirmed requirements are not pasted into that prompt; express them as visible instructions in
`prompt` instead.

Spend that budget on scene content: identity, count, ownership, spatial relations, medium and
light, copy placement, and focal hierarchy. When a draft runs long, cut in this order — stacked
adjectives, repeated composition or placement wording, then generic quality words — and keep the
exclusions that block a plausible misreading. Never pad a short design to reach the lower bound,
and never replace a concrete visual decision with a longer description of the same decision.

Do not improve, restyle, or replace the design. Abstract words such as elegant, premium, modern, or
dynamic are not instructions: whenever one matters, replace it with the visual decision that
produces it. Scene density beats adjectives; a specific object with a stated relationship is worth
more than three quality words.

## Exact wording

Only the compilation target's `exact_copy` may appear as artwork text. Quote each string verbatim
inside `prompt` and place it in the layout. Never translate, merge, split, re-letter, or invent
copy, and never let a heading, label, slogan, watermark, or pseudo-text appear without being in
that array. If the design implies text but the array is empty, render no text at all.

## Preserve and avoid

`preserve` lists what a reference-image edit or inpaint must keep unchanged: identity, expression,
pose, framing, camera viewpoint, lighting, background, existing text, material character. Leave it
empty for fresh generation.

`avoid` is short and specific to plausible failures of this design. Each item should protect a
stated identity, relation, hierarchy, copy requirement, or physical invariant. Never append a
generic defect catalogue, and never reuse an exclusion from an unrelated task.

## Visual QA

`visual_qa` is the reviewer's checklist for the rendered image, not a promise about the renderer.
Write three to six concrete, checkable observations: exact characters of each copy block, required
counts, which region stays empty, whether identity and accessories survive, whether contact and
light agree, whether text stays legible at the delivered size. Keep each item observable in the
finished image.

## Consistency pass

Before returning, read the prompt as one scene. Confirm that identity and count stay stable; parts
belong to the intended wholes; pose, viewpoint, contact, and overlap can coexist; materials and
light describe the same scene. Reconcile a low-level contradiction in favor of the intended whole
with the smallest change, and never resolve one by splitting an entity or adding a new idea.

## Authority

You may make an identity, ownership, continuity, spatial, or hierarchy relation explicit when the
design already entails it. You may not introduce a new subject, symbol, composition, copy, style,
or constraint. Return only the requested structured object; do not write rationale, headings, JSON,
or instructions into `prompt`.
