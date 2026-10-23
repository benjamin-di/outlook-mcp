"""Plain text as HTML, and a reply's text above the quote (``tools/_mail_body.py``).

Graph's ``comment`` joins a multi-line text's lines with spaces on an HTML message, and
``message.body`` drops the quoted original (checked against an Exchange Online mailbox),
so reply and forward text is converted here and patched into the draft Graph quoted.
"""

from __future__ import annotations

from types import SimpleNamespace

from msgraph.generated.models.body_type import BodyType

from outlook_mcp.tools._mail_body import above_quote, text_to_html

# The quote a createReply draft carries: Outlook's header block below an <hr>.
_HTML_DRAFT = (
    '<html><head><meta http-equiv="Content-Type" content="text/html; charset=utf-8"></head>'
    '<body><hr tabindex="-1" style="display:inline-block; width:98%">'
    '<div id="divRplyFwdMsg" dir="ltr"><b>From:</b> Sender &lt;sender@example.com&gt;</div>'
    "<div><p>The <b>original</b> message.</p></div></body></html>"
)
# The same for a plain-text original: a line break, a rule, the header block.
_TEXT_DRAFT = (
    "\r\n________________________________________\r\n"
    "From: Sender <sender@example.com>\r\nSubject: Plans\r\n\r\nThe original message.\r\n"
)


def _draft(content, content_type=BodyType.Html):
    return SimpleNamespace(content=content, content_type=content_type)


class TestTextToHtml:
    def test_paragraphs_line_breaks_and_lists_survive(self):
        text = (
            "First paragraph line one.\nFirst paragraph line two.\n\nSecond paragraph.\n\n"
            "- bullet one\n- bullet two\n\n**bold** text"
        )

        assert text_to_html(text) == (
            "<p>First paragraph line one.<br>First paragraph line two.</p>"
            "<p>Second paragraph.</p>"
            "<ul><li>bullet one</li><li>bullet two</li></ul>"
            "<p>**bold** text</p>"
        )

    def test_everything_is_escaped(self):
        assert text_to_html('Use <b>x</b> & "y"\n- a <i>') == (
            "<p>Use &lt;b&gt;x&lt;/b&gt; &amp; &quot;y&quot;</p><ul><li>a &lt;i&gt;</li></ul>"
        )

    def test_crlf_and_cr_line_endings(self):
        assert text_to_html("a\r\nb\r\n\r\nc\rd") == "<p>a<br>b</p><p>c<br>d</p>"

    def test_a_line_of_spaces_still_separates_paragraphs(self):
        assert text_to_html("a\n \t\nb\n\n\n\nc") == "<p>a</p><p>b</p><p>c</p>"

    def test_a_list_can_follow_and_precede_text_without_a_blank_line(self):
        assert text_to_html("Items:\n  * one\n  - two\nThat's all.") == (
            "<p>Items:</p><ul><li>one</li><li>two</li></ul><p>That&#x27;s all.</p>"
        )

    def test_only_a_marker_and_a_space_make_an_item(self):
        text = "-- \nA signature\n-1 degrees\n*not a list*\n- \n*"

        assert text_to_html(text) == (
            "<p>--<br>A signature<br>-1 degrees<br>*not a list*<br>-<br>*</p>"
        )

    def test_trailing_spaces_go_and_nothing_is_nothing(self):
        assert text_to_html("a  \n- b  ") == "<p>a</p><ul><li>b</li></ul>"
        assert text_to_html("") == ""
        assert text_to_html("\n \n") == ""


class TestAboveQuote:
    def test_plain_text_goes_into_an_html_draft_as_html_right_after_body(self):
        body = above_quote(_draft(_HTML_DRAFT), "Thanks.\nSee you\n\n- at 10", is_html=False)

        assert body.content_type == BodyType.Html
        assert body.content == _HTML_DRAFT.replace(
            "<body>", "<body><p>Thanks.<br>See you</p><ul><li>at 10</li></ul>"
        )

    def test_html_goes_in_as_written(self):
        body = above_quote(_draft(_HTML_DRAFT), "<p>Thanks, <b>see you</b>.</p>", is_html=True)

        assert body.content_type == BodyType.Html
        assert body.content == _HTML_DRAFT.replace("<body>", "<body><p>Thanks, <b>see you</b>.</p>")

    def test_the_body_tag_is_found_whatever_its_case_and_attributes(self):
        body = above_quote(_draft('<HTML><BODY class="x" lang=en>quoted</BODY></HTML>'), "n", False)

        assert body.content == '<HTML><BODY class="x" lang=en><p>n</p>quoted</BODY></HTML>'

    def test_a_draft_with_no_body_tag_gets_the_text_in_front(self):
        assert above_quote(_draft("<div>quoted</div>"), "n", False).content == (
            "<p>n</p><div>quoted</div>"
        )

    def test_plain_text_stays_plain_text_on_a_plain_text_draft(self):
        body = above_quote(_draft(_TEXT_DRAFT, BodyType.Text), "Thanks.\nSee you\n\n- at 10", False)

        assert body.content_type == BodyType.Text
        # The draft's own CRLF, then Graph's quote unchanged: its opening line
        # break makes the one blank line.
        assert body.content == "Thanks.\r\nSee you\r\n\r\n- at 10\r\n" + _TEXT_DRAFT

    def test_a_plain_text_quote_without_a_leading_break_still_gets_a_blank_line(self):
        body = above_quote(_draft("> quoted\n", BodyType.Text), "Thanks.\r\n\r\n", False)

        assert body.content == "Thanks.\n\n> quoted\n"

    def test_html_on_a_plain_text_draft_makes_it_html_with_the_quote_escaped(self):
        body = above_quote(
            _draft("From: a <a@example.com>\r\nquoted line", BodyType.Text), "<p>n</p>", True
        )

        assert body.content_type == BodyType.Html
        assert body.content == "<p>n</p><br>From: a &lt;a@example.com&gt;<br>quoted line"

    def test_an_empty_draft_body_is_just_the_new_text(self):
        assert above_quote(None, "<p>n</p>", True).content == "<p>n</p>"
        assert above_quote(None, "n", False).content == "<p>n</p>"
        assert above_quote(_draft("", BodyType.Text), "<p>n</p>", True).content == "<p>n</p>"
        text = above_quote(_draft("", BodyType.Text), "a\nb\n", False)
        assert (text.content, text.content_type) == ("a\nb", BodyType.Text)
