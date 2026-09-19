"""Art-led design node."""


def run(state: dict, runtime) -> dict:
    return runtime.design(state, expected_profile="art-article-cover")
