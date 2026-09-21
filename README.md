# Corpus Atelier

Corpus Atelier is a downstream research workspace for turning domain knowledge—such as design, rhetoric, and semiotics—and structured visual corpora (see [Visual-Rhetoric-Atlas](https://github.com/666feiyu666/visual-rhetoric-atlas)) into reproducible graphic-design experiments that support graphic design and image generation.

The project focuses on one knowledge-transformation process:

1. How can domain knowledge and corpus knowledge be transformed into a structured image-generation prompt?
2. What does this structured prompt produce, and how can we understand the relationship between the input knowledge and the generated image?
3. Based on this understanding, how can we reframe the structured prompt?

My broader, long-term goal is to build an agentic tool that can help us make “better” graphic designs. Corpus Atelier is one research phase toward that goal. Before assembling such a tool, we first need to understand and test its core components separately.

Basically, this project does not currently include:

- RAG: The current question is how selected corpus knowledge contributes to a design, rather than how that knowledge should be retrieved dynamically. Hopefully, these experiments will also help us understand how to mine and organize the corresponding corpus in the future. That being said, for a mature agentic tool, RAG is surely be included.
- Multi-Round Agent: The current goal is to understand how knowledge is transformed into a prompt and how the image model responds to that prompt. Multi-round iteration may produce higher-quality designs, but it belongs to a later phase.
- Multi-Agent Design: This phase does not divide the process among multiple specialized agents. Before introducing agent roles and coordination, we first need to understand the individual components and the relationships between them.