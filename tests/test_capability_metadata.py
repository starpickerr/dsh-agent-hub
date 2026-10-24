"""Published plugin metadata survives the actual install/inventory path."""
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent / 'Stella-Core'))

CATALOG = ROOT / 'catalog/official.json'
ROWS = json.loads(CATALOG.read_text())['plugins']


@pytest.mark.parametrize('row', ROWS, ids=lambda row: row['pluginId'])
def test_installed_plugin_supplies_its_own_localized_overview(tmp_path, row):
    from core.capabilities.catalog import CapabilityCatalog
    from core.plugins.distribution import fetch_and_install_from_catalog
    from core.plugins.lifecycle import PluginManager
    from core.plugins.management import ManagementStore
    from core.plugins.manifest import load_manifest
    from core.plugins.package_ops import _sha256_tree

    source = (CATALOG.parent / row['path']).resolve()
    manifest = load_manifest(source)
    assert manifest['description']['zh'].strip()
    assert manifest['description']['en'].strip()
    assert _sha256_tree(source) == row['sha256']
    assert manifest['version'] == row['version']
    manager = PluginManager(ManagementStore(tmp_path), catalog_path=CATALOG)
    result = fetch_and_install_from_catalog(catalog_path=CATALOG, plugin_id=row['pluginId'], package_store=manager.packages)
    assert result['status'] == 'installed'
    catalog = CapabilityCatalog(tmp_path, plugin_manager=manager, tool_rows=lambda: [], mcp_rows=lambda: [])
    detail = catalog.detail('plugins', row['pluginId'])
    assert detail['description'] == manifest['description']
    assert detail['overview'] == manifest['description']
