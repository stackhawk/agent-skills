"""The environment of every git command that a test fixture runs.

It drops each GIT_* variable of the calling process, so a git hook that runs the tests (and
exports GIT_DIR or GIT_INDEX_FILE) cannot point the fixture at the real repository. It reads
no global or system config, so a host setting such as commit.gpgsign, core.hooksPath or
init.templateDir cannot change a fixture commit. It sets a fixed author and committer, unless the
commands set their own (identity=False).
"""
import os

IDENTITY = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com",
            "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com"}


def git_env(identity=True, **extra):
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    return {**env, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
            **(IDENTITY if identity else {}), **extra}
