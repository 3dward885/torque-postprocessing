"""Withdrawn widgets reproduce continuous input without desktop interaction."""
import copy
import tkinter as tk
import unittest
from unittest.mock import patch

import test_treated_plots as fixtures
from app import App
from io_profiles import read_raw
from output_settings import default_output, accepted_output
from installation_check import check_output_typing


class OutputTypingTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.TreatedPlotTests()
        self.fixture.setUp()
        self.root = tk.Tk()
        self.root.withdraw()
        self.errors = []
        self.root.report_callback_exception = lambda kind, error, trace: self.errors.append(str(error))
        self.app = App(self.root)
        raw = read_raw(self.fixture.raw)
        choice = {**default_output(raw.sha256, self.fixture.raw), **fixtures.MASS}
        key = self.app.add_record(self.fixture.raw, raw, self.fixture.result['config'],
                                  output=accepted_output(choice, raw.sha256, self.fixture.result))
        self.app.records[key]['result'] = self.fixture.result
        self.app.files.selection_set(key)
        self.app.refresh_selected()
        self.root.update()

    def tearDown(self):
        self.app.output.cancel()
        self.app.close()
        self.fixture.tearDown()

    def test_continuous_entry_and_preview_guard(self):
        check_output_typing(self.app, self.root)
        self.assertFalse(self.errors)
        self.assertEqual(self.root.state(), 'withdrawn')

    def test_apply_commits_once_cancel_restores_and_invalid_draft_stays_editable(self):
        panel = self.app.output
        record = self.app.selected()
        result = copy.deepcopy(record['result'])
        entry = panel.entries['mass_mg']
        entry.delete(0, 'end')
        entry.insert(0, 'NaN')
        panel.apply_button.invoke()
        self.assertTrue(panel.dirty)
        self.assertIn('positive finite', panel.note.get())
        entry.delete(0, 'end')
        for char in '0.235':
            entry.insert('insert', char)
            self.root.update()
        with patch('app.run_entry', side_effect=AssertionError('Apply refitted data')):
            panel.apply_button.invoke()
        self.assertFalse(panel.dirty)
        self.assertEqual(record['output']['mass_mg'], '0.235')
        self.assertEqual(record['result'], result)
        entry.delete(0, 'end')
        entry.insert(0, '9')
        panel.cancel_button.invoke()
        self.assertEqual(entry.get(), '0.235')
        self.assertFalse(self.errors)


if __name__ == '__main__':
    unittest.main()
