from __future__ import annotations

import re


def _parse_flowchart(content: str) -> str | None:
    """Parse a flowchart/graph mermaid block and return a natural-language summary."""
    node_labels: dict[str, str] = {}
    edges: list[tuple[str, str]] = []

    # Extract node labels: A[Label], A(Label), A{Label}
    node_pattern = re.compile(r'\b(\w+)\s*[\[\({]\s*([^\]\)\}]+?)\s*[\]\)\}]')
    for match in node_pattern.finditer(content):
        node_id, label = match.group(1), match.group(2)
        node_labels[node_id] = label

    # Extract edges: A --> B, A --- B, A -.-> B, A ==> B
    # Also handle node definitions inline: A[Label] --> B[Label]
    # Also handle edge labels: A -->|text| B
    edge_pattern = re.compile(
        r'\b(\w+)\s*(?:[\[\({][^\]\)\}]*[\]\)\}])?\s*'
        r'(?:-->|---|-.->|==>)'
        r'(?:\|[^|]*\|)?\s*(\w+)'
    )
    for match in edge_pattern.finditer(content):
        src, dst = match.group(1), match.group(2)
        edges.append((src, dst))

    if not edges:
        return None

    sentences = []
    for src, dst in edges:
        src_label = node_labels.get(src, src)
        dst_label = node_labels.get(dst, dst)
        sentences.append(f"{src_label} connects to {dst_label}")

    return ". ".join(sentences) + "."


def _parse_sequence(content: str) -> str | None:
    """Parse a sequenceDiagram mermaid block and return a natural-language summary."""
    sentences = []

    # Match: Source->>Target: message  (send)  or  Source-->>Target: reply
    send_pattern = re.compile(r'^\s*(\w+)->>(\w+)\s*:\s*(.+)$', re.MULTILINE)
    reply_pattern = re.compile(r'^\s*(\w+)-->>(\w+)\s*:\s*(.+)$', re.MULTILINE)

    # Collect all matches with their positions so we can sort by position
    matches: list[tuple[int, str]] = []

    for m in send_pattern.finditer(content):
        src, dst, msg = m.group(1), m.group(2), m.group(3).strip()
        matches.append((m.start(), f"{src} sends {msg} to {dst}"))

    for m in reply_pattern.finditer(content):
        src, dst, msg = m.group(1), m.group(2), m.group(3).strip()
        matches.append((m.start(), f"{src} replies {msg} to {dst}"))

    matches.sort(key=lambda x: x[0])
    sentences = [text for _, text in matches]

    if not sentences:
        return None

    return ". ".join(sentences) + "."


def _summarize_mermaid(block_content: str) -> str | None:
    """Given the raw mermaid diagram content, return a natural-language summary or None."""
    stripped = block_content.strip()
    first_line = stripped.split('\n')[0].strip().lower()

    if first_line.startswith('graph') or first_line.startswith('flowchart'):
        return _parse_flowchart(stripped)
    elif first_line == 'sequencediagram':
        return _parse_sequence(stripped)

    return None


def enrich_mermaid_blocks(text: str) -> str:
    """Find all fenced mermaid code blocks and append natural-language summaries.

    For recognized diagram types (graph/flowchart, sequenceDiagram), appends
    '\\n\\nDiagram: {summary}' after the closing fence. Unrecognized types are
    left unchanged.
    """
    pattern = re.compile(r'(```mermaid\s*\n(.*?)```)', re.DOTALL)

    def replace_block(match: re.Match) -> str:
        full_block = match.group(1)
        content = match.group(2)
        summary = _summarize_mermaid(content)
        if summary is None:
            return full_block
        return full_block + f"\n\nDiagram: {summary}"

    return pattern.sub(replace_block, text)
