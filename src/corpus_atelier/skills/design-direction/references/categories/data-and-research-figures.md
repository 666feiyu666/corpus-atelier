# Data and research figures

Adapted from the data-visualization and research-paper-figure slices of the GPT-Image2-Skill
reference gallery (https://github.com/wuyoscar/GPT-Image2-Skill, MIT). Condensed and rewritten for
this pipeline.

## Decide before rendering

- The chart family: small multiples, network graph, sankey, treemap, choropleth, bar or line panel.
- The venue style: camera-ready paper figure, editorial data story, teaching chart.
- The encoding: which visual property carries which quantity, and the units.
- Whether any number is supplied. If not, the figure is schematic and must look schematic.

## Structure that carries the message

- State orientation and panel structure first: figure size, rows and columns, shared axes.
- Label directly where possible; keep one legend for shared encodings.
- Keep scales and alignment identical across repeated panels.
- Use color for one stated meaning, not decoration.
- Leave margins and a clean background so labels stay readable in print.

## Common failures

- Invented values presented as measured data.
- Truncated axes or inconsistent scales between panels.
- A rainbow palette with no stated meaning.
- Chartjunk: 3-D bars, drop shadows, decorative backgrounds.
- Labels too small for the printed figure size.

## Visual QA

- Check axis labels, units, and legend completeness.
- Verify the encoding is consistent across every panel.
- Confirm color meaning is stated and repeated consistently.
- Confirm nothing implies measured data when the brief supplies none.
- Check readability at the intended print size.

## Optional style vocabulary

Camera-ready minimalism, editorial data storytelling, or an isometric diagram style when the brief
explicitly asks for it. Keep the grammar of a chart, not an illustration.
