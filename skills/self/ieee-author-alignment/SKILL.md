---
name: ieee-author-alignment
description: Fix IEEE conference LaTeX template author-block alignment problems. Use this skill whenever the user mentions IEEE template author alignment, misaligned authors, uneven author columns, IEEEtran \author blocks, \IEEEauthorblockN, \IEEEauthorblockA, confusing \and placement, or wanting 2-per-row or 3-per-row author layouts in an IEEE paper. This skill is especially useful for papers with 4, 5, 6, or more authors where long affiliations make the default template look unbalanced.
---

# IEEE Author Alignment

Use this skill to diagnose and fix author alignment issues in IEEE conference
LaTeX templates that use `\IEEEauthorblockN`, `\IEEEauthorblockA`, and `\and`.

The common failure mode is that authors are written in natural source order:
`1 2 3 4 5 6`, with `\and` between every author. For long author names or
affiliations, IEEEtran may produce visibly uneven columns. The reliable fix is
to choose the layout that matches the intended visual rows:

- For a two-column author area, arrange the source by columns rather than by
  reading order.
- For a three-authors-per-row layout, keep natural source order and insert a
  custom `\linebreakand` command where a new author row should begin.

## Source Note

This skill was distilled from a CSDN article by
`野指针小李`:
https://blog.csdn.net/qq_35357274/article/details/126585041

The CSDN note's core lesson is:

- For six authors, change source order from `1 2 3 4 5 6` to `1 3 5 \and 2 4 6`.
- Remove the original `\and` commands between every author.
- Add line breaks between stacked authors inside each column.
- Keep only one `\and` between the left and right columns.

This skill also includes the three-authors-per-row approach from a Zhihu answer
by `我是一个工具人`:
https://www.zhihu.com/question/352144429/answer/1835338678

That approach defines a `\linebreakand` command around IEEEtran's internal
`@IEEEauthorhalign` environment, then uses normal `\and` within a row and
`\linebreakand` between author rows.

## When Editing A Paper

1. Read the target `.tex` file and locate the complete `\author{...}` block.
2. Identify each author unit as one `\IEEEauthorblockN{...}` followed by its
   matching `\IEEEauthorblockA{...}`.
3. Preserve the exact content of every author name, affiliation, email, ORCID,
   footnote marker, and macro.
4. Decide whether the requested output is a two-column layout or a
   three-authors-per-row layout. If the user says "3 per row", "three authors
   in one line", "first row has 3 authors", or similar, use the
   `\linebreakand` method.
5. Modify only the author layout and the required preamble helper macro unless
   the user explicitly requests broader changes.
6. Do not compile TeX unless the user explicitly asks. If validation is needed,
   inspect the edited source structure first.

## Six-Author Fix

For six authors, build two vertical columns while preserving visual reading
order by rows:

```text
Left source column:   author 1, author 3, author 5
Right source column:  author 2, author 4, author 6
Visual rows:          1-2, 3-4, 5-6
```

Use this LaTeX structure:

```tex
\author{
% Author 1
\IEEEauthorblockN{...}
\IEEEauthorblockA{...} \\

% Author 3
\IEEEauthorblockN{...}
\IEEEauthorblockA{...} \\

% Author 5
\IEEEauthorblockN{...}
\IEEEauthorblockA{...}
\and
% Author 2
\IEEEauthorblockN{...}
\IEEEauthorblockA{...} \\

% Author 4
\IEEEauthorblockN{...}
\IEEEauthorblockA{...} \\

% Author 6
\IEEEauthorblockN{...}
\IEEEauthorblockA{...}
}
```

The line break after each author block stacks authors inside a column. The
single `\and` switches from the left source column to the right source column.

## Three-Authors-Per-Row Fix

Use this method when the desired visual layout is three authors on the first
row and the remaining authors on a following row, for example `1 2 3` on the
first row and `4 5` on the second row.

Add this helper macro in the preamble after `\documentclass[conference]{IEEEtran}`
and before `\author{...}`:

```tex
\makeatletter
\newcommand{\linebreakand}{%
  \end{@IEEEauthorhalign}
  \hfill\mbox{}\par
  \mbox{}\hfill\begin{@IEEEauthorhalign}
}
\makeatother
```

Then keep the author source in natural reading order. Use normal `\and` between
authors on the same row, and replace the row-breaking `\and` with
`\linebreakand`.

For five authors as `3 + 2`, use this structure:

```tex
\author{
% Author 1
\IEEEauthorblockN{...}
\IEEEauthorblockA{...}
\and
% Author 2
\IEEEauthorblockN{...}
\IEEEauthorblockA{...}
\and
% Author 3
\IEEEauthorblockN{...}
\IEEEauthorblockA{...}
\linebreakand
% Author 4
\IEEEauthorblockN{...}
\IEEEauthorblockA{...}
\and
% Author 5
\IEEEauthorblockN{...}
\IEEEauthorblockA{...}
}
```

For six authors as `3 + 3`, use:

```text
1 \and 2 \and 3 \linebreakand 4 \and 5 \and 6
```

For more authors, insert `\linebreakand` after every third author when the
venue permits a three-per-row layout:

```text
9 authors:  1 \and 2 \and 3 \linebreakand 4 \and 5 \and 6 \linebreakand 7 \and 8 \and 9
```

Prefer this method over manual spacing commands such as repeated `\hspace`,
`\vspace`, or ad hoc `minipage` blocks because it works with IEEEtran's
author-alignment machinery instead of bypassing it.

## General Rule

For an even number of authors that should appear as two balanced columns:

1. Split authors by visual row position.
2. Put odd-indexed authors in the first source column.
3. Put even-indexed authors in the second source column.
4. Insert `\\` after every author block except the last author in each column.
5. Insert one `\and` between the two source columns.

Examples:

```text
4 authors:  1 3 \and 2 4
6 authors:  1 3 5 \and 2 4 6
8 authors:  1 3 5 7 \and 2 4 6 8
```

For an odd number of authors, keep the columns as balanced as possible and ask
whether the user wants the final author centered, kept in the shorter right
column, or moved to a separate final line if the venue template permits it.

If the user specifically wants three authors per line, do not use the
odd/even-column reordering rule. Use `\linebreakand` and keep the authors in
natural source order.

## Validation Checklist

Before returning the edited file, verify the source by inspection:

- The `\author{...}` block still has balanced braces.
- Every original author block is still present exactly once.
- There is only one `\and` for the two-column fix.
- `\\` appears between stacked authors inside a column, not after the final
  author in a column.
- For the three-authors-per-row fix, `\linebreakand` is defined once in the
  preamble and used only where a new author row should begin.
- For the three-authors-per-row fix, normal `\and` remains between authors on
  the same row.
- No title, abstract, keywords, body text, bibliography, or package imports
  were changed unless requested.

## Response Format

When reporting the fix to the user, keep the answer brief:

```text
已处理 IEEE 作者对齐问题：将作者块从自然顺序改为列优先顺序，并只在两列之间保留一个 \and。
验证：作者数量未变，\author 块括号配平，未改动正文内容。
```

For the three-authors-per-row fix:

```text
已处理 IEEE 作者排版：新增 \linebreakand，并在需要换到下一行作者的位置使用它；同一行作者之间仍使用 \and。
验证：作者数量未变，\author 块括号配平，未改动正文内容。
```
