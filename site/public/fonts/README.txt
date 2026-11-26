Fonts on this site

Alegreya 2.008 (Regular, Italic, Bold, ExtraBold)
  Source: https://github.com/huertatipografica/Alegreya, tag v2.008, fonts/webfonts/
  Licence: SIL Open Font License 1.1, OFL-Alegreya.txt

Alegreya Sans 2.008 (Regular, Italic, Bold)
  Source: https://github.com/huertatipografica/Alegreya-Sans, tag v2.008, fonts/webfonts/
  Licence: SIL Open Font License 1.1, OFL-AlegreyaSans.txt

Neither licence declares a Reserved Font Name.

The files here are the official woff2 files, cut down to the Latin characters
(the same range font services call "latin", plus the arrows U+2190-2199).
Every OpenType feature is kept. The command, run once per file with fontTools 4.46:

  python3 -m fontTools.subset IN.woff2 --flavor=woff2 --layout-features='*' \
    --unicodes="U+0000-00FF,U+0131,U+0152-0153,U+02BB-02BC,U+02C6,U+02DA,U+02DC,U+0304,U+0308,U+0329,U+2000-206F,U+20AC,U+2122,U+2190-2199,U+2212,U+2215,U+FEFF,U+FFFD" \
    --output-file=OUT.woff2

SHA-256 of the official files before the cut:
  df48af9e17d325cbdbe0340e9e7ce3eaf6e70d31749323b7e79f71cc4237de21  Alegreya-Regular.woff2
  113874ad4686813249555a974e2e78c5988fd46e3331823d7e9d300744a1ecc6  Alegreya-Italic.woff2
  5043b0e4261f2947c3a86cd5239cbb6996c28fdc2042dca396eabe18f8a6ba3a  Alegreya-Bold.woff2
  4665599f3d5efff1d287f3424a7b9f4b7fa2f1f329d7b7c9bbd9faa0f105a42b  Alegreya-ExtraBold.woff2
  073e58748f8b928f28f9ee5de0ae74be3a24779e0eadf396397a2e25ea24e90b  AlegreyaSans-Regular.woff2
  ae286475e6057faafff2e2b8067f2915ef1c89b13560718b732e8b8e2b1253bf  AlegreyaSans-Italic.woff2
  b4053b913910a5e8b3706235ee2a80a2374f4f8f69641a57b2ec0abcc7a587cf  AlegreyaSans-Bold.woff2
