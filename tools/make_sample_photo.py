"""Creates the sample's "client-supplied" product photo with OpenAI, once.

In a real engagement this file comes from the client's photo shoot. For the
sample it was generated, and the README says so. Committed, so nobody else
needs a key to use it.
"""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from studio import config  # noqa: E402
from studio.providers.openai_provider import OpenAIProvider  # noqa: E402

config.load_env()
prompt = (
    "Professional product photograph from a brand photo shoot. A slim frosted coral-coloured spray "
    "bottle of SPF 50 sunscreen mist with a navy blue cap stands upright on smooth warm sand at golden "
    "hour, soft long shadows, the sea softly out of focus behind. The bottle has a minimal label with "
    "the lowercase word 'solvane' in small navy letters. Wide shot: the bottle is small in the frame, "
    "standing slightly left of centre and a little below the middle, taking up only about a quarter of "
    "the image height, with lots of calm sky above and sand around it. Photorealistic, premium, "
    "no other text, no people."
)
img = OpenAIProvider().generate_image(prompt, 1536, 0, {})
out = Path(__file__).resolve().parent.parent / "samples/long-light/assets/daylight-mist.png"
img.save(out)
print(out, img.size)
