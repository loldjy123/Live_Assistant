import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from jsonschema import ValidationError
from pydantic import ValidationError as ModelValidationError

import claim
from claim import ClaimStore, BookIdentification, BookObservation, render_report
from test_claim import jpeg


class BookOnlyOutputTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = ClaimStore(self.temp.name)
        self.store.set_locale('United States', 'USD')
        self.frame = self.store.save_frame(jpeg())

    def observe(self, **fields):
        data = dict(kind='book', title='Readable title', bbox=[0,0,500,100], confidence=.95)
        data.update(fields)
        return self.store.apply_observations(
            BookIdentification.model_validate({'observations': [data]}), self.frame
        )

    def test_book_schema_rejects_other_object_types(self):
        with self.assertRaises(ModelValidationError):
            BookObservation(kind='furniture', bbox=[0,0,500,100], confidence=.9)
        schema = BookObservation.model_json_schema()
        self.assertEqual(schema['properties']['kind']['const'], 'book')

    def test_mixed_frame_keeps_books_and_discards_non_books(self):
        result = BookIdentification.model_validate({'observations': [
            {'kind': 'book', 'title': 'Readable book', 'bbox': [0,0,500,100], 'confidence': .9},
            {'kind': 'furniture', 'title': 'Chair'},
        ]})
        self.store.apply_observations(result, self.frame)
        self.assertEqual([book['title'] for book in self.store.books()], ['Readable book'])

    def test_correction_tool_uses_book_id(self):
        import main
        correction = next(tool for tool in main.TOOLS if tool.name == 'record_correction')
        self.assertIn('book_id', correction.parameters.properties)
        self.assertNotIn('item_id', correction.parameters.properties)
        book = self.observe()[0]
        self.store.correct(book_id=book['id'], field='title', value='Corrected title')
        self.assertEqual(self.store.get_book(book['id'])['title'], 'Corrected title')

    def packet(self):
        self.store.finalize_packet()
        self.store.data['status'] = 'report_ready'
        return claim.build_output_packet(self.store.data)

    def price(self, amount):
        return dict(amount=amount, currency='USD', country='United States', source='Test seller',
                    url='https://example.com/book', retrieved_at='2026-11-16T00:00:00+00:00',
                    condition_assumed='new', quote=f'USD {amount}', match_notes='Test fixture')

    def test_non_books_discarded_but_unreadable_books_counted(self):
        self.assertFalse(self.observe(kind='item', title='Shelving'))
        self.assertFalse(self.observe(kind='furniture', title='Chair'))
        self.observe(title='')
        packet = self.packet()
        self.assertEqual(packet['totals']['book_count'],1)
        self.assertEqual(packet['totals']['books_unidentified'],1)
        self.assertEqual(len(packet['books']),0)
        self.assertNotIn('review_queue',packet)
        self.assertTrue(self.store.data['review_queue'])
        self.observe(title='Identified title')
        packet = self.packet()
        self.assertEqual(len(packet['books']),1)
        self.assertNotIn('room',packet)
        self.assertNotIn('items',packet)
        self.assertNotIn('dimensions_cm',packet['books'][0])
        self.assertIsNone(packet['books'][0]['spine_height_cm'])
        self.assertIsNone(packet['books'][0]['spine_thickness_cm'])
        self.assertIsNone(packet['totals']['shelf_run_m'])
        self.assertEqual(set(packet), {'sweep','books','totals'})
        self.assertIsNone(packet['books'][0]['replacement_cost'])

    def test_decimal_totals_and_partial_prices(self):
        first = self.observe()[0]
        second = self.observe(title='Second copy')[0]
        third = self.observe(title='Unknown price')[0]
        first['replacement_cost'] = self.price(.1)
        first['used_value'] = self.price(.05)
        second['replacement_cost'] = self.price(.2)
        packet = self.packet()
        self.assertEqual(packet['totals']['books_replacement_cost'],.3)
        self.assertEqual(packet['totals']['books_used_value'],.05)
        self.assertNotIn('books_priced',packet['totals'])
        self.assertEqual(self.store.totals()['books_priced'],1)
        self.assertEqual(packet['totals']['book_count'],3)
        self.assertEqual(packet['totals']['excluded_from_totals'],1)
        report = render_report(packet)
        self.assertIn('Replacement total: 0.3 USD',report)
        self.assertNotIn('Dimensions',report)

    def test_duplicate_does_not_inflate_count_or_prices(self):
        first = self.observe()[0]
        duplicate = self.observe(possible_duplicate_of=first['id'])[0]
        duplicate['replacement_cost']=self.price(100)
        packet=self.packet()
        self.assertEqual(packet['totals']['book_count'],1)
        self.assertEqual(packet['totals']['books_replacement_cost'],0)

    def test_schema_is_loaded_and_enforced(self):
        self.observe()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'edited_schema.json'
            schema=json.loads(claim.SCHEMA_PATH.read_text())
            schema['required'].append('my_new_required_field')
            path.write_text(json.dumps(schema))
            with patch.object(claim,'SCHEMA_PATH',path):
                with self.assertRaises(ValidationError):self.packet()

    def test_unknown_books_and_review_queue_are_not_in_report(self):
        self.observe(title='')
        self.observe(title='Visible known title')
        packet = self.packet()
        self.assertEqual([book['title'] for book in packet['books']], ['Visible known title'])
        report = render_report(packet)
        self.assertNotIn('Review queue', report)
        self.assertNotIn('Unidentified book', report)
        self.assertIn('1 of 2 detected', report)
        self.assertIn('1 detected books had unreadable titles', report)

    def test_untitled_book_price_does_not_enter_totals(self):
        book = self.observe(title='   ')[0]
        book['replacement_cost'] = self.price(99)
        packet = self.packet()
        self.assertEqual(packet['books'], [])
        self.assertEqual(packet['totals']['books_replacement_cost'], 0)

    def test_measurement_tools_are_removed(self):
        import main
        names={tool.name for tool in main.TOOLS}
        self.assertNotIn('measure_shelving',names)
        self.assertNotIn('set_room_dimensions',names)
        self.assertFalse(hasattr(self.store,'calibrate'))


if __name__=='__main__':unittest.main()
