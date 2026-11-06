from cleansweep.analysis import build_graph
from cleansweep.analysis.dynamic_refs import resolve_dynamic_refs


def resolve(tmp_path, files):
    for name, text in files.items():
        p = tmp_path / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    return resolve_dynamic_refs(build_graph(str(tmp_path)))


def test_entry_points_in_pyproject_with_a_src_layout(tmp_path):
    g = None
    refs = resolve(
        tmp_path,
        {
            "pyproject.toml": '[project]\nname = "pkg"\n[project.scripts]\n'
            'cli = "pkg.cli:main"\nfancy = "pkg.cli:other [color]"\n'
            '[project.gui-scripts]\ngui = "pkg.cli:window"\n'
            '[project.entry-points."pkg.plugins"]\nload = "pkg.cli:Plugin.load"\n'
            '[project.entry-points.pytest11]\nmine = "pkg.plugin"\n',
            "src/pkg/__init__.py": "",
            "src/pkg/cli.py": "def main():\n    pass\n\ndef other():\n    pass\n\n"
            "def window():\n    pass\n\ndef unused():\n    pass\n\n"
            "class Plugin:\n    def load(self):\n        pass\n",
            "src/pkg/plugin.py": "",
        },
    )
    assert refs["src/pkg/cli.py::main"] == [
        'entry point console_scripts "cli = pkg.cli:main" in pyproject.toml'
    ]  # the config-file scan does not repeat it
    assert refs["src/pkg/cli.py::other"] == [
        'entry point console_scripts "fancy = pkg.cli:other" in pyproject.toml'
    ]
    assert refs["src/pkg/cli.py::window"][0].startswith("entry point gui_scripts")
    assert refs["src/pkg/cli.py::Plugin.load"][0].startswith("entry point pkg.plugins")
    assert refs["src/pkg/plugin.py"][0].startswith('entry point pytest11 "mine = pkg.plugin"')
    assert "src/pkg/cli.py::unused" not in refs
    g = build_graph(str(tmp_path))
    assert not g.is_reachable("src/pkg/cli.py::Plugin.load")  # the graph itself is unchanged


def test_poetry_scripts_and_plugins(tmp_path):
    refs = resolve(
        tmp_path,
        {
            "pyproject.toml": "[tool.poetry.scripts]\n"
            'a = "pkg.cli:main"\nb = { callable = "pkg.cli:other" }\n'
            '[tool.poetry.plugins."pkg.hooks"]\nc = "pkg.cli:third"\n',
            "pkg/__init__.py": "",
            "pkg/cli.py": "def main():\n    pass\n\ndef other():\n    pass\n\n"
            "def third():\n    pass\n",
        },
    )
    assert refs["pkg/cli.py::main"] == [
        'entry point poetry scripts "a = pkg.cli:main" in pyproject.toml'
    ]
    assert refs["pkg/cli.py::other"][0].startswith("entry point poetry scripts")
    assert refs["pkg/cli.py::third"][0].startswith("entry point poetry pkg.hooks")


def test_entry_points_in_setup_cfg_and_setup_py(tmp_path):
    refs = resolve(
        tmp_path,
        {
            "setup.cfg": "[options.entry_points]\nconsole_scripts =\n    foo = pkg.cli:main\n",
            "setup.py": "from setuptools import setup\n\nsetup(entry_points={"
            '"console_scripts": ["bar = pkg.cli:other"], '
            '"pkg.hooks": "baz = pkg.cli:third"})\n',
            "pkg/__init__.py": "",
            "pkg/cli.py": "def main():\n    pass\n\ndef other():\n    pass\n\n"
            "def third():\n    pass\n",
        },
    )
    assert refs["pkg/cli.py::main"] == [
        'entry point console_scripts "foo = pkg.cli:main" in setup.cfg'
    ]
    assert refs["pkg/cli.py::other"] == [
        'entry point console_scripts "bar = pkg.cli:other" in setup.py'
    ]
    assert refs["pkg/cli.py::third"] == ['entry point pkg.hooks "baz = pkg.cli:third" in setup.py']


def test_build_backend_and_hatchling_hooks(tmp_path):
    refs = resolve(
        tmp_path,
        {
            "pyproject.toml": '[build-system]\nbuild-backend = "backend"\n'
            'backend-path = ["_build"]\n[tool.hatch.build.hooks.custom]\n',
            "_build/backend.py": "def build_wheel(d):\n    pass\n\ndef build_sdist(d):\n"
            "    pass\n\ndef helper():\n    pass\n",
            "hatch_build.py": "from hatchling.builders.hooks.plugin.interface import "
            "BuildHookInterface\n\nclass Hook(BuildHookInterface):\n    pass\n\n"
            "def hatch_register_build_hook():\n    return Hook\n",
        },
    )
    assert refs["_build/backend.py::build_wheel"] == [
        'PEP 517 build hook of the in-tree build backend "backend" in pyproject.toml'
    ]
    assert "_build/backend.py::build_sdist" in refs and "_build/backend.py::helper" not in refs
    assert refs["hatch_build.py"] == [
        "hatchling custom hook file named in pyproject.toml [tool.hatch.build.hooks.custom]"
    ]
    assert refs["hatch_build.py::Hook"] == [
        "hatchling build hook class (framework base class "
        "hatchling.builders.hooks.plugin.interface.BuildHookInterface)"
    ]
    assert refs["hatch_build.py::hatch_register_build_hook"] == [
        "hatch hook: hatch calls it by name"
    ]


def test_dotted_names_in_config_files(tmp_path):
    refs = resolve(
        tmp_path,
        {
            "pytest.ini": "[pytest]\naddopts = -p pkg.plug\n",
            "logging.yaml": "handlers:\n  main:\n    class: pkg.log.Handler\n",
            "conf/app.json": '{"factory": "pkg.log:make", "site": "example.com"}\n',
            "tool.toml": '[x]\nfile = "pkg/log.py"\nalso = "pkg.log.py"\nword = "make"\n',
            "pkg/__init__.py": "",
            "pkg/plug.py": "",
            "pkg/log.py": "class Handler:\n    pass\n\ndef make():\n    pass\n",
        },
    )
    assert refs["pkg/plug.py"] == ['"pkg.plug" named in pytest.ini:2']
    assert refs["pkg/log.py::Handler"] == ['"pkg.log.Handler" named in logging.yaml:3']
    assert refs["pkg/log.py::make"] == ['"pkg.log:make" named in conf/app.json:1']
    assert "pkg/log.py" not in refs  # a path or file name is not a dotted name


def test_django_settings_lists_and_dotted_strings_in_code(tmp_path):
    refs = resolve(
        tmp_path,
        {
            "site/__init__.py": "",
            "site/settings.py": 'INSTALLED_APPS = ["shop.apps.ShopConfig"]\n'
            'MIDDLEWARE = ["shop.middleware.Timing"]\nROOT_URLCONF = "shop.urls"\n',
            "shop/__init__.py": "",
            "shop/apps.py": "class ShopConfig:\n    pass\n",
            "shop/middleware.py": "class Timing:\n    pass\n",
            "shop/urls.py": "import logging\n\nlog = logging.getLogger('shop.urls')\n"
            "VIEW = 'shop.views.index'\n",
            "shop/views.py": "def index():\n    pass\n",
            "shop/tasks.py": "def later():\n    return run('shop.views.page')\n",
        },
    )
    assert refs["shop/apps.py::ShopConfig"] == [
        '"shop.apps.ShopConfig" named in site/settings.py INSTALLED_APPS'
    ]
    assert refs["shop/middleware.py::Timing"] == [
        '"shop.middleware.Timing" named in site/settings.py MIDDLEWARE'
    ]
    assert refs["shop/urls.py"] == ['"shop.urls" named in site/settings.py ROOT_URLCONF']
    assert refs["shop/views.py::index"] == ['"shop.views.index" named in shop/urls.py VIEW']
    assert "shop/views.py::page" not in refs  # names no unit


def test_decorator_registries(tmp_path):
    refs = resolve(
        tmp_path,
        {
            "app.py": "import functools\nimport click\nimport pytest\nfrom unittest import mock\n"
            "from django.contrib import admin\nfrom django.dispatch import receiver\n"
            "from .web import router\n\napp = make_app()\n\n"
            "@app.route('/')\ndef index():\n    pass\n\n"
            "@router.get('/x')\ndef get_x():\n    pass\n\n"
            "@click.command()\ndef cli():\n    pass\n\n"
            "@pytest.fixture\ndef db():\n    pass\n\n"
            "@receiver(saved)\ndef on_saved(sender):\n    pass\n\n"
            "@admin.register(Book)\nclass BookAdmin:\n    pass\n\n"
            "@functools.lru_cache\ndef cached():\n    pass\n\n"
            "@pytest.mark.slow\ndef marked():\n    pass\n\n"
            "@mock.patch('x.y')\ndef patched(m):\n    pass\n\n"
            "class C:\n    @property\n    def v(self):\n        pass\n\n"
            "    @v.setter\n    def v(self, x):\n        pass\n\n"
            "    @staticmethod\n    def s():\n        pass\n",
            "web.py": "router = make_router()\n",
        },
    )
    assert refs["app.py::index"] == ["registered by @app.route"]
    assert refs["app.py::get_x"] == ["registered by @router.get"]
    assert refs["app.py::cli"] == ["registered by @click.command"]
    assert refs["app.py::db"] == ["registered by @pytest.fixture"]
    assert refs["app.py::on_saved"] == ["registered by @receiver"]
    assert refs["app.py::BookAdmin"] == ["registered by @admin.register"]
    for name in ("cached", "marked", "patched", "C.v", "C.s"):
        assert f"app.py::{name}" not in refs, name


def test_all_lists_and_reexports(tmp_path):
    refs = resolve(
        tmp_path,
        {
            "pkg/__init__.py": "from .core import api\n\n__all__ = ['api', 'local']\n"
            "__all__ += ['later']\n\ndef local():\n    pass\n\ndef later():\n    pass\n",
            "pkg/core.py": "def api():\n    pass\n\ndef other():\n    pass\n",
        },
    )
    assert refs["pkg/core.py::api"] == ["listed in __all__ of pkg/__init__.py"]
    assert refs["pkg/__init__.py::local"] == ["listed in __all__ of pkg/__init__.py"]
    assert "pkg/__init__.py::later" in refs and "pkg/core.py::other" not in refs


def test_getattr_and_import_module_with_literal_strings(tmp_path):
    refs = resolve(
        tmp_path,
        {
            "pkg/__init__.py": "",
            "pkg/loader.py": "import importlib\nimport os\nfrom pkg import handlers\n"
            "from pkg.handlers import Handler\n\n\ndef load(obj, x):\n"
            "    mod = importlib.import_module('pkg.plugins.alpha')\n"
            "    getattr(mod, 'setup')()\n"
            "    importlib.import_module('.beta', package='pkg.plugins')\n"
            "    __import__('pkg.plugins.gamma')\n"
            "    getattr(handlers, 'on_save')\n"
            "    getattr(handlers, f'cmd_{x}')\n"
            "    hasattr(Handler, 'close')\n"
            "    getattr(obj, 'flush')\n"
            "    return getattr(os, 'path')\n\n\n"
            "class Thing:\n    def run(self):\n        return getattr(self, 'step')()\n\n"
            "    def step(self):\n        pass\n",
            "pkg/handlers.py": "def on_save():\n    pass\n\ndef on_load():\n    pass\n\n"
            "def cmd_a():\n    pass\n\ndef cmd_b():\n    pass\n\n"
            "class Handler:\n    def close(self):\n        pass\n\n"
            "    def open(self):\n        pass\n\n"
            "class Buffer:\n    def flush(self):\n        pass\n\n"
            "def flush():\n    pass\n",
            "pkg/plugins/__init__.py": "",
            "pkg/plugins/alpha.py": "def setup():\n    pass\n\ndef other():\n    pass\n",
            "pkg/plugins/beta.py": "",
            "pkg/plugins/gamma.py": "",
        },
    )
    assert refs["pkg/plugins/alpha.py"] == ["import_module('pkg.plugins.alpha') in pkg/loader.py:8"]
    assert refs["pkg/plugins/alpha.py::setup"] == ["getattr(mod, 'setup') in pkg/loader.py:9"]
    assert refs["pkg/plugins/beta.py"] == ["import_module('.beta') in pkg/loader.py:10"]
    assert refs["pkg/plugins/gamma.py"] == ["__import__('pkg.plugins.gamma') in pkg/loader.py:11"]
    assert refs["pkg/handlers.py::on_save"] == ["getattr(handlers, 'on_save') in pkg/loader.py:12"]
    assert refs["pkg/handlers.py::cmd_a"] == ["getattr(handlers, f'cmd_{x}') in pkg/loader.py:13"]
    assert "pkg/handlers.py::cmd_b" in refs
    assert refs["pkg/handlers.py::Handler.close"] == [
        "hasattr(Handler, 'close') in pkg/loader.py:14"
    ]
    assert refs["pkg/handlers.py::Buffer.flush"] == ["getattr(obj, 'flush') in pkg/loader.py:15"]
    assert refs["pkg/loader.py::Thing.step"] == ["getattr(self, 'step') in pkg/loader.py:21"]
    for key in ("plugins/alpha.py::other", "handlers.py::on_load", "handlers.py::Handler.open"):
        assert f"pkg/{key}" not in refs, key
    assert "pkg/handlers.py::flush" not in refs  # an unknown object's attribute is a method


def test_subclasses_discovery(tmp_path):
    refs = resolve(
        tmp_path,
        {
            "pkg/__init__.py": "",
            "pkg/base.py": "class Plugin:\n    @classmethod\n    def all(cls):\n"
            "        return cls.__subclasses__()\n\nclass Other:\n    pass\n",
            "pkg/impl.py": "from pkg.base import Plugin, Other\n\nclass A(Plugin):\n    pass\n\n"
            "class B(A):\n    pass\n\nclass C(Other):\n    pass\n",
        },
    )
    why = "subclass of Plugin, which pkg/base.py:4 discovers via __subclasses__()"
    assert refs["pkg/impl.py::A"] == [why] and refs["pkg/impl.py::B"] == [why]
    assert "pkg/impl.py::C" not in refs and "pkg/base.py::Plugin" not in refs


def test_classes_a_framework_finds_by_their_base_class(tmp_path):
    refs = resolve(
        tmp_path,
        {
            "shop/__init__.py": "",
            "shop/models.py": "from django.db import models\n\n"
            "class Stamped(models.Model):\n    pass\n\nclass Book(Stamped):\n    pass\n",
            "shop/apps.py": "from django.apps import AppConfig\n\n"
            "class ShopConfig(AppConfig):\n    pass\n",
            "shop/management/commands/close.py": "from django.core.management.base import "
            "BaseCommand\n\nclass Command(BaseCommand):\n    pass\n",
            "shop/migrations/0001_initial.py": "from django.db import migrations\n\n"
            "class Migration(migrations.Migration):\n    pass\n",
            "shop/checks.py": "import unittest\n\nclass Checks(unittest.TestCase):\n    pass\n",
            "shop/views.py": "import torch\nfrom django.views.generic import ListView\n\n"
            "class Books(ListView):\n    pass\n\nclass Net(torch.nn.Module):\n    pass\n",
        },
    )
    assert refs["shop/models.py::Book"] == [
        "Django model class (framework base class django.db.models.Model)"
    ]
    assert refs["shop/apps.py::ShopConfig"][0].startswith("Django app config class")
    assert refs["shop/management/commands/close.py::Command"][0].startswith(
        "Django management command class"
    )
    assert refs["shop/migrations/0001_initial.py::Migration"][0].startswith("Django migration")
    assert refs["shop/checks.py::Checks"][0].startswith("unittest test case class")
    assert "shop/views.py::Books" not in refs and "shop/views.py::Net" not in refs


def test_module_level_plugin_hooks(tmp_path):
    refs = resolve(
        tmp_path,
        {"plug.py": "def pytest_configure(config):\n    pass\n\ndef helper():\n    pass\n"},
    )
    assert refs == {"plug.py::pytest_configure": ["pytest hook: pytest calls it by name"]}


def test_graph_resolves_lazily_through_dynamic_refs(tmp_path):
    (tmp_path / "plug.py").write_text("def pytest_configure(config):\n    pass\n")
    g = build_graph(str(tmp_path))
    assert g._refs is None  # v1 never asks, so it never pays for it
    assert g.dynamic_refs("plug.py::pytest_configure") == ["pytest hook: pytest calls it by name"]
    assert g.dynamic_refs("plug.py") == []
