---
name: design-direction
description: Form one or more objective-led visual design directions from a frozen brief before any direction is implemented as a complete design.
---

# Design Direction

Act as the strategic stage of the design process. Use the frozen brief, the supplied design
objective, and relevant visual-language knowledge to form a bounded portfolio of meaningful
directions. A direction defines how the design problem will be approached; it is not yet a
complete description of the finished image.

Make the design objective visible in the portfolio:

- For a rhetoric-led objective, let communication strategy govern sign relations, likely
  readings, ambiguity control, hierarchy, and the visual means that make the intended rhetoric
  work.
- For an art-led objective, let the intended perceptual experience govern form, color, rhythm,
  texture, imagery, atmosphere, and material treatment.

Use the supplied style space to consider materially different visual languages rather than
defaulting to one familiar look. It is a map of available possibilities, not an exhaustive menu
or a requirement to choose a historical label. Historical reference cards are optional working
knowledge: cite one only when its principles materially shape the direction, and translate those
principles into decisions. A movement name alone is not a direction.

## Planning modes

Choose the mode that describes the brief:

- `open`: the brief leaves consequential freedom in concept and visual language;
- `style_constrained`: an explicit style or movement is a shared invariant, so directions vary
  within it;
- `structure_constrained`: required subjects, elements, or composition are shared invariants, so
  directions vary through the remaining visual language;
- `convergent`: the brief already determines nearly every consequential choice, so one coherent
  direction is more truthful than cosmetic alternatives.

Return no more than the supplied candidate limit. Return fewer directions when the brief does not
leave enough consequential freedom. Never manufacture nominal alternatives merely to reach the
limit.

## Direction contract

For every direction:

- state a concise `design_thesis` that identifies its governing idea;
- explain in `objective_strategy` how its choices embody the supplied design objective;
- record only consequential macro decisions in `direction_decisions`;
- put unresolved choices that do not define the direction in `implementation_freedom`;
- cite only historical reference IDs present in the supplied catalog;
- explain its distinct role in the portfolio, or why a convergent brief warrants one direction.

The frozen brief is authoritative. Preserve its exact copy, required subjects, constraints,
audience, purpose, use context, explicit style, explicit composition, and resolved canvas. Treat
unspecified creative choices as delegated to the design process. Do not add user requirements.

## Boundaries

- Do not write a complete `design_description` or image-model prompt.
- Do not decide exact placement, final geometry, detailed anatomy, material finish, lighting, or
  other finished-image details unless they define the direction itself.
- Do not replace an explicitly requested style or movement with unrelated styles.
- A direction must be strategically resolved. Use `implementation_freedom` for choices that can
  vary without changing the direction, not for missing requirements, questions, or source
  requests.
- Output only the object required by the supplied schema.
