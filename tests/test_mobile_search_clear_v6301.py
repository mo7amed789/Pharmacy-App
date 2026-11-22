"""Regression checks for the mobile main-search clear control."""
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
HTML = (ROOT / 'mobile.html').read_text(encoding='utf-8')


class MobileSearchClearTests(unittest.TestCase):
    def test_accessible_button_and_hidden_empty_state(self):
        self.assertIn('id="searchClear"', HTML)
        self.assertIn('aria-label="مسح البحث / Clear search"', HTML)
        self.assertIn('aria-controls="searchInput results" hidden', HTML)
        self.assertIn("$('searchClear').hidden=!input.value", HTML)

    def test_direction_is_based_on_actual_search_text(self):
        self.assertIn('dir="auto"', HTML)
        self.assertIn('dataset.textDir=getComputedStyle(input).direction', HTML)
        self.assertIn('.search[data-text-dir=rtl] .search-clear{left:5px;right:auto}', HTML)
        self.assertIn('padding-right:58px;text-align:left', HTML)
        self.assertIn('padding-left:58px;text-align:right', HTML)

    def test_native_icon_is_suppressed_only_for_custom_search(self):
        self.assertIn('.search input::-webkit-search-cancel-button', HTML)
        self.assertIn('width:44px;height:44px', HTML)
        self.assertIn('.search-clear[hidden]{display:none}', HTML)

    def test_clear_uses_input_pipeline_and_restores_focus(self):
        start=HTML.index("$('searchClear').addEventListener('click'")
        end=HTML.index("$('searchInput').addEventListener('input'", start)
        handler=HTML[start:end]
        self.assertIn("$('searchInput').value=''", handler)
        self.assertIn("dispatchEvent(new Event('input',{bubbles:true}))", handler)
        self.assertIn("$('searchInput').focus()", handler)

    def test_stale_results_cannot_reappear_after_clear(self):
        self.assertIn('searchRequest++', HTML)
        self.assertIn('const request=++searchRequest', HTML)
        self.assertIn('if(request===searchRequest)renderResults(drugs)', HTML)
        self.assertIn('if(request===searchRequest)renderResults(d.drugs||[])', HTML)
        self.assertIn("if(!$('searchInput').value.trim()){doSearch('');return}", HTML)

    def test_scanner_updates_custom_clear_control(self):
        self.assertIn("$('searchInput').value=code;syncSearchClear();", HTML)
        self.assertIn('pharmacy-mobile-v6301', (ROOT/'sw.js').read_text())


if __name__ == '__main__':
    unittest.main()

# End of regression tests.
