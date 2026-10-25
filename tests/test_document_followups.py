"""Optional reader diagnostics stay useful within the parent's bounded error fields."""

import pytest

from outlook_mcp.errors import OutlookMCPError
from outlook_mcp.tools import mail_attachment_read
from tests.test_readable_attachments import ARGS, graph, pdf


async def test_many_blank_pages_report_total_and_explicit_sample_omission():
    sdk, _ = graph(pdf("Synthetic", *([None] * 151)), "blank-pages.pdf", "application/pdf")
    result = await mail_attachment_read.read_attachment(sdk, **ARGS)
    warning = result["warnings"][0]
    assert len(warning) < 300
    assert "151 pages" in warning and "143 more omitted" in warning
    assert "[2, 3, 4, 5, 6, 7, 8, 9]" in warning


async def test_parser_refusal_prints_the_download_remedy_once():
    sdk, _ = graph(pdf("Synthetic", password="synthetic"), "locked.pdf", "application/pdf")
    with pytest.raises(OutlookMCPError) as error:
        await mail_attachment_read.read_attachment(sdk, **ARGS)
    assert str(error.value).lower().count("download") == 1
