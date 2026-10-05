# Vendored static files

Served from `/static/` so the app runs without a CDN (TDD Part 2, "Dependencies
and environment"). Downloaded once on 2026-10-03 (batch 3, PO-approved, Q11).
Update by downloading the new version and replacing the version, URL and sha256 here.

| File | Package | Version | Source | sha256 | Licence |
| --- | --- | --- | --- | --- | --- |
| htmx.min.js | htmx.org | 2.0.4 | https://cdn.jsdelivr.net/npm/htmx.org@2.0.4/dist/htmx.min.js | e209dda5c8235479f3166defc7750e1dbcd5a5c1808b7792fc2e6733768fb447 | 0BSD |
| pico.min.css | @picocss/pico | 2.0.6 | https://cdn.jsdelivr.net/npm/@picocss/pico@2.0.6/css/pico.min.css | dd5fd5591afd81ee21dcc117ad85c014dc3f1f19dc2d7b7d101ea0acc29274c2 | MIT |
| fonts/plex-sans.woff2 | IBM Plex Sans | 3.201 | https://raw.githubusercontent.com/google/fonts/main/ofl/ibmplexsans/IBMPlexSans%5Bwdth%2Cwght%5D.ttf (sha256 3b031aa4216174205bd8471f88a49b91f093169e9e87bd5262242bc5967fe2e3) | f2e77ead7ec26f6274b9c25139a4ebe998b9690ddccad1f3815d9738984ea6e2 | OFL-1.1 (fonts/OFL-IBMPlexSans.txt) |

`plex-sans.woff2` is the variable font pinned to normal width, weights 400 to 700 kept, and
subset to Latin, Latin-1, common punctuation, the minus sign and ₹ (U+20B9), with fontTools:

    fonttools varLib.instancer IBMPlexSans[wdth,wght].ttf wdth=100 wght=400:700 -o plex-inst.ttf
    pyftsubset plex-inst.ttf --unicodes="U+0020-007E,U+00A0-00FF,U+2010-2027,U+2030-203A,U+2190-2193,U+2212,U+20B9,U+2022,U+2026,U+00D7,U+2713,U+2715" \
      --layout-features="kern,liga,lnum,ccmp,locl" --flavor=woff2 --output-file=plex-sans.woff2

Plex's figures are tabular by default (every digit is 600 units wide), so amounts line up in columns.
