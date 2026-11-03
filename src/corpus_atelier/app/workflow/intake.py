"""Turn the frozen request into a reviewed brief."""

from __future__ import annotations

from ...design_support.validation import validate
from ...atelier.intake import compile_intake_prompt
from ...language import bind_brief_language
from ..registry import get_profile
from ..state import AtelierState
from .routing import resolve_execution_route

class IntakeMixin:
    """Turn the frozen request into a reviewed brief."""

    def interpret_request(self, state: AtelierState) -> AtelierState:
        run_dir = self._dir(state)
        profile = get_profile(state["profile"])
        self.store.update(run_dir, "interpreting_request")
        prompt = compile_intake_prompt(
            profile, state["user_request"],
            user_requirements=state.get("user_requirements"),
            superseded_user_requirements=state.get("superseded_user_requirements"),
            content_language=state.get("content_language"),
        )
        request = {
            "model": getattr(
                self.text_provider, "model", type(self.text_provider).__name__,
            ),
            "profile": profile.name,
            "schema": profile.brief_schema,
        }
        self.store.json(run_dir, "intake/request.json", request)
        self.store.text(run_dir, "intake/prompt.md", prompt)
        self.store.register(
            run_dir,
            intake_request="intake/request.json",
            intake_prompt="intake/prompt.md",
        )
        try:
            brief, response = self.text_provider.propose(
                prompt,
                schema_name=profile.brief_schema,
            )
            if "user_requirements" in state:
                brief = {**brief, "user_requirements": list(state["user_requirements"])}
            brief = validate(bind_brief_language(brief, state.get("content_language")), profile.brief_schema)
            self.store.json(run_dir, "intake/response.json", response)
            self.store.json(run_dir, "brief.json", brief)
            self.store.register(
                run_dir,
                intake_response="intake/response.json",
                brief="brief.json",
            )
            return {
                "brief": brief,
                "content_language": brief.get("content_language"),
                "execution_route": resolve_execution_route({**state, "brief": brief}),
                "status": "designing",
            }
        except Exception as exc:
            self.store.json(run_dir, "intake/response.json", {
                "status": "failed",
                "error_type": type(exc).__name__,
                "message": str(exc),
            })
            self.store.register(run_dir, intake_response="intake/response.json")
            raise
