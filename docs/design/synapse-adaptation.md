# DOU-Synapse chat adaptation

The citizen answer surface uses the reading hierarchy and source-card composition inspected in DOU-Synapse. The reference checkout reported revision `2cbe1eab8ab46c5958f4d529cb9a32c0b6bb2169` during the 2026-09-26 review. Its stored screenshots `docs/images/ui-2026-09-16/03-course-chat.png` and `04-citation-context.png` were reviewed as historical visual references, not as captures of the running Nabız application.

## Source components

Paths below are relative to the DOU-Synapse repository:

- `apps/web/components/chat/transcript-parts.tsx`: right-aligned question bubble, plain assistant reading flow, multiline composer, and suggestion rows.
- `apps/web/components/source-card.tsx`: a quiet card with a source header, exact quotation, location badge, and source-context link.
- `apps/web/app/courses/[courseId]/chat/page.tsx`: transcript and composer in one reading column, with evidence directly after the answer.
- `apps/web/components/chat-feedback.tsx`: inline feedback below the relevant answer.

## Native adaptation

[answer_card.css](../../src/nabiz/console/static/css/answer_card.css) removes the enclosing answer box and its decorative arrival stripe. The assistant's response and numbered steps use a left-aligned reading column. Quotes retain their own bordered surface with a distinct header and readable source footer. Source records use soft cards with the institution or source link beside the existing freshness label; the layout stacks on narrow screens.

Nabız's existing markup, data fields, exact quotations, date labels, official links, fixed refusal text, and feedback contracts remain unchanged. Recorded data retains its amber status, old evidence retains its confirmation notice, and error notices retain their red semantic colour. Unknown evidence remains explicitly labelled rather than gaining a misleading current-data style.

The CSS uses Nabız's own colour tokens and the platform-native system font. It introduces no React, Next.js, Tailwind, external font, dependency, network call, or copied course-specific behaviour. The answer has no nested entrance animation; transcript motion remains owned by the existing page rules. Token-based surfaces follow the current theme, and high-contrast and forced-colour borders remain explicit.

The visual adaptation does not transfer DOU-Synapse course roles, PDF page numbering, document telemetry, or learning-event collection into the citizen service. Composer behaviour and question-bubble styling are owned by the citizen page rather than this stylesheet.

## Licence notice

The referenced DOU-Synapse components are distributed under the following licence, retained here for the adaptation:

```text
MIT License

Copyright (c) 2026 Muratcan Ates

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

## Copy check

The adaptation takes the layout idea, not source lines. On 2026-09-27 the lines this revision adds under
`src/nabiz/console/static/` were compared with every `.css`, `.ts`, `.tsx` and `.js` file under DOU-Synapse
`apps/web/` at the revision above, line by line and as six-token shingles. The only matches were generic
(`@media (prefers-reduced-motion: reduce) {`, `@media (min-width: 1024px) {`, `event.preventDefault();` and a
`border: 1px solid var(--border)` surface rule); DOU-Synapse styles with Tailwind utility classes, which this
page does not use.
