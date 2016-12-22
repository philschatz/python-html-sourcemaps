# Install

1. run `npm install` to get the source-map pretty-printer
1. run `./test` which generates `out.html` and `out.html.map`
1. run `$(npm bin)/sourcemap-lookup out.html:${LINE}:${COLUMN}` to specify the line/column in the output file and see the line/column in the input file


# TODO

- [ ] load an input sourcemap file and rewire to use it when generating the output
  - This would allow showing the CNXML source file (since sourcemaps support multiple source files)
- [ ] pythonify the ported code
