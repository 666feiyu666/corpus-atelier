"""Small offline fixtures for model boundaries."""
import json
from types import SimpleNamespace
from graphic_design_helper.proposal_schema import TEXT_FIELDS, LIST_FIELDS


def image_spec():
    return {"communication_objective": "Invite a pause", "audience_and_context": "Office noticeboard",
            "visible_copy": ["Pause."], "composition": "A small circle below a large headline",
            "typography": "Large readable sans serif", "visual_treatment": "Black ink on white",
            "allowed_variation": ["Circle position within the lower half"], "exclusions": ["Additional copy"]}


def proposal():
    return {**{k: "Explanation" for k in TEXT_FIELDS}, **{k: [] for k in LIST_FIELDS},
            "status": "ready", "image_spec": image_spec()}


def designer_client(value, calls):
    def create(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(status="completed", output_text=json.dumps(value))
    return SimpleNamespace(responses=SimpleNamespace(create=create))
