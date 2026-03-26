from __future__ import annotations

from html.parser import HTMLParser


class HtmlTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        if data.strip():
            self.parts.append(data.strip())

    def text(self) -> str:
        return "\n".join(self.parts)


def html_to_text(html: str) -> str:
    parser = HtmlTextExtractor()
    parser.feed(html)
    return parser.text().strip()
