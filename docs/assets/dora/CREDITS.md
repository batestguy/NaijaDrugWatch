# Images: what each one is, where it came from, and what may be done with it

**Fetched 2026-11-13 from Wikimedia Commons.** Each licence below was read from that file's own record
on Commons (the MediaWiki `imageinfo`/`extmetadata` fields the file page renders), not from a search
result or a summary. The raw responses are kept beside this file in `licences.json`.

Only **one portrait** exists in this project. The masthead mark, the wide band and the footer mark are
three crops of that single photograph: this is a tribute built from one face, not a gallery. The three
statue photographs were licence-checked; **one** is used, on the About page.

| file in this folder | what it shows | size | bytes |
|---|---|---|---|
| `dora-portrait.jpg` | the portrait, cropped, for the masthead and the About page | 480x600 | 51,941 |
| `dora-band.jpg` | a wide horizontal crop of the same portrait, for the band | 640x305 | 23,153 |
| `dora-mark.jpg` | a square crop of the same portrait, for the footer | 220x220 | 6,983 |
| `dora-monument.jpg` | a photograph of the memorial to her at Ezinano, Agulu | 480x776 | 56,023 |

**Total: 138,100 bytes (134.9 KB).** The build refuses to publish if the four files ever total more
than 400 KB (`IMAGE_BUDGET_BYTES` in `scripts/build_site.py`).

## 1. The portrait: CC0, National Library of Nigeria

- File page: https://commons.wikimedia.org/wiki/File:Prof._Dora_Akunyili_(Hon._Minister_of_Information_Communication_2008_-_2010).jpg
- Author as recorded on the file: *Unknown author*, credited to the **National Library of Nigeria**
- Licence: **CC0 1.0** (public domain dedication), https://creativecommons.org/publicdomain/zero/1.0/
- Original: 750x903, 67,802 bytes. Changes: cropped (the white border and the printed caption band at
  the foot are excluded), resized, re-encoded as JPEG.

CC0 asks for no attribution. It is given on every page that shows a crop, and here, because the
institution that holds the photograph should be named anyway. The National Library of Nigeria is also
the institution whose repository supplies the biographical facts on the About page.

## 2. The memorial: CC BY-SA 4.0, Chiinobis

- File page: https://commons.wikimedia.org/wiki/File:DoraAkunyili_Monument_at_Ezinano_Agulu.jpg
- Author: **Chiinobis** (uploader, "own work")
- Licence: **CC BY-SA 4.0**, https://creativecommons.org/licenses/by-sa/4.0/
- Original: 1903x3075, 862,768 bytes. Changes: cropped and resized.

Attribution and the licence link are printed under the photograph on `about.html`. A crop is an
adaptation, so **this crop is offered under CC BY-SA 4.0 as well**. That share-alike applies to the
photograph; it does not reach the price data, which is CC-BY-4.0.

## 3. Two further statue photographs: licence checked, not used

Both carry **CC BY-SA 4.0** and are reusable, but they are not on either page: three photographs of
statues beside one portrait would read as a gallery, and one photograph of the memorial is enough.

- `File:DoraAkunyili Monument at Ezinano Agulu.jpg` is the one used (above).
- `File:Late Prof Dora Akunyili.jpg` - 948x1852, 291,779 bytes, author **Mercyjamb123**, CC BY-SA 4.0,
  https://commons.wikimedia.org/wiki/File:Late_Prof_Dora_Akunyili.jpg
- `File:Dora Nkem Akunyili OFR was the Director-General of National Agency for Food and Drug
  Administration and Control.jpg` - 695x1084, 736,539 bytes, author **Adimora chidinma**, CC BY-SA
  4.0, https://commons.wikimedia.org/wiki/File:Dora_Nkem_Akunyili_OFR_was_the_Director-General_of_National_Agency_for_Food_and_Drug_Administration_and_Control.jpg
  (The brief gave this title truncated as "Dora Nkem Akunyili OFR ... .jpg"; the full title is above.)

## What is deliberately not here

No press photograph, no screenshot, no image taken from a news page, and no photograph whose licence
could not be read. If a licence is unclear, the image does not go on the page.

## Provenance

The originals were downloaded to a temporary directory and are **not** committed: they total about
1.9 MB and nothing needs them once the crops exist. Every one can be re-fetched from the file page URL
above. The exact metadata Commons returned for each, including the licence fields quoted here, is in
`licences.json` in this folder.
