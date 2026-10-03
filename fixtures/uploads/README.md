# Uploads

Files a person uploads on /add (CHG-007). `scripts/make_fixtures.py` generated them; every value in them is fictional. The demo's fixture AI recognises each one by the sha256 of its bytes and answers from the hand-written replies in `fixtures/ai_replies.json`.

| File | What it is |
| --- | --- |
| ap-2610-131-photo.png | A photo of Ashirwad's invoice AP/2610/131. The same invoice also arrives by email (`test_inbox/08`), so the second copy becomes a duplicate, not a second bill |
| handwritten-bill-ganesh.png | Shree Ganesh Hardware's bill 418, ₹12,390. A clean italic rendering stands in for handwriting; real handwriting belongs to Phase 9's eval set |
| voice-note-ashirwad.wav | Half a second of silence. Its canned reply is the Hinglish transcript ("... dedh lakh rupaye ..."). Only an authorised live run tests real audio |

## GSTINs

The fixture GSTINs are fictional. Their PAN part starts `ZZZ`, and their check character is computed with GSTN's mod-36 scheme (`app/validate/gstin.py`). That scheme is pinned by the GST portal's published sample `27AAPFU0939F1ZV` in `tests/test_validate_gstin.py`.

| Party | GSTIN |
| --- | --- |
| Ashirwad Paper Suppliers | 27ZZZFZ0001Z1ZU |
| Kaveri Traders | 29ZZZCZ0002Z1ZV |
| Prime Chem Industries | 24ZZZPZ0003Z1ZD |
| Saraswati Precision Works (the business) | 27ZZZCZ0004Z1ZX |
| Shree Ganesh Hardware | 27ZZZPZ0005Z1Z5 |
