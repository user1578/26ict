from pathlib import Path

from app.config import load_local_env


def test_local_env_never_overrides_process_or_loads_example(tmp_path, monkeypatch):
    local = tmp_path / '.env'
    local.write_text('AMAP_API_KEY="local-only"\nTRAVELGUARD_TOOL_API_KEY=local-auth\n# ignore\n', encoding='utf-8')
    monkeypatch.setenv('AMAP_API_KEY', 'process-wins')
    monkeypatch.delenv('TRAVELGUARD_TOOL_API_KEY', raising=False)
    load_local_env(local)
    assert __import__('os').environ['AMAP_API_KEY'] == 'process-wins'
    assert __import__('os').environ['TRAVELGUARD_TOOL_API_KEY'] == 'local-auth'
    load_local_env(tmp_path / 'missing')
