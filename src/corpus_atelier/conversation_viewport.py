"""A small CCv2 controller that preserves the conversation reading position."""

import streamlit as st


_JS = """
export default function({parentElement, data}) {
  const doc = parentElement.ownerDocument;
  const shell = doc.querySelector('.st-key-' + CSS.escape(data.surface + '_' + data.task));
  if (!shell) return;
  const candidates = [shell, shell.parentElement, ...shell.querySelectorAll('[data-testid]')];
  const main = candidates.find(el => ['auto', 'scroll'].includes(getComputedStyle(el).overflowY)) || shell;
  // Each panel owns its scroll position; discussion never moves the design panel.
  const registry = window.__atelierViewports ||= new Map();
  const identity = data.task + ':' + data.surface;
  let state = registry.get(identity);
  const firstVisit = !state;
  if (!state) {
    state = {top: main.scrollTop, follow: true, token: data.token, command: data.command};
    registry.set(identity, state);
  }
  const target = () => shell.querySelector('[id="atelier-latest-brief"]');
  const button = parentElement.querySelector('button');
  button.textContent = data.label;
  let applying = false;
  let frame = 0;
  const showButton = () => {
    const anchor = target();
    button.hidden = data.surface === 'assistant_messages' || !anchor ||
      (anchor.getBoundingClientRect().top >= main.getBoundingClientRect().top - 20 &&
       anchor.getBoundingClientRect().top < main.getBoundingClientRect().top + 180);
  };
  const move = () => {
    applying = true;
    const anchor = target();
    if (state.follow && data.surface === 'assistant_messages') {
      main.scrollTop = main.scrollHeight;
      state.top = main.scrollTop;
    } else if (state.follow && anchor) {
      main.scrollTop += anchor.getBoundingClientRect().top - main.getBoundingClientRect().top - 20;
      state.top = main.scrollTop;
    } else {
      main.scrollTop = state.top;
    }
    showButton();
    requestAnimationFrame(() => { applying = false; });
  };
  const explicit = data.command !== state.command;
  if (explicit || firstVisit) {
    state.follow = true;
    state.userScroll = false;
  }
  const newContent = data.token !== state.token;
  state.token = data.token;
  state.command = data.command;
  const onIntent = () => { state.follow = false; state.userScroll = true; };
  const onKey = e => {
    if (['PageUp', 'PageDown', 'Home', 'End', 'ArrowUp', 'ArrowDown', 'Tab'].includes(e.key)) onIntent();
  };
  const onScroll = () => {
    if (!applying && state.userScroll) {
      state.top = main.scrollTop;
      // Reading history or scrolling the editor is a user-controlled position.
      state.follow = data.surface === 'assistant_messages' && main.scrollHeight - main.scrollTop - main.clientHeight < 60;
    }
    showButton();
  };
  button.onclick = () => { state.follow = true; state.userScroll = false; move(); };
  main.addEventListener('wheel', onIntent, {passive: true});
  main.addEventListener('touchstart', onIntent, {passive: true});
  main.addEventListener('pointerdown', onIntent, {passive: true});
  main.addEventListener('keydown', onKey);
  main.addEventListener('scroll', onScroll, {passive: true});
  const observer = new ResizeObserver(() => {
    cancelAnimationFrame(frame);
    frame = requestAnimationFrame(move);
  });
  observer.observe(shell);
  for (const child of main.children) observer.observe(child);
  if (firstVisit || explicit || newContent) frame = requestAnimationFrame(move);
  else frame = requestAnimationFrame(() => { main.scrollTop = state.top; showButton(); });
  return () => {
    cancelAnimationFrame(frame);
    observer.disconnect();
    main.removeEventListener('wheel', onIntent);
    main.removeEventListener('touchstart', onIntent);
    main.removeEventListener('pointerdown', onIntent);
    main.removeEventListener('keydown', onKey);
    main.removeEventListener('scroll', onScroll);
  };
}
"""

def create_viewport():
    """Register once in the app entry point for the current Streamlit runtime."""
    return st.components.v2.component(
        "atelier_conversation_viewport", html='<button class="atelier-latest-button" type="button" hidden></button>',
        js=_JS, isolate_styles=False,
        css="""
    .atelier-latest-button {
      position: fixed; right: 2rem; bottom: 6rem; z-index: 100;
      border: 1px solid var(--st-border-color); border-radius: 2rem;
      background: var(--st-background-color); color: var(--st-text-color);
      padding: .5rem 1rem; cursor: pointer; box-shadow: 0 2px 12px #0002;
    }
        """,
    )


def render_viewport(run_id: str, conversation: dict, *, label: str, controller,
                    surface: str = "design_panel", token: str | None = None) -> None:
    controller(key=f"viewport_{surface}_{run_id}", height=0, data={
        "task": run_id,
        "surface": surface,
        "token": token or (str(conversation["revision"]) if surface == "design_panel"
                           else str(len(conversation["messages"]))),
        "command": st.session_state.get(f"viewport_command_{surface}_{run_id}", 0), "label": label,
    })


def follow_latest(run_id: str, surface: str = "design_panel") -> None:
    key = f"viewport_command_{surface}_{run_id}"
    st.session_state[key] = st.session_state.get(key, 0) + 1
