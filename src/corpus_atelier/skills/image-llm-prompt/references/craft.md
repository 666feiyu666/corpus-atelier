# Prompt craft checklist

Use this as a diagnostic list while writing `prompt`, not as scene content. Adapted from the
prompt-craft guidance published with GPT-Image2-Skill
(https://github.com/wuyoscar/GPT-Image2-Skill), rewritten for this pipeline.

## Canvas before surface

State deliverable, aspect ratio, and orientation first, then reserve the layout zones: where the
title block, the main visual, and the quiet margin sit. A renderer that receives the layout first
places everything else inside it.

## Exact text in quotes

Every displayed string goes in double quotes, in its approved source language. Separate text
blocks with `/` or layout labels. When text must be readable, say it is crisp and large enough at
the delivered size and that no garbled characters may appear.

## Scene density beats adjectives

Prefer a stated object, count, material, and spatial relation over a quality adjective. Two
specific visual facts describe more than five abstract claims.

## Style anchors stay specific and bounded

Name one visual language and the two or three decisions that make it recognizable. Do not stack
compatible-sounding movement names, and do not let a style label replace the composition.

## Separate the controls

Palette, material, light direction, texture, and degree of realism are separate statements. Keep
them consistent: a stated light direction implies where shadows and highlights fall.

## Focal hierarchy without distortion

Express emphasis through placement, local contrast, light, sharpness, detail, or negative space.
Do not enlarge, detach, duplicate, or distort a carrier element to make something else prominent.

## Negation only for strong priors

One or two targeted constraints at the end, aimed at a plausible misreading of this design. A long
list of "no ..." clauses weakens the positive description and is not a quality control system.

## Editing keeps invariants explicit

For a reference-image edit, say which image is the base, which region or object changes, and what
must stay identical everywhere else. Name identity, pose, framing, light, background, and existing
text as preserved rather than assuming the renderer will infer it.

## Text-heavy layouts

For dense or bilingual layouts, list every required string, state which ones carry hierarchy, and
reserve a clear block for each. Multilingual copy needs an explicit instruction that characters
must remain correct and unwarped.
