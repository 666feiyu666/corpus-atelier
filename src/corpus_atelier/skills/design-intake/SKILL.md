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
- Use `user_requirements` for explicit mandatory requirements. When a confirmed contract is
  supplied, copy that list exactly; never add, remove, translate, or paraphrase its entries.
  Otherwise, extract only explicit mandatory requirements from the request, or use an empty list.
- Distinguish user requirements from creative latitude. Treat unspecified visual choices as
  delegated when the user expresses uncertainty, asks for development, or simply leaves them
  open.
- Complete every required field. Infer only what is needed to state a coherent design problem;
  use neutral, conservative wording for ordinary gaps rather than inventing a preference,
  placeholder, alternative, or unresolved question.
- Express relevant social, physical, technical, and tonal boundaries through the fields provided
  by the active schema. Do not invent new fields.
- Prefer a coherent, actionable brief over a literal transcription of the request.

## Audience and length

The brief is read by the person who asked for the design and by the design stages, never by the
image model. Write it for that person: complete sentences, stated context, and the nuance that
makes the decision reviewable. There is no length budget here — a brief that needs a paragraph to
explain the occasion, the audience, or a prohibition should have it, and it stays that way in the
saved record.

Length here does not buy length later: the image-prompt stage turns this brief into a short,
model-facing instruction, and it does that by translating intent into visible decisions. So write
the requirement clearly rather than compressing it into a phrase, and never write that later prompt
inside a brief field.

## Deliverable category

When the schema provides `asset_category`, classify the deliverable into exactly one supplied
category ID and return it.

- Classify by what is being made and how it will be seen, not by the visual style the user likes.
- A poster, an article cover, an invitation, a product packshot, an infographic, a UI mockup, and a
  photograph are different artifacts with different requirements even at the same canvas size.
- Prefer the category the user's own words imply. Ask for nothing extra merely to classify.
- If two categories genuinely apply, choose the one that governs the reading context and leave the
  secondary aspect to the design stage.
- Never invent a category ID outside the supplied list.

## Visible copy

Treat `exact_copy` as the exhaustive wording approved for the finished image.

- Preserve user-supplied wording exactly, including its language and punctuation.
- If the user explicitly requests no readable text, return an empty array.
- If the user has not supplied wording but has delegated creative development and readable text
  materially helps the communication task, write concise, context-appropriate copy and place it
  in `exact_copy`.
- Do not include explanatory notes, alternatives, placeholders, or quotation marks that are not
  intended to appear in the image.

## Generation route

Set `execution_route` only when the schema provides it, and explain the choice in `route_reason`.

- `direct`: the request itself already fixes the deliverable, subject, visual language or style,
  the wording to render, and the canvas, so a designer could render it without exploring
  alternatives. A concise, decided request takes this route.
- `staged`: at least one consequential choice is still open — the concept, composition, visual
  language, or hierarchy has to be developed and reviewed before rendering.

Do not invent missing details to justify `direct`, and do not choose `staged` merely because the
request is short. When the request leaves a real design decision open, prefer `staged`.

## Boundaries

- Output only the object required by the supplied schema, with no additional fields.
- Do not write an image-model prompt, image specification, design proposal, or rationale.
- Do not choose a composition, palette, style, or image-making method unless the user has made it
  a requirement or preference.
- Describe the intended design outcome without text-model or image-model instructions.
