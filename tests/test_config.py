import scribe.config as cfg


def test_theme_state_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(cfg, "STATE_PATH", str(tmp_path / "state.json"))
    assert cfg.load_last_theme() is None
    cfg.save_last_theme("gruvbox")
    assert cfg.load_last_theme() == "gruvbox"
    cfg.save_last_theme("tokyo-night")
    assert cfg.load_last_theme() == "tokyo-night"
