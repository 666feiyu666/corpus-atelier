# Edit and inpaint invariants

When the target operation is `reference_generation` or `mask_edit`, the prompt describes a change
to an existing image. Write it so a renderer cannot "improve" the untouched parts.

- Name the base image relation in one clause, then the single requested change.
- State the region or object that changes precisely: position, extent, and what replaces it.
- Then enumerate the invariants that must survive: subject identity and expression, pose,
  framing, camera viewpoint, lighting direction, background, existing text, and material
  character.
- Put those invariants in `preserve` as short clauses, and repeat the load-bearing ones in
  `prompt`. `preserve` is rendered after the prompt; it does not replace the in-prompt statement.
- Do not describe the unchanged content in full. A long restatement invites the model to redraw it.
- Do not add, remove, crop, restyle, or "clean up" anything outside the requested change.
- For mask inpainting, the mask defines what may change. Describe the replacement content, and say
  that pixels outside the mask keep their existing appearance.
- `exact_copy` still applies: if existing text is preserved, it is not new copy and stays out of
  the array; if new text is introduced, it must be approved copy.
- A prompt-level constraint is not a pixel-level lock. Phrase it as an intended appearance, and
  put the comparison steps in `visual_qa`.
