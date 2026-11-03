---
name: design-direction
description: Classify the deliverable, then form a bounded portfolio of design directions from a frozen brief before any direction is implemented.
---

# Design Direction

Act as the strategic stage of the design process. Classify what is being made, use the supplied
design objective and the category guide for that deliverable, and form a bounded portfolio of
meaningful directions. A direction defines how the design problem will be approached; it is not yet
a complete description of the finished image.

## Classify before proposing

Name the deliverable category before choosing any visual language:

- Read the supplied category index and choose the one category that matches the deliverable.
- Read only that category slice, plus a second one only for a genuine hybrid.
- Let the category decide what this artifact must get right — reading distance, information
  structure, copy behavior, physical plausibility, viewing context.
- Return the chosen ID in `asset_category`. When the brief already carries a category, keep it.

Category is not style. Two directions may share a category and look nothing alike. The category
sets the requirements; the direction decides how to meet them.

## Make the design objective visible

- For a rhetoric-led objective, let communication strategy govern sign relations, likely
  readings, ambiguity control, hierarchy, and the visual means that make the intended rhetoric
  work.
- For an art-led objective, let the intended perceptual experience govern form, color, rhythm,
  texture, imagery, atmosphere, and material treatment.

The supplied style space is a set of dimensions to decide in, not a menu to pick from. Work through
it to reach materially different languages instead of defaulting to one familiar look. Style is
chosen to serve the category requirements and the objective, never the reverse.

## Style is a set of observable decisions

A visual language is defined by what it does to the image, not by the name attached to it. For each
direction:

- resolve the dimensions the work depends on, and state each as the decision that produces it — a
  contour behavior, a value structure, a palette limit, a distribution of detail, a reading order.
  A quality word is not a decision: it names the effect instead of producing it.
- choose one primary language that sets the medium, contour, and value logic, plus at most two
  supporting techniques that add color, texture, or post-treatment without competing for control.
- resolve contradictions between dimensions by removing the weaker statement, rather than keeping
  both and letting the renderer average them.
- no movement, style, or catalog label may stand in for these decisions. A historical name is
  allowed only when the decisions already denote it, and then only as their summary.

A complete direction can describe a contemporary, vernacular, or medium-led voice without any
historical reference. Name the two or three decisions that make the language recognizable; that
naming is the direction.

When the brief explicitly requires a style, treat that style as a shared invariant and vary the
remaining decisions.

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

Directions in one portfolio must be materially different, not differently worded: any two should
differ on at least two of the visual-language dimensions, and at least one of those differences must
be visible in the silhouette, structure, or value arrangement — not only in surface texture or
palette temperature.

## Direction contract

For every direction:

- return the same `asset_category` for the whole portfolio;
- state a concise `design_thesis` that identifies its governing idea;
- explain in `objective_strategy` how its choices embody the design objective for this category;
- record only consequential macro decisions in `direction_decisions`;
- put unresolved choices that do not define the direction in `implementation_freedom`;
- add optional `style_anchors` as short descriptive phrases naming the observable decisions, not a
  list of labels;
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
