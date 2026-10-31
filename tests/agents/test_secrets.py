from cleansweep.agents.secrets import Redactor, is_secret_file, public_findings, scan

KEY = "AKIA" + "ABCDEFGHIJKLMNOP"
TOKEN = "ghp_" + "a" * 36


def test_scan_finds_planted_keys_without_keeping_values_in_the_report(tmp_path):
    (tmp_path / "settings.py").write_text(f'AWS_KEY = "{KEY}"\napi_token = "s3cr3t-value-123"\n')
    (tmp_path / ".env").write_text("VOYAGER_API_KEY=whatever\n")
    (tmp_path / "ok.py").write_text('password = "changeme"\n')
    found = scan(str(tmp_path))
    kinds = {f["kind"] for f in found["findings"]}
    assert {"aws_access_key", "assigned_secret"} <= kinds
    assert found["files"] == [".env"]
    assert KEY in found["values"] and "s3cr3t-value-123" in found["values"]
    assert all(f["path"] != "ok.py" for f in found["findings"])
    shown = str(public_findings(found))
    assert KEY not in shown and "s3cr3t" not in shown


def test_redactor_masks_values_and_patterns():
    redact = Redactor({"s3cr3t-value-123"})
    text = f'key {KEY}, token {TOKEN}, api_token = "s3cr3t-value-123", url https://bob:pw123@host/x'
    out = redact(text)
    assert (
        KEY not in out and TOKEN not in out and "s3cr3t-value-123" not in out and "pw123" not in out
    )
    assert "[REDACTED" in out


def test_secret_files():
    assert (
        is_secret_file(".env")
        and is_secret_file("deploy/id_rsa")
        and is_secret_file("certs/server.pem")
    )
    assert not is_secret_file(".env.example") and not is_secret_file("shop/env.py")
