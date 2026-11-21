"""Catalog notices and research-only provenance: no network/real imports."""
import csv
import importlib
import pathlib
import unittest
from unittest.mock import patch

import catalog_sources

ROOT = pathlib.Path(__file__).resolve().parents[1]

class CatalogSourceTests(unittest.TestCase):
    def test_explicit_fixed_links_only(self):
        with patch.object(catalog_sources.webbrowser, 'open') as browser:
            for _, url in catalog_sources.SOURCES:
                catalog_sources.open_source(url)
                browser.assert_called_with(url)
            with self.assertRaises(ValueError):
                catalog_sources.open_source('https://example.invalid/')
            self.assertEqual(browser.call_count, 3)

    def test_import_has_no_network_or_browser_side_effect(self):
        with patch.object(catalog_sources.webbrowser, 'open') as browser:
            importlib.reload(catalog_sources)
            browser.assert_not_called()

    def test_distributed_provenance_is_review_only(self):
        path=ROOT/'catalog/open_reference_batch2_provenance.csv'
        with path.open(encoding='utf-8-sig') as handle:
            rows=list(csv.DictReader(handle))
        self.assertEqual(len(rows),2)
        self.assertEqual({r['code'] for r in rows},{'42299837','0817513019920'})
        for row in rows:
            self.assertEqual(row['import_ready'],'False')
            self.assertTrue(row['source_url'].startswith('http'))
            self.assertIn('ODbL',row['attribution'])
            self.assertNotIn('sell_price',row)
            self.assertNotIn('buy_price',row)

    def test_desktop_and_phone_visible_notices(self):
        desktop=(ROOT/'main.py').read_text(encoding='utf-8')
        self.assertIn('catalog_sources.build_notice(f)',desktop)
        self.assertLess(desktop.index('catalog_sources.build_notice(f)'), desktop.index('self.btn_cloud_pull ='))
        phone=(ROOT/'mobile.html').read_text(encoding='utf-8')
        self.assertIn('id="catalogSourceNotice"',phone)
        self.assertIn('Contains data from Open Beauty Facts and Open Products Facts',phone)
        for _,url in catalog_sources.SOURCES:
            self.assertIn(url,phone)
        self.assertIn('noopener noreferrer',phone)
        self.assertIn('pharmacy-mobile-v630',(ROOT/'sw.js').read_text())
        self.assertIn('v6.30',desktop)

if __name__=='__main__':unittest.main()
