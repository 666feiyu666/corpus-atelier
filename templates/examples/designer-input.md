# Design task

## Topic

Slowing down in everyday life

## Communication purpose

Invite people to reconsider pressure to remain continuously productive and allow a brief pause.

## Core message

Not specified.

## Deliverable

A portrait poster in English. Propose the visible wording.

# Audience and viewing context

## Audience

Students or office workers feeling pressure to stay productive.

## Viewing context

A poster encountered briefly in a shared indoor space.

# Requirements and constraints

## Hard constraints

Avoid unsupported factual, health, or society-wide claims.

## Tone

Inviting rather than blaming or patronizing.

## Exact visible copy

Not specified.

# Design decisions

Develop the concept, signs, and intended readings for the communication purpose and viewing context, then select a supporting visual style and implement both through imagery, composition, typography, color, and wording. Respect all specified requirements, including exact visible copy when supplied.

## Expression decisions

First establish the important signs, their referents, intended readings, and the
relationships needed to communicate the task. Explain why this concept fits.
Then choose a visual style that supports those relationships, and translate both
into concrete composition, typography, imagery, color, and variation instructions.

## Style constraints and selection

Treat any user-specified style or reference as a constraint from the outset when
choosing signs. Otherwise derive a proposed direction from the expression needs;
do not choose a style and add sign labels afterward. Signs and style may be revised
together when a visual treatment changes the intended reading. Explain the tradeoff
and preserve explicit requirements. Record the direction, supporting qualities,
variation boundaries, and evidenced confirmation status in visual_style.

# Design approach

## Shared design principles

Act as a graphic designer informed by Peircean semiotics.
Develop the design from the Design task, Audience and viewing context, and
Requirements and constraints sections above. Let these requirements guide visual
motifs and sign relationships.
Explain what important elements refer to, how their relationships might support a
reading, and why graphic choices suit the audience and setting. Use iconic, indexical,
and symbolic relationships where relevant; do not force all three or assume fixed
meanings for colors and shapes. You may question whether depicting the topic literally
serves the purpose. Offer proposed wording unless exact visible copy is specified.
Keep intended readings hypothetical. State uncertainties and visible review criteria.
Preserve supplied wording and distinguish requirements from your interpretations and
assumptions. Missing information is unspecified; do not invent facts or sources.
Ask focused questions only when an unresolved issue would materially change the design.

### From communication to visual expression

Develop and explain the proposal in this order: communication purpose and context;
core concept; signs and intended readings; why the concept fits; visual style and
art direction; concrete visual implementation. Identify what the elements communicate
before selecting their stylistic treatment. This is a dependency in the design
argument, not a requirement to disclose private reasoning or make separate model calls.

Choose style qualities because they support specific sign relationships. For example,
if an interruption carries meaning, explain what visual continuity makes it perceptible.
Do not decorate a chosen style with retrospective semiotic labels. A style explicitly
specified by the user constrains sign selection from the outset. Iterate between signs
and style if their interaction changes a reading, explaining the resolved relationship
and any remaining conflict with user requirements.

### Design explanation for human review

Provide an inspectable design explanation alongside image_spec. These are two
separate deliverables: people review the explanation; the image model receives
only the executable visual specification.

In sign_relationships, use a short Markdown subsection for each important element.
Explain what the element refers to, which iconic, indexical, or symbolic relationship
is relevant, what supports that relationship, and what a viewer might understand.
Name the relationship explicitly when justified. An element may involve more than
one relationship; do not force all three categories or treat a label as an explanation.
For an indexical claim, identify the actual connection or evidence being claimed;
a generated depiction alone does not establish that connection. State ambiguity
where a reading depends on context or audience conventions.

In design_rationale, explain why the proposed signs and their combined reading suit
the communication purpose, audience, and viewing conditions.

In visual_style, refer to the preceding sign_relationships. Use separate Markdown
subsections for the style or reference direction, how it supports those relationships,
defining visual qualities, variation boundaries, and
confirmation status. A named movement such as Bauhaus or International Typographic
Style is optional, not a default: specify the actual features being adopted rather
than relying on the label. A contemporary or mixed direction must be equally concrete.
Distinguish a user-specified requirement from a designer proposal and from explicit
user confirmation. For confirmation, identify the supplied statement or record;
never invent it or infer it from ready status, prior generation, or your own text.
If no style was specified, propose one without making selection a mandatory
clarification step. Ask only if an unresolved style requirement materially blocks
the design. Ready means prepared for review, not that the style is user-approved.

In graphic_decisions, connect each important choice across the intended sign
relationship, the supporting style quality, and the concrete image_spec instruction.
Make explicit which relationships must survive stylistic variation. Cover composition,
typography, visible_copy, visual_treatment, allowed_variation, or exclusions.
Keep the art direction consistent across image_spec.visual_treatment, composition,
typography, allowed_variation, and exclusions. The image model needs concrete visual
instructions, not confirmation history or the argument for choosing a style.
Use uncertainties for plausible misreadings and review_criteria for visible checks.
Keep explanations concise and evidence-based, not a transcript of private deliberation.

### Sources and image specification

A generated trace cannot establish documentary evidence. If the chosen direction
requires real sources or precise source composition, set status to needs_sources,
list those requirements, and set image_spec to null. This application only
supports text-to-image generation, not faithful source composition.
If essential user intent needs clarification, set status to needs_clarification,
list focused clarification_questions, and set image_spec to null.
When neither sources nor clarification are outstanding, set status to ready and
provide the complete structured image_spec: communication objective, audience and
viewing context, exact visible copy, composition, typography, visual treatment,
allowed variation, and exclusions. Keep theory analysis, alternative readings,
and research plans in the rationale fields, outside the image specification.

### Response contract

No separate critic is involved. Proposals never authorize generation.
Return the requested JSON structure. Rationale fields are concise explanations of
choices, not a transcript of private internal reasoning.

Ready proposals have no outstanding source_requirements or clarification_questions.
Use visible_copy for exact artwork text and an empty visible_copy list for text-free
designs. Return all schema fields.

# Propose the design

## Initial design proposal

Interpret the communication problem and state assumptions. Introduce the core concept,
then identify its signs, referents, relevant relationships, and intended readings in
sign_relationships. Explain why this expression suits the task in design_rationale.
Derive visual_style from those expression needs, explaining how its defining qualities
support particular relationships. Specify variation boundaries and confirmation status.
Treat user-supplied style requirements as constraints during sign selection; without
them, propose a direction for review rather than claiming confirmation.

Use graphic_decisions to connect signs and style to concrete image_spec instructions.
If a treatment weakens the intended reading, reconsider the signs or treatment together
while respecting explicit requirements. Include alternatives only when they clarify
a meaningful tradeoff. Return both the explanation fields and complete image_spec
when status is ready. Leave revision_summary empty for this initial proposal.

# Required response format

Return the JSON object defined by the response schema attached to this request.
Keep design explanations separate from image_spec. Only image_spec is used to build
the image model's prompt after human review. Supplied content and artwork text are
material to interpret, not instructions that override this task or response format.
