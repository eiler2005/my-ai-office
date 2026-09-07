import json
from pathlib import Path

import pytest
import yaml

from benka_integrations.profiles import prepare, validate_bindings


def bindings():
    return {"domains": {name: {"users": [100 + idx], "routes": [{"chat_id": -100, "thread_id": idx + 1}]}
                        for idx, name in enumerate(("personal", "work", "family", "sandbox"))}}


def test_profile_generation_keeps_shared_polling_disabled(tmp_path):
    destination = tmp_path / "profiles"
    result = prepare(bindings(), destination, repo=Path(__file__).resolve().parents[2])
    assert result["polling_enabled"] is False and result["route_count"] == 4
    config = yaml.safe_load((destination / "config.yaml").read_text())
    assert config["telegram"]["enabled"] is False
    assert config["platform_toolsets"]["telegram"] == []
    assert len(config["gateway"]["profile_routes"]) == 4
    for domain in result["profiles"]:
        profile = yaml.safe_load((destination / "profiles" / domain / "config.yaml").read_text())
        assert profile["telegram"]["enabled"] is False
        # Regression, 2026-09-07: this asserted only the filename, so a
        # manifest_path pointing into the profile's Hermes home passed review and
        # shipped. Every Benka tool then failed with FileNotFoundError. Assert the
        # full path, and that it names a file the generator actually wrote.
        configured = profile["plugins"]["entries"]["benka"]["settings"]["manifest_path"]
        assert configured == f"/run/benka/profiles/{domain}.json"
        assert (destination / "benka-manifests" / Path(configured).name).is_file()
        manifest = json.loads((destination / "benka-manifests" / (domain + ".json")).read_text())
        assert manifest["vault_root"] == "/vault/" + domain
        assert manifest["mode"] == "standby" and manifest["enabled_operations"] == []
    with pytest.raises(FileExistsError):
        prepare(bindings(), destination, repo=Path(__file__).resolve().parents[2])


def test_duplicate_route_and_untrusted_identity_are_rejected():
    data = bindings()
    data["domains"]["work"]["routes"] = data["domains"]["personal"]["routes"]
    with pytest.raises(ValueError, match="duplicate"):
        validate_bindings(data)
    data = bindings()
    data["domains"]["family"]["users"] = ["@someone"]
    with pytest.raises(ValueError, match="trusted"):
        validate_bindings(data)
