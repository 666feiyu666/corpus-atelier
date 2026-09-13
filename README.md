# Semiotic Graphic

Exploring how an AI designer generates, reviews, and revises posters to communicate a macro idea.

## Design

The system uses two model layers with distinct responsibilities:
- Design model: Interprets the brief and proposes a design, keeping its rationale separate from a structured image specification (image_spec). During revision, the same model examines the generated poster against the original brief and updates the proposal where justified.
- Image model: Renders the poster from a prompt assembled from the reviewed image specification and shared rendering instructions.
Human judgment guides the process. Model interpretations remain hypotheses to explore through audience feedback.

## Workflow

1. Define the brief: Specify the purpose, core message, audience, and viewing context.
2. Preview the design request: The application assembles the instructions and brief. Review the input and trigger the design call.
3. Review the proposal: Resolve clarification or source requirements, then inspect and optionally edit image_spec.
4. Preview and generate: The application assembles the image prompt. Review it with the generation settings and authorize generation.
5. Inspect and iterate: Keep the poster or request self-review by the design model. Review the revised proposal before generating again.

## Implementation

to be updated