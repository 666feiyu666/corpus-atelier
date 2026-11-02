"""The atelier (generation) layer.

Compiles briefs into visual directions, finished design proposals, image-model
specifications, and generated/edited images. The corpus layer feeds it
references; the interaction layer drives it through conversation.
"""

from .design_direction import (
    compile_design_direction_prompt,
    load_historical_cards,
    synthesize_design_directions,
    validate_design_direction_plan,
)
from .design_implementation import (
    compile_design_implementation_prompt,
    synthesize_design_implementation,
)
from .image_prompt import (
    compile_generation_prompt,
    compile_image_spec_prompt,
    synthesize_image_spec,
)
from .image_prompt.prompt_compiler import compile_positive_negative
from .intake import compile_intake_prompt
from .reverse_prompt import reverse_prompt, reverse_prompt_instruction

__all__ = [
    "compile_design_direction_prompt",
    "load_historical_cards",
    "synthesize_design_directions",
    "validate_design_direction_plan",
    "compile_design_implementation_prompt",
    "synthesize_design_implementation",
    "compile_generation_prompt",
    "compile_image_spec_prompt",
    "compile_positive_negative",
    "synthesize_image_spec",
    "compile_intake_prompt",
    "reverse_prompt",
    "reverse_prompt_instruction",
]
