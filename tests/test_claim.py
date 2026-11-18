import asyncio
import base64
import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from PIL import Image
from claim import ClaimStore, BookIdentification, BookObservation, BookPriceCandidate, BookPriceExtraction, render_report
from pipeline import Pipeline, verified_prices, grounded_evidence


def jpeg():
    output = io.BytesIO()
    Image.new('RGB',(1000,500),'white').save(output,'JPEG')
    return base64.b64encode(output.getvalue()).decode()


class ClaimTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = ClaimStore(self.temp.name)
        self.frame = self.store.save_frame(jpeg())

    def tearDown(self):
        self.temp.cleanup()

    def book(self, **kwargs):
        payload = dict(kind='book', title='Visible title', bbox=[100,100,500,150],confidence=.95)
        payload.update(kwargs)
        return self.store.apply_observations(BookIdentification(observations=[BookObservation(**payload)]),self.frame)[0]

    def test_saved_evidence_and_unknowns(self):
        book = self.book()
        self.assertTrue((self.store.directory/book['frame_ref']).is_file())
        packet = self.store.finalize_packet()
        self.assertNotIn('spine_height_cm', book)
        self.assertNotIn('room', packet)
        self.assertEqual(packet['totals']['books_replacement_cost'],0)
        self.assertTrue(packet['review_queue'])
        self.assertEqual(json.loads((self.store.directory/'inventory.json').read_text())['sweep']['id'],self.store.id)

    def test_physical_duplicates_not_deduplicated_by_title(self):
        first = self.book()
        second = self.book()
        self.assertNotEqual(first['id'],second['id'])
        self.assertEqual(self.store.totals()['book_count'],2)
        self.store.correct(second['id'],'duplicate_of',first['id'])
        self.assertEqual(self.store.totals()['book_count'],1)

    def test_track_does_not_overwrite_correction(self):
        book = self.book()
        self.store.correct(book['id'],'title','User corrected title')
        self.store.apply_observations(BookIdentification(observations=[BookObservation(kind='book',existing_id=book['id'],title='Wrong replacement',bbox=[1,2,500,100],confidence=.9)]),self.frame)
        self.assertEqual(book['title'],'User corrected title')
        self.assertEqual(len(book['evidence']),2)
        self.assertEqual(len(self.store.data['corrections']),1)

    def test_locale_invalidates_prices(self):
        self.store.set_locale('United States','USD')
        book = self.book()
        book['replacement_cost'] = {'amount':19.99}
        self.store.set_locale('United Kingdom','GBP')
        self.assertIsNone(book['replacement_cost'])
        self.assertEqual(book['revision'],1)


    def test_appraisal_and_html_escaping(self):
        book = self.book(edition='Signed first edition',title='<script>alert(1)</script>')
        book['replacement_cost']={'amount':100}
        self.assertEqual(self.store.totals()['books_replacement_cost'],0)
        book['replacement_cost']=None
        report=render_report(self.store.finalize_packet(),'<script>bad</script>')
        self.assertNotIn('<script>',report)
        self.assertIn('&lt;script&gt;',report)

    def test_price_support(self):
        data=dict(valuation='replacement',amount=19.99,currency='USD',country='United States',source='Seller',url='https://seller.example/book',condition='new',quote='USD 19.99 new')
        extraction=BookPriceExtraction(prices=[BookPriceCandidate(**data)])
        evidence=[{'url':data['url'],'quote':data['quote']}]
        self.assertEqual(len(verified_prices(extraction,evidence,'United States','USD')),1)
        self.assertFalse(verified_prices(extraction,[],'United States','USD'))
        self.assertFalse(verified_prices(extraction,evidence,'United States','GBP'))
        extraction.prices[0].amount=99.99
        self.assertFalse(verified_prices(extraction,evidence,'United States','USD'))

    def test_invalid_frame_and_bbox(self):
        with self.assertRaises(Exception): self.store.save_frame(base64.b64encode(b'not jpeg').decode())
        result = self.store.apply_observations(BookIdentification(observations=[BookObservation(kind='book',bbox=[500,100,100,200],confidence=.9)]),self.frame)
        self.assertFalse(result)







class PipelineTests(unittest.IsolatedAsyncioTestCase):
    async def test_queued_frame_drop_and_finalization(self):
        with tempfile.TemporaryDirectory() as directory:
            store=ClaimStore(directory)
            emitted=[]
            async def emit(message): emitted.append(message)
            pipeline=Pipeline(None,store,emit)
            # More frames than the queue can hold must leave a review trail.
            for _ in range(3): await pipeline.submit_frame(jpeg())
            self.assertEqual(store.data['frames'][0]['status'],'not_processed')
            self.assertTrue(store.data['review_queue'])
            # A controlled fake model exercises workers and final artifact creation.
            async def generate(stage,contents,config):
                if stage=='identification': return SimpleNamespace(text=BookIdentification().model_dump_json())
                return SimpleNamespace(text='Unknown prices require review.')
            pipeline.generate=generate
            pipeline.start()
            await pipeline.finish()
            packet=json.loads((store.directory/'claim_packet.json').read_text())
            self.assertEqual(store.data['status'],'report_ready')
            self.assertEqual(set(packet), {'sweep','books','totals'})
            self.assertTrue((store.directory/'report.html').is_file())
            self.assertTrue(any('report_ready' in event for event in emitted))

    async def test_stale_price_does_not_overwrite_user_edit(self):
        with tempfile.TemporaryDirectory() as directory:
            store=ClaimStore(directory)
            store.set_locale('United States','USD')
            frame=store.save_frame(jpeg())
            book=store.apply_observations(BookIdentification(observations=[BookObservation(kind='book',title='Before',bbox=[0,0,100,100],confidence=.9)]),frame)[0]
            async def emit(message): pass
            pipeline=Pipeline(None,store,emit)
            entered=asyncio.Event()
            release=asyncio.Event()
            async def generate(stage,contents,config):
                entered.set(); await release.wait()
                return SimpleNamespace(text='No results',candidates=[])
            pipeline.generate=generate
            worker=asyncio.create_task(pipeline.price_worker())
            pipeline.enqueue_price(book)
            await entered.wait()
            store.correct(book['id'],'title','After')
            release.set()
            await pipeline.prices.join()
            worker.cancel(); await asyncio.gather(worker,return_exceptions=True)
            self.assertEqual(book['title'],'After')
            self.assertIsNone(book['replacement_cost'])


if __name__=='__main__': unittest.main()
