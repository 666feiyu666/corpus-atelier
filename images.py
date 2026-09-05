"""Display local design variations without changing the source files."""
import base64
import html
from io import BytesIO

def compare_images(paths, labels=None, width=300):
    """Return an IPython HTML comparison; preserve image aspect ratios."""
    from IPython.display import HTML
    from PIL import Image, ImageOps

    paths = list(paths)
    labels = list(labels) if labels is not None else [f"Variant {i + 1}" for i in range(len(paths))]
    if len(paths) != len(labels):
        raise ValueError("Provide one label for each image")
    if not isinstance(width, int) or width < 1:
        raise ValueError("width must be a positive integer")
    cards = []
    for path, label in zip(paths, labels):
        with Image.open(path) as original:
            preview = ImageOps.exif_transpose(original).convert("RGB")
            preview.thumbnail((width * 2, width * 3))
            buffer = BytesIO()
            preview.save(buffer, format="PNG")
        encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
        caption = html.escape(str(label))
        cards.append(
            f'<figure style="margin:0;width:{width}px">'
            f'<img src="data:image/png;base64,{encoded}" alt="{caption}" style="width:100%;height:auto">'
            f'<figcaption>{caption}</figcaption></figure>'
        )
    return HTML('<div style="display:flex;gap:20px;align-items:flex-start;flex-wrap:wrap">' + ''.join(cards) + '</div>')
