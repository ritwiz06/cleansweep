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
    "http.server": {
        "packages": ("http", "socketserver"),
        "names": {
            "handle",
            "setup",
            "finish",
            "log_message",
            "log_request",
            "log_error",
            "send_head",
            "version_string",
        },
        "prefixes": ("do_",),
    },
    "ast.NodeVisitor": {
        "packages": ("ast",),
        "names": {"generic_visit"},
        "prefixes": ("visit_",),
    },
    "torch": {
        "packages": ("torch",),
        "names": {"forward", "extra_repr", "reset_parameters"},
        "prefixes": (),
    },
    "lightning": {
        "packages": ("lightning", "pytorch_lightning"),
        "names": {
            "forward",
            "training_step",
            "validation_step",
            "test_step",
            "predict_step",
            "configure_optimizers",
            "train_dataloader",
            "val_dataloader",
            "test_dataloader",
            "predict_dataloader",
            "prepare_data",
            "setup",
            "teardown",
        },
        "prefixes": ("on_",),
    },
    "hatchling": {
        "packages": ("hatchling",),
        "names": {"initialize", "finalize", "clean", "dependencies"},
        "prefixes": (),
    },
}

_BY_PACKAGE = {pkg: name for name, fw in FRAMEWORKS.items() for pkg in fw["packages"]}


def framework_for(module: str) -> str | None:
    """The framework a module belongs to (by its top-level package), or None."""
    return _BY_PACKAGE.get(module.split(".")[0])


def is_callback_name(framework: str, method: str) -> bool:
    fw = FRAMEWORKS[framework]
    return method in fw["names"] or method.startswith(fw["prefixes"])


# Base classes whose subclasses a framework finds by itself, by top-level package. No project code
# names such a subclass, so the graph sees no use of the class. Only bases the framework really
# discovers: views, forms, click commands or torch modules are instantiated by the project's code.
DISCOVERED_BASES: dict[str, dict[str, str]] = {
    "django": {
        "Model": "Django model",  # the app registry and migrations know it by name
        "AppConfig": "Django app config",  # found in the apps.py of an installed app
        "BaseCommand": "Django management command",  # found by its file in management/commands
        "AppCommand": "Django management command",
        "LabelCommand": "Django management command",
        "Migration": "Django migration",  # found by its file in the app's migrations folder
        "TestCase": "Django test case",  # collected by the test runner
        "SimpleTestCase": "Django test case",
        "TransactionTestCase": "Django test case",
        "LiveServerTestCase": "Django test case",
    },
    "unittest": {
        "TestCase": "unittest test case",
        "IsolatedAsyncioTestCase": "unittest test case",
    },
    "hatchling": {
        "BuildHookInterface": "hatchling build hook",  # found in hatch_build.py by its base
        "MetadataHookInterface": "hatchling metadata hook",
    },
}
# Module-level functions a plugin system calls by name, by prefix.
MODULE_HOOKS: dict[str, tuple[str, ...]] = {
    "pytest": ("pytest_",),  # hooks of a conftest or plugin module
    "hatch": ("hatch_register_",),  # hatch plugin registration hooks
}


def discovered_base(base: str) -> str | None:
    """What a class is when a framework discovers subclasses of `base` (a dotted name such as
    django.db.models.Model), or None."""
    return DISCOVERED_BASES.get(base.split(".")[0], {}).get(base.rsplit(".", 1)[-1])


def module_hook(name: str) -> str | None:
    """The plugin system that calls a module-level function with this name, or None."""
    return next((s for s, prefixes in MODULE_HOOKS.items() if name.startswith(prefixes)), None)
