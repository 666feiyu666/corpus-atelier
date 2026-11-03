# Renderer output contract

The image model receives only the assembled prompt. It never sees this brief, the JSON object, the
design rationale, the brief's purpose or audience, or the QA list.

Therefore:

- `prompt` must stand alone. No field names, headings, bullet labels, or JSON fragments.
- No instructions addressed to a reader: no "the design should", "the client wants", "use this
  space for a logo later". State what is visible in the finished image.
- Never mention `exact_copy`, `preserve`, `avoid`, or any other schema term.
- Reserve empty space by describing the empty region, not by explaining why it is empty.
- A rendering instruction that cannot be seen in the final pixels does not belong in `prompt`;
  put the corresponding check in `visual_qa` instead.
- Do not promise pixel-level fidelity, exact fonts, or guaranteed spelling. Describe the intended
  appearance and let the reviewer verify the result.
