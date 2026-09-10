# BSD 2-Clause License
#
# Copyright (c) 2026, Renaud Allard <renaud@allard.it>
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#
# 1. Redistributions of source code must retain the above copyright notice, this
#    list of conditions and the following disclaimer.
#
# 2. Redistributions in binary form must reproduce the above copyright notice,
#    this list of conditions and the following disclaimer in the documentation
#    and/or other materials provided with the distribution.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
# AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
# DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE
# FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
# DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
# SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
# CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
# OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
# OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

"""Regenerate the brand icons from the Home Connect application icon.

    python tools/make_icons.py tmp/xapk/icon.png

Home Assistant serves an integration's icons out of home-assistant/brands, and
falls back to a `brand` directory in the integration itself for one that is
not listed there. Both want the same square icon at two sizes, so both are
made by scaling the application icon and nothing else is invented.

There is no logo pair. A logo is a wordmark, the application icon is a square
mark, and inventing a wordmark out of one would be making up a thing that does
not exist rather than shipping the thing that does.

Needs Pillow, which the integration itself does not.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image

BRAND = Path("custom_components/homeconnect/brand")

# What home-assistant/brands asks for: the icon at its own size and again at
# twice it, both square.
SIZES = {"icon.png": 256, "icon@2x.png": 512}


def main(source: Path) -> int:
    icon = Image.open(source).convert("RGBA")
    if icon.width != icon.height:
        print(f"{source} is {icon.width}x{icon.height} and an icon is square")
        return 1
    BRAND.mkdir(parents=True, exist_ok=True)
    for name, size in SIZES.items():
        scaled = icon.resize((size, size), Image.Resampling.LANCZOS)
        scaled.save(BRAND / name, optimize=True)
        print(f"wrote {BRAND / name} at {size}x{size}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        raise SystemExit(2)
    raise SystemExit(main(Path(sys.argv[1])))
