from cleansweep.analysis import build_graph


def write(tmp_path, files):
    for name, text in files.items():
        p = tmp_path / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    return build_graph(str(tmp_path))


def test_toy_repo_dead_code_and_traps(toy_repo):
    g = build_graph(toy_repo)
    assert not g.is_reachable("shopcart/utils.py::format_money_v2")
    assert g.dynamic_risk("shopcart/commands.py::cmd_export")
    assert g.callers("shopcart/cart.py::compute_total") == ["shopcart/cart.py::Cart.checkout"]
    assert not g.imported_by.get("shopcart/pricing_old.py")


def test_relative_imports_methods_and_decorators(tmp_path):
    g = write(
        tmp_path,
        {
            "pkg/__init__.py": "",
            "pkg/a.py": "from .b import helper\n\nclass C:\n    def run(self):\n"
            "        return self.step()\n\n    def step(self):\n        return helper()\n",
            "pkg/b.py": "def helper():\n    return 1\n\n@register\ndef plugin():\n    pass\n",
            "tests/test_a.py": (
                "from pkg.a import C\n\ndef test_run():\n    assert C().run() == 1\n"
            ),
        },
    )
    assert g.is_reachable("pkg/b.py::helper")
    assert "pkg/a.py::C.step" in g.callees("pkg/a.py::C.run")
    assert g.is_reachable("pkg/b.py::plugin")  # decorated => entry point
    assert g.dynamic_risk("pkg/b.py::plugin")
    assert {u.kind for u in g.units()} == {"file", "class", "function"}


def test_framework_callbacks_follow_bases_to_the_framework(tmp_path):
    g = write(
        tmp_path,
        {
            "app/__init__.py": "",
            "app/base.py": "from textual.screen import Screen\n\nclass Base(Screen[None]):\n"
            "    pass\n",
            "app/ui.py": "import textual.app\nfrom .base import Base\n\n"
            "class Welcome(Base):\n    def compose(self):\n        pass\n\n"
            "    def on_mount(self):\n        pass\n\n    def helper(self):\n        pass\n\n"
            "class Main(textual.app.App):\n    def action_quit(self):\n        pass\n\n"
            "class Plain:\n    def on_mount(self):\n        pass\n\n"
            "class Err(ValueError):\n    def compose(self):\n        pass\n",
            "app/web.py": "from django.views.generic import ListView\nimport click\n"
            "from _pytest.nodes import Item\n\n"
            "class Books(ListView):\n    def get_queryset(self):\n        pass\n\n"
            "class Cli(click.Command):\n    def invoke(self, ctx):\n        pass\n\n"
            "class YamlItem(Item):\n    def runtest(self):\n        pass\n",
        },
    )
    found = {
        k: g.framework_callback(f"app/{k}")
        for k in (
            "ui.py::Welcome.compose",
            "ui.py::Welcome.on_mount",
            "ui.py::Welcome.helper",
            "ui.py::Main.action_quit",
            "ui.py::Plain.on_mount",
            "ui.py::Err.compose",
            "web.py::Books.get_queryset",
            "web.py::Cli.invoke",
            "web.py::YamlItem.runtest",
        )
    }
    assert found == {
        "ui.py::Welcome.compose": "textual",  # through the project's own Base(Screen[None])
        "ui.py::Welcome.on_mount": "textual",
        "ui.py::Welcome.helper": None,  # not a Textual callback name
        "ui.py::Main.action_quit": "textual",
        "ui.py::Plain.on_mount": None,  # no framework base
        "ui.py::Err.compose": None,  # a standard-library base
        "web.py::Books.get_queryset": "django",
        "web.py::Cli.invoke": "click",
        "web.py::YamlItem.runtest": "pytest",
    }
