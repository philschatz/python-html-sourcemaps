# Install

1. run `npm install` to get the source-map pretty-printer
1. run `./test` which generates `out.html` and `out.html.map`
1. run `$(npm bin)/sourcemap-lookup out.html:${LINE}:${COLUMN}` to specify the line/column in the output file and see the line/column in the input file


# TODO

- [ ] load an input sourcemap file and rewire to use it when generating the output
  - This would allow showing the CNXML source file (since sourcemaps support multiple source files)
- [ ] pythonify the ported code


# Screenshots

The "console-GUI" tool that showcases that the sourcemaps are working takes an output file and output line/column information and shows the line/column in the source file. Since this code does not really manipulate the DOM much it is not terribly interesting but here goes:

```
$ sourcemap-lookup out.html:1:0

Original Position:
	input.html, Line 1:0

Code Section:
1>| <html>
2 |   <body>
3 |     <!-- Here is a comment that is only in the input file (dunno why) -->
4 |     <div id="id123"></div>
5 |   </body>
6 | </html>
```

```
$ sourcemap-lookup out.html:4:6

Original Position:
	input.html, Line 4:4

Code Section:
1 | <html>
2 |   <body>
3 |     <!-- Here is a comment that is only in the input file (dunno why) -->
4>|     <div id="id123"></div>
        ^
5 |   </body>
6 | </html>
7 |
```
