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

## P26 phase A: contextual suggestions, citations and event feedback

The 2026-09-28 phase A extends the `eb51c42` baseline using the same DOU-Synapse revision above.
The inspected reference patterns are `course-nav.tsx`, `transcript-parts.tsx`, `source-card.tsx`,
`campus-motion.tsx`, `globals.css`, and the source-context page. Their navigation feedback, reading
hierarchy and exact-quotation structure are adapted to native DOM and Nabız tokens. No Synapse colour,
React, Tailwind, GSAP, additional stylesheet, external font or dependency is introduced.

[context_chips.js](../../src/nabiz/console/static/js/context_chips.js) offers at most three controls from
the latest assistant turn. It waits for deferred card controls, clears detached/history turns, and
leaves existing consent handlers in charge. Following a topic fills the draft without submitting it.
The route offer receives focus; the map and calendar suggestions invoke the original card button.
The calendar button still requires its separate confirmation before publishing an action.

[citation_card.js](../../src/nabiz/console/static/js/citation_card.js) builds one inert element tree for
DOM `textContent` rendering and the existing escaped-string answer renderer. Quotations remain exact
server strings, source links require HTTPS, and quoted passages already shown above are linked rather
than duplicated. The first two citations remain open; additional sources use native `details`.
Unique answer-local fragment IDs connect E63 sentence support, quotations and source cards. Missing
support and conflicting evidence retain explicit text, with neutral or amber styling. Emergency
payloads bypass the citation renderer for every mode. Existing refusal wording is unchanged.

Freshness formatting reuses Nabız's existing helpers. This section supersedes the earlier paragraph's
blanket amber/critical-red styling: recorded badges are neutral, noncritical source errors are amber,
and old page evidence retains its confirmation notice. Freshness badges retain the design language's
one-pixel boundary; ordinary type badges are borderless. The inherited current-data label and single
fresh-dot beat remain governed by the existing contract rather than being applied to recorded pages.

Navigation, message, card and disclosure feedback stays in the citizen stylesheets. Event markers
are removed on animation completion or after 400 ms. Saved conversations do not receive message/card
entry markers. New rules animate only transform/opacity, inside both the system preference media
query and the explicit reduced-motion/simple-mode guard. The measured composer height reserves
keyboard focus space. The conversation rail uses a container query to keep the delete control below
narrow titles; this does not modify the P02 stylesheet or storage code.

### Phase A copy check

The added static-file lines, including the two new modules, were compared against all 15 supplied
CSS/TS/TSX/JS reference copies, line by line and as six-word lexical shingles. Exact matches are only
language scaffolding (`}`, `});`, `return true;`, `return;`, `return null;`, `try {`, `} catch {`)
and the standard `@supports (animation-timeline: scroll())` declaration. The matching six-word sequences
are generic border/colour declarations, opacity/translate entry syntax, and the standard scroll
timeline/range declaration. Inspection found no distinctive copied source lines. Existing attribution
headers remain; new files take structural ideas only and need no additional copied-code NOTICE entry.

### Precedence decisions

The card contract and NABIZ-DILI take priority over the brief, its supplement and general skills.
The brief's explicit entry markers take precedence over the supplement's CSS-only entry suggestion.
The supplement's animated background colour becomes an immediate hover colour and a guarded transform.
Reduced motion remains fully still; the Apple skill's optional fade and spring libraries are not used.
The T06 borderless badge suggestion applies to type labels, while freshness badges retain the higher
priority one-pixel boundary. Irreversible deletion retains its design-language danger outline.
The existing fixed refusal copy and current-data wording are preserved by their locked contracts;
new suggestion and recorded-source copy does not introduce them.

### User reference refinement

The later Microsoft/Copilot reference sets compact work-surface proportions, while the supplied
İBB screenshots retain the civic blue palette, light surfaces and quiet Istanbul photograph.
The existing self-hosted Nabız Sans face is restored only on the citizen page, with regular body
text and semibold headings. This follows the existing K5 font decision without adding a font asset.
Hero text is 28–36 px, ordinary headings 19–22 px and body text 16 px at the normal text setting;
the user's larger-text preference still scales all of them. The user's compactness request replaces
the earlier oversized hero spacing, without reducing disclosure text or 44 px touch targets.

The five supplied UX rules map to available-only contextual suggestions, one primary ask action,
quiet secondary actions and native disclosures for optional detail and additional sources.
Existing legacy quick suggestions still submit immediately; changing their owner files is recorded
in the handoff. Zero-minimum grid tracks keep source answers within the phone viewport; the citizen
agency-card override allows its official link to wrap at enlarged text sizes without clipping it.

The return link reuses the existing Asistan/Assistant navigation label and shared translation key;
this follows the user’s one-intent/one-label rule and avoids a second name for the same destination.
