"""A tiny HTML DOM parser built on stdlib html.parser.

Provides just enough of a query API (find by tag/class, attribute access,
text extraction) to write readable scrapers without third-party deps.
"""
from __future__ import annotations

import html
import re
from html.parser import HTMLParser


class Node:
    __slots__ = ("tag", "attrs", "children", "parent", "text")

    def __init__(self, tag: str, attrs: dict, parent: "Node | None"):
        self.tag = tag
        self.attrs = attrs
        self.children: list["Node"] = []
        self.parent = parent
        self.text = ""

    def get(self, key: str, default: str | None = None):
        return self.attrs.get(key, default)

    def classes(self) -> set[str]:
        c = self.attrs.get("class", "")
        return set(c.split()) if c else set()

    def has_class(self, *names: str) -> bool:
        cs = self.classes()
        return all(n in cs for n in names)

    def find_all(self, tag: str | None = None, class_: str | tuple | None = None, attrs: dict | None = None, depth: int = 100) -> list["Node"]:
        out: list[Node] = []
        self._walk(tag, class_, attrs, depth, out)
        return out

    def _walk(self, tag, class_, attrs, depth, out):
        if depth <= 0:
            return
        for child in self.children:
            ok = True
            if tag is not None and child.tag != tag:
                ok = False
            if ok and class_ is not None:
                cs = child.classes()
                if isinstance(class_, (tuple, list)):
                    if not any(c in cs for c in class_):
                        ok = False
                elif class_ not in cs:
                    ok = False
            if ok and attrs:
                for k, v in attrs.items():
                    if child.get(k) != v:
                        ok = False
                        break
            if ok:
                out.append(child)
            child._walk(tag, class_, attrs, depth - 1, out)

    def find(self, tag: str | None = None, class_: str | None = None, attrs: dict | None = None) -> "Node | None":
        found = self.find_all(tag, class_, attrs, depth=50)
        return found[0] if found else None

    def find_parent(self, tag: str | None = None, class_: str | None = None) -> "Node | None":
        p = self.parent
        while p is not None:
            ok = True
            if tag is not None and p.tag != tag:
                ok = False
            if ok and class_ is not None and class_ not in p.classes():
                ok = False
            if ok:
                return p
            p = p.parent
        return None

    def get_text(self, strip: bool = True) -> str:
        buf = [self.text]
        for c in self.children:
            buf.append(c.get_text(strip=False))
        txt = "".join(buf)
        txt = html.unescape(txt)
        txt = re.sub(r"\s+", " ", txt)
        return txt.strip() if strip else txt

    def __repr__(self) -> str:  # pragma: no cover
        return f"<{self.tag} class={self.attrs.get('class', '')!r} text={self.text[:30]!r}>"


class _Parser(HTMLParser):
    VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link",
            "meta", "param", "source", "track", "wbr"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = Node("#root", {}, None)
        self.stack = [self.root]

    def handle_starttag(self, tag, attrs):
        node = Node(tag, dict(attrs), self.stack[-1])
        self.stack[-1].children.append(node)
        if tag not in self.VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        node = Node(tag, dict(attrs), self.stack[-1])
        self.stack[-1].children.append(node)

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].tag == tag:
                del self.stack[i:]
                break

    def handle_data(self, data):
        if self.stack:
            self.stack[-1].text += data


def parse(html_text: str) -> Node:
    p = _Parser()
    try:
        p.feed(html_text)
    except Exception:
        pass
    p.close()
    return p.root
