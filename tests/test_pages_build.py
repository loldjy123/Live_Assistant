import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.build_pages import build


class PagesBuildTests(unittest.TestCase):
    def test_only_public_assets_are_packaged(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict(os.environ, {'BACKEND_URL':'https://api.example.com'}):
                target = build(directory)
            self.assertEqual({p.name for p in target.iterdir()},
                {'index.html','app.js','processor.js','site-config.js','.nojekyll'})
            self.assertIn('https://api.example.com',(target/'site-config.js').read_text())
            self.assertFalse((target/'.env').exists())
            self.assertFalse((target/'main.py').exists())

    def test_backend_url_cannot_embed_a_secret(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict(os.environ, {'BACKEND_URL':'https://user:secret@api.example.com'}):
                with self.assertRaises(ValueError):build(directory)


if __name__=='__main__':unittest.main()
