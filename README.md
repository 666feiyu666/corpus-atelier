# Semiotic Graphic

Exploring how AI-assisted design can generate and refine graphics for different purposes. The project currently contains two experiments: a design and review workflow for communicating abstract ideas, and a reference-guided workflow for creating visually appealing editorial images.

## Experiments

### Pilot 1: Semiotic Graphic

Explores how an AI designer generates, reviews, and revises posters to communicate a macro idea.

The workflow uses two model layers with distinct responsibilities:

- Design model: Interprets the brief and proposes a design, keeping its rationale separate from a structured image specification (image_spec). During revision, the same model examines the generated poster against the original brief and updates the proposal where justified.

- Image model: Renders the poster from a prompt assembled from the reviewed image specification and shared rendering instructions.

Human judgment guides the process. Model interpretations remain hypotheses to explore through audience feedback.

### Pilot 2: Reference-Guided Images

Explores the creation of WeChat article covers and in-article images using a local image corpus. These images are chosen for visual appeal; they do not need to depict or explain the article’s text.

The workflow combines a design request with selected reference images and their descriptive tags. It assembles an image prompt and sends the prompt and references to an image model. The resulting images are reviewed and selected by a human.