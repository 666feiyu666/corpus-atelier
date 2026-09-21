# Corpus Atelier

Corpus Atelier is a downstream research workspace for turning domain knowledge (e.g. design, rhetoric, and semiotic) and structured visual corpora (see [Visual-Rhetoric-Atlas](https://github.com/666feiyu666/visual-rhetoric-atlas)) into reproducible graphic-design experiments to support graphic design and image generation. 

This project aims to help answer the following questions:
1. How domain knowledge(design, rhetoric, and semiotics) and corpus knowledge(currently use Alphonse Mucha's images) are transformed into one structured image generation prompt?
2. What will be the output of this structured prompt? And how to understand this output? 
3. Following two, how could we use this understanding to reframe the structured image generation prompt?

The ultimate goal ofc is to build an agentic tool to help us make "better" graphic design, but to assemble this tool, it requires several mature components. Basically we don't want this project to have:

- RAG (No need for complicate RAG, because what we want to test here is how corpus knowledge will contribute the design, so there does not exist an RAG scheme currently. But hopefully, this will also inspire us on how to do the data mining and build our corresponding corpus)
- Multi-Round Agent (Just as the research questions indicate, what we want is to understand how the design agent produce the prompt, and how the model produce the image based on the prompt. I believe multi-round agent is more capable to make a graphic design with high quality, but this should be the future direction.)