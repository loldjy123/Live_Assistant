"""Package only public frontend assets for GitHub Pages; never publish Python or .env."""
import json
import os
import shutil
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent.parent


def build(destination=None):
    destination = Path(destination) if destination else ROOT / '_site'
    destination.mkdir(parents=True, exist_ok=True)
    for name in ['index.html', 'app.js', 'processor.js', 'site-config.js']:
        shutil.copy2(ROOT / name, destination / name)
    backend = os.environ.get('BACKEND_URL', '').strip()
    if backend:
        parsed = urlsplit(backend)
        if parsed.scheme != 'https' or not parsed.netloc or parsed.username or parsed.password:
            raise ValueError('BACKEND_URL must be a public HTTPS URL without credentials')
        (destination / 'site-config.js').write_text(
            'window.LIBRARY_CONFIG = ' + json.dumps({'backendUrl':backend}) + ';\n',
            encoding='utf-8',
        )
    (destination / '.nojekyll').touch()
    print('Packaged public assets; hosted backend configured:', bool(backend))
    return destination


if __name__ == '__main__':
    build()
