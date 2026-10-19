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
