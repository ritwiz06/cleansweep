"""Methods a framework calls by name: the conventions, one table for all frameworks.

A method counts as a framework callback when its class inherits, directly or through the
project's own classes, from a class imported from one of the framework's packages, and its name
is one of the framework's callback names or starts with one of its callback prefixes. Nothing in
the project calls such a method, so the code graph can't see that it is used.
"""

from __future__ import annotations

FRAMEWORKS: dict[str, dict] = {
    "textual": {
        "packages": ("textual",),
        "names": {
            "compose",
            "render",
            "render_line",
            "render_lines",
            "get_content_width",
            "get_content_height",
            "check_action",
        },
        "prefixes": (
            "on_",
            "_on_",
            "action_",
            "watch_",
            "_watch_",
            "compute_",
            "validate_",
            "key_",
        ),
    },
    "django": {
        "packages": ("django",),
        "names": {
            "save",
            "delete",
            "clean",
            "full_clean",
            "dispatch",
            "get",
            "post",
            "put",
            "patch",
            "head",
            "options",
            "handle",
            "add_arguments",
            "ready",
            "form_valid",
            "form_invalid",
            "save_model",
            "delete_model",
            "natural_key",
            "get_absolute_url",
            "process_request",
            "process_response",
            "process_view",
            "process_exception",
        },
        # get_queryset, get_context_data, has_add_permission, clean_<field>, ...
        "prefixes": ("get_", "has_", "clean_", "render_"),
    },
    "flask": {
        "packages": ("flask",),
        "names": {"get", "post", "put", "patch", "delete", "head", "options", "dispatch_request"},
        "prefixes": (),
    },
    "fastapi": {
        "packages": ("fastapi", "starlette"),
        "names": {"get", "post", "put", "patch", "delete", "head", "options", "dispatch"},
        "prefixes": (),
    },
    "click": {
        "packages": ("click", "typer"),
        "names": {
            "invoke",
            "main",
            "make_context",
            "parse_args",
            "get_command",
            "list_commands",
            "resolve_command",
            "format_help",
            "format_usage",
            "format_options",
            "get_params",
            "get_help",
            "convert",
            "get_metavar",
            "shell_complete",
        },
        "prefixes": (),
    },
    "pytest": {
        "packages": ("pytest", "_pytest"),
        "names": {"runtest", "reportinfo", "repr_failure", "collect", "setup", "teardown"},
        "prefixes": ("pytest_",),
    },
}

_BY_PACKAGE = {pkg: name for name, fw in FRAMEWORKS.items() for pkg in fw["packages"]}


def framework_for(module: str) -> str | None:
    """The framework a module belongs to (by its top-level package), or None."""
    return _BY_PACKAGE.get(module.split(".")[0])


def is_callback_name(framework: str, method: str) -> bool:
    fw = FRAMEWORKS[framework]
    return method in fw["names"] or method.startswith(fw["prefixes"])
