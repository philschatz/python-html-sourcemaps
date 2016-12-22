#!/usr/bin/env python
"""Use baker from command line."""
from __future__ import print_function

import argparse
import logging
import sys
import contextlib

# Force python XML parser not faster C accelerators
# because we can't hook the C implementation
sys.modules['_elementtree'] = None
import xml.etree as etree
import xml.etree.ElementTree as ET
from xml.etree.ElementTree import QName, Comment, ProcessingInstruction


def adjust_pos(line_num, column_num, str):
    """ Keeps track of the line/column when serializing
        This is used for the output sourcemap file
    """
    lines = str.splitlines()
    line_num += len(lines)
    column_num = len(lines[:1]) + 1 # Columns are 1-based???
    return (line_num, column_num)


class LineNumberingParser(ET.XMLParser):
    """ Record the line and column numbers for elements (to create a sourcemap later)
    TODO: also record line/column information for attribute names, values, and text nodes
          because they can come from different places (different XML files, CSS recipe files)
    """
    def _start_list(self, *args, **kwargs):
        # Here we assume the default XML parser which is expat
        # and copy its element position attributes into output Elements
        element = super(self.__class__, self)._start_list(*args, **kwargs)
        print("open", self.parser.CurrentLineNumber, self.parser.CurrentColumnNumber)
        element._start_line_number = self.parser.CurrentLineNumber
        element._start_column_number = self.parser.CurrentColumnNumber
        element._start_byte_index = self.parser.CurrentByteIndex
        return element

    def _end(self, *args, **kwargs):
        element = super(self.__class__, self)._end(*args, **kwargs)
        print("close", self.parser.CurrentLineNumber, self.parser.CurrentColumnNumber)
        element._end_line_number = self.parser.CurrentLineNumber
        element._end_column_number = self.parser.CurrentColumnNumber
        element._end_byte_index = self.parser.CurrentByteIndex
        return element


# Ported from https://github.com/mozilla/source-map/blob/master/lib/base64-vlq.js

# A single base 64 digit can contain 6 bits of data. For the base 64 variable
# length quantities we use in the source map spec, the first bit is the sign,
# the next four bits are the actual value, and the 6th bit is the
# continuation bit. The continuation bit tells us whether there are more
# digits in this value following this digit.
#
#   Continuation
#   |    Sign
#   |    |
#   V    V
#   101011
VLQ_BASE_SHIFT = 5
# binary: 100000
VLQ_BASE = 1 << VLQ_BASE_SHIFT
# binary: 011111
VLQ_BASE_MASK = VLQ_BASE - 1
# binary: 100000
VLQ_CONTINUATION_BIT = VLQ_BASE

def toVLQSigned(aValue):
  """
   Converts from a two-complement value to a value where the sign bit is
   placed in the least significant bit.  For example, as decimals:
     1 becomes 2 (10 binary), -1 becomes 3 (11 binary)
     2 becomes 4 (100 binary), -2 becomes 5 (101 binary)
  """
  # return aValue < 0
  #   ? ((-aValue) << 1) + 1
  #   : (aValue << 1) + 0
  return ((-aValue) << 1) + 1 if aValue < 0 else (aValue << 1) + 0


def fromVLQSigned(aValue):
  """
   Converts to a two-complement value from a value where the sign bit is
   placed in the least significant bit.  For example, as decimals:
     2 (10 binary) becomes 1, 3 (11 binary) becomes -1
     4 (100 binary) becomes 2, 5 (101 binary) becomes -2
  """
  isNegative = (aValue & 1) == 1
  shifted = aValue >> 1
  return -shifted if isNegative else shifted


# From http://stackoverflow.com/a/30238073
def rshift(val, n):
    s = val & 0x80000000
    for i in range(0,n):
        val >>= 1
        val |= s
    return val

def base64VLQ_encode(aValue):
  """
   Returns the base 64 VLQ encoded value.
  """
  encoded = ""
  digit

  vlq = toVLQSigned(aValue)

  condition = True
  while condition:
    digit = vlq & VLQ_BASE_MASK
    # vlq >>>= VLQ_BASE_SHIFT
    vlq = rshift(vlq, VLQ_BASE_SHIFT)
    if (vlq > 0):
      # There are still more digits in this value, so we must make sure the
      # continuation bit is marked.
      # digit |= VLQ_CONTINUATION_BIT
      digit = digit | VLQ_CONTINUATION_BIT

    encoded += base64.encode(digit)
    condition = (vlq > 0)

  return encoded


# def base64VLQ_decode(aStr, aIndex, aOutParam):
# """
#  Decodes the next base 64 VLQ value from the given string and returns the
#  value and the rest of the string via the out parameter.
# """
#   strLen = aStr.length
#   result = 0
#   shift = 0
#   continuation, digit
#
#   do:
#     if (aIndex >= strLen):
#       throw new Error("Expected more digits in base 64 VLQ value.")
#
#     digit = base64.decode(aStr.charCodeAt(aIndex++))
#     if (digit == -1):
#       throw new Error("Invalid base64 digit: " + aStr.charAt(aIndex - 1))
#
#     continuation = !!(digit & VLQ_CONTINUATION_BIT)
#     digit &= VLQ_BASE_MASK
#     result = result + (digit << shift)
#     shift += VLQ_BASE_SHIFT
#    while (continuation)
#
#   aOutParam.value = fromVLQSigned(result)
#   aOutParam.rest = aIndex




@contextlib.contextmanager
def _get_writer(file_or_filename, encoding):
    # returns text write method and release all resources after using
    try:
        write = file_or_filename.write
    except AttributeError:
        # file_or_filename is a file name
        if encoding == "unicode":
            file = open(file_or_filename, "w")
        else:
            file = open(file_or_filename, "w", encoding=encoding,
                        errors="xmlcharrefreplace")
        with file:
            yield file.write
    else:
        # file_or_filename is a file-like object
        # encoding determines if it is a text or binary writer
        if encoding == "unicode":
            # use a text writer as is
            yield write
        else:
            # wrap a binary writer with TextIOWrapper
            with contextlib.ExitStack() as stack:
                if isinstance(file_or_filename, io.BufferedIOBase):
                    file = file_or_filename
                elif isinstance(file_or_filename, io.RawIOBase):
                    file = io.BufferedWriter(file_or_filename)
                    # Keep the original file open when the BufferedWriter is
                    # destroyed
                    stack.callback(file.detach)
                else:
                    # This is to handle passed objects that aren't in the
                    # IOBase hierarchy, but just have a write method
                    file = io.BufferedIOBase()
                    file.writable = lambda: True
                    file.write = write
                    try:
                        # TextIOWrapper uses this methods to determine
                        # if BOM (for UTF-16, etc) should be added
                        file.seekable = file_or_filename.seekable
                        file.tell = file_or_filename.tell
                    except AttributeError:
                        pass
                file = io.TextIOWrapper(file,
                                        encoding=encoding,
                                        errors="xmlcharrefreplace",
                                        newline="\n")
                # Keep the original file open when the TextIOWrapper is
                # destroyed
                stack.callback(file.detach)
                yield file.write

def _escape_cdata(text):
    # escape character data
    try:
        # it's worth avoiding do-nothing calls for strings that are
        # shorter than 500 character, or so.  assume that's, by far,
        # the most common case in most applications.
        if "&" in text:
            text = text.replace("&", "&amp;")
        if "<" in text:
            text = text.replace("<", "&lt;")
        if ">" in text:
            text = text.replace(">", "&gt;")
        return text
    except (TypeError, AttributeError):
        _raise_serialization_error(text)

def _escape_attrib(text):
    # escape attribute value
    try:
        if "&" in text:
            text = text.replace("&", "&amp;")
        if "<" in text:
            text = text.replace("<", "&lt;")
        if ">" in text:
            text = text.replace(">", "&gt;")
        if "\"" in text:
            text = text.replace("\"", "&quot;")
        # The following business with carriage returns is to satisfy
        # Section 2.11 of the XML specification, stating that
        # CR or CR LN should be replaced with just LN
        # http://www.w3.org/TR/REC-xml/#sec-line-ends
        if "\r\n" in text:
            text = text.replace("\r\n", "\n")
        if "\r" in text:
            text = text.replace("\r", "\n")
        #The following four lines are issue 17582
        if "\n" in text:
            text = text.replace("\n", "&#10;")
        if "\t" in text:
            text = text.replace("\t", "&#09;")
        return text
    except (TypeError, AttributeError):
        _raise_serialization_error(text)

def _namespaces(elem, default_namespace=None):
    # identify namespaces used in this tree

    # maps qnames to *encoded* prefix:local names
    qnames = {None: None}

    # maps uri:s to prefixes
    namespaces = {}
    if default_namespace:
        namespaces[default_namespace] = ""

    def add_qname(qname):
        # calculate serialized qname representation
        try:
            if qname[:1] == "{":
                uri, tag = qname[1:].rsplit("}", 1)
                prefix = namespaces.get(uri)
                if prefix is None:
                    prefix = _namespace_map.get(uri)
                    if prefix is None:
                        prefix = "ns%d" % len(namespaces)
                    if prefix != "xml":
                        namespaces[uri] = prefix
                if prefix:
                    qnames[qname] = "%s:%s" % (prefix, tag)
                else:
                    qnames[qname] = tag # default element
            else:
                if default_namespace:
                    # FIXME: can this be handled in XML 1.0?
                    raise ValueError(
                        "cannot use non-qualified names with "
                        "default_namespace option"
                        )
                qnames[qname] = qname
        except TypeError:
            _raise_serialization_error(qname)

    # populate qname and namespaces table
    for elem in elem.iter():
        tag = elem.tag
        if isinstance(tag, QName):
            if tag.text not in qnames:
                add_qname(tag.text)
        elif isinstance(tag, str):
            if tag not in qnames:
                add_qname(tag)
        elif tag is not None and tag is not Comment and tag is not PI:
            _raise_serialization_error(tag)
        for key, value in elem.items():
            if isinstance(key, QName):
                key = key.text
            if key not in qnames:
                add_qname(key)
            if isinstance(value, QName) and value.text not in qnames:
                add_qname(value.text)
        text = elem.text
        if isinstance(text, QName) and text.text not in qnames:
            add_qname(text.text)
    return qnames, namespaces


def write(root_node, file_or_filename,
          encoding=None,
          xml_declaration=None,
          default_namespace=None,
          method=None,
          short_empty_elements=True):
    """Write element tree to a file as XML.
    Arguments:
      *file_or_filename* -- file name or a file object opened for writing
      *encoding* -- the output encoding (default: US-ASCII)
      *xml_declaration* -- bool indicating if an XML declaration should be
                           added to the output. If None, an XML declaration
                           is added if encoding IS NOT either of:
                           US-ASCII, UTF-8, or Unicode
      *default_namespace* -- sets the default XML namespace (for "xmlns")
      *method* -- either "xml" (default), "html, "text", or "c14n"
      *short_empty_elements* -- controls the formatting of elements
                                that contain no content. If True (default)
                                they are emitted as a single self-closed
                                tag, otherwise they are emitted as a pair
                                of start/end tags
    """
    method = "xml"
    if not encoding:
        # if method == "c14n":
        #     encoding = "utf-8"
        # else:
        #     encoding = "us-ascii"
        encoding = "unicode"
    enc_lower = encoding.lower()
    with _get_writer(file_or_filename, enc_lower) as write:
        if method == "xml" and (xml_declaration or
                (xml_declaration is None and
                 enc_lower not in ("utf-8", "us-ascii", "unicode"))):
            declared_encoding = encoding
            if enc_lower == "unicode":
                # Retrieve the default encoding for the xml declaration
                import locale
                declared_encoding = locale.getpreferredencoding()
            write("<?xml version='1.0' encoding='%s'?>\n" % (
                declared_encoding,))
        if method == "text":
            _serialize_text(write, root_node)
        else:
            qnames, namespaces = _namespaces(root_node, default_namespace)
            serialize = _serialize_xml
            pos = (0, 0)
            serialize(write, root_node, qnames, namespaces, pos,
                      short_empty_elements=short_empty_elements)


def _serialize_xml(write, elem, qnames, namespaces, pos,
                   short_empty_elements, **kwargs):

    def __writer(pos, node, text):
        (line_num, column_num) = pos
        pos = adjust_pos(line_num, column_num, text)
        # TODO: Print to the sourcemapper
        print("serialize", node._start_line_number, node._start_column_number)

        write(text)
        return pos

    def __writer_end(pos, node, text):
        """ used for close tags """
        (line_num, column_num) = pos
        pos = adjust_pos(line_num, column_num, text)
        # TODO: Print to the sourcemapper
        print("serializeEnd", node._end_line_number, node._end_column_number)
        write(text)
        return pos

    tag = elem.tag
    text = elem.text
    if tag is Comment:
        pos = __writer(pos, elem, "<!--%s-->" % text)
    elif tag is ProcessingInstruction:
        pos = __writer(pos, elem, "<?%s?>" % text)
    else:
        tag = qnames[tag]
        if tag is None:
            if text:
                pos = __writer(pos, elem, _escape_cdata(text))
            for e in elem:
                _serialize_xml(write, e, qnames, None, pos,
                               short_empty_elements=short_empty_elements)
        else:
            pos = __writer(pos, elem, "<" + tag)
            items = list(elem.items())
            if items or namespaces:
                if namespaces:
                    for v, k in sorted(namespaces.items(),
                                       key=lambda x: x[1]):  # sort on prefix
                        if k:
                            k = ":" + k
                        pos = __writer(pos, elem, " xmlns%s=\"%s\"" % (
                            k,
                            _escape_attrib(v)
                            ))
                for k, v in sorted(items):  # lexical order
                    if isinstance(k, QName):
                        k = k.text
                    if isinstance(v, QName):
                        v = qnames[v.text]
                    else:
                        v = _escape_attrib(v)
                    pos = __writer(pos, elem, " %s=\"%s\"" % (qnames[k], v))
            if text or len(elem) or not short_empty_elements:
                pos = __writer(pos, elem, ">")
                if text:
                    pos = __writer(pos, elem, _escape_cdata(text))
                for e in elem:
                    _serialize_xml(write, e, qnames, None, pos,
                                   short_empty_elements=short_empty_elements)
                pos = __writer_end(pos, elem, "</" + tag + ">")
            else:
                pos = __writer_end(pos, elem, " />")
    if elem.tail:
        pos = __writer(pos, elem, _escape_cdata(elem.tail))



def convert_file(html_in, html_out, source_map, source_map_input):
    # html_parser = etree.HTMLParser(encoding="utf-8")
    html_parser = LineNumberingParser(encoding="utf-8")
    html_doc = ET.parse(html_in, html_parser)
    # # html_doc = etree.XML(html_in.read(), html_parser)
    # oven = Oven(css_in, use_repeatable_ids)
    # oven.bake(html_doc, last_step)

    # serialize out HTML
    # print(etree.tostring(html_doc, method="html"), file=html_out)
    write(html_doc.getroot(), html_out)


def main(argv=None):
    """Commandline script wrapping Baker."""
    parser = argparse.ArgumentParser(description="Process raw HTML to baked"
                                                 " (embedded numbering and"
                                                 " collation)")
    parser.add_argument("html_in",
                        type=argparse.FileType('r'),
                        help="raw HTML file to bake (default stdin)",
                        default=sys.stdin)
    parser.add_argument("html_out",
                        type=argparse.FileType('w'),
                        help="baked HTML file output (default stdout)",
                        default=sys.stdout)
    parser.add_argument('--source-map-input', metavar='html.map',
                        type=argparse.FileType('r'),
                        help="HTML Sourcemap file if it exists ")
    parser.add_argument('--source-map', metavar='output.map',
                        type=argparse.FileType('w'),
                        help="HTML Output Sourcemap file")
    parser.add_argument('-d', '--debug', action='store_true',
                        help='Send debugging info to stderr')
    args = parser.parse_args(argv)

    convert_file(args.html_in, args.html_out, args.source_map, args.source_map_input)


if __name__ == "__main__":
    main(sys.argv[1:])
