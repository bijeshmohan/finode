IBM Plex Sans and IBM Plex Mono, by Mike Abbink and Bold Monday for IBM (https://github.com/IBM/plex).
Licensed under the SIL Open Font License 1.1: https://openfontlicense.org
Source: https://github.com/google/fonts/tree/main/ofl/ibmplexsans and .../ofl/ibmplexmono (served here so the app does not
depend on a third party for its look)

ibm-plex-sans.woff2: cut with fontTools from IBMPlexSans[wdth,wght].ttf, pinned to width 100 with weight 400-700 kept variable.
ibm-plex-mono-medium.woff2 / -semibold.woff2: IBMPlexMono-Medium.ttf and -SemiBold.ttf, for amounts and the big figures.
All three: the Latin range plus the rupee sign (U+20B9), no hinting (pyftsubset --flavor=woff2 --no-hinting).
