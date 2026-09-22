"""Pins this test suite to the pocketsphinx provider regardless of the
app's real default (faster_whisper, see app/config.py). pocketsphinx is the
only provider that runs fully offline -- pinning it here is what keeps
`pytest` runnable in network-restricted environments (this project's own
dev sandbox included) without silently masking a real faster-whisper bug:
faster-whisper's own code path is exercised manually per README section 5.4,
not by this automated suite. Must run before `app.main` (and therefore its
module-level provider construction) is ever imported, which is why this
lives in conftest.py rather than a fixture.
"""
import os

os.environ.setdefault("PROVIDER", "pocketsphinx")
