---
name: design-intake
description: Convert an informal design request into the exact structured brief required by the active Corpus Atelier design profile.
---

# Design Intake

Transform the user's everyday description of a situation, need, or desired effect into a
complete design brief that conforms exactly to the supplied schema. Interpret the request as a
whole rather than mechanically assigning phrases to fields. The brief should make the design
problem actionable without prematurely designing its solution.

## Interpretation standard

- Identify the actual deliverable, communication purpose, audience, and viewing or use context.
- Preserve explicit requirements and prohibitions without weakening or embellishing them.
- Distinguish user requirements from creative latitude. Treat unspecified visual choices as
  delegated when the user expresses uncertainty, asks for development, or simply leaves them
  open.
- Complete every required field. Infer only what is needed to state a coherent design problem;
  use neutral, conservative wording for ordinary gaps rather than inventing a preference,
  placeholder, alternative, or unresolved question.
- Express relevant social, physical, technical, and tonal boundaries through the fields provided
  by the active schema. Do not invent new fields.
- Prefer a coherent, actionable brief over a literal transcription of the request.

## Visible copy

Treat `exact_copy` as the exhaustive wording approved for the finished image.

- Preserve user-supplied wording exactly, including its language and punctuation.
- If the user explicitly requests no readable text, return an empty array.
- If the user has not supplied wording but has delegated creative development and readable text
  materially helps the communication task, write concise, context-appropriate copy and place it
  in `exact_copy`.
- Do not include explanatory notes, alternatives, placeholders, or quotation marks that are not
  intended to appear in the image.

## Boundaries

- Output only the object required by the supplied schema, with no additional fields.
- Do not write an image-model prompt, image specification, design proposal, or rationale.
- Do not choose a composition, palette, style, or image-making method unless the user has made it
  a requirement or preference.
- Describe the intended design outcome without text-model or image-model instructions.
