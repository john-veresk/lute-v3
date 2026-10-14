# Translation with local Codex CLI

Codex is the only translation source; languages no longer use dictionary websites.
In **Settings → Languages → Edit**, set **Translate into** (Russian by default), and choose
a **Codex model** from the suggestions or enter a model ID. Leave the model
blank to use the CLI's configured default. Save the language and reload the book.
**Reasoning effort** can use the CLI setting or override it for this language.
Known models show only the effort levels supported in the local CLI cache.
**Fast mode** requests priority processing when checked; unchecked uses standard
processing, overriding the CLI's service tier. Availability and increased usage
depend on the selected model and your account. Both options apply to words,
phrases, sentences and pages.
**Show translation timer** displays elapsed request time beside the model in the
Codex panel, including waiting for the result. It stops when the response is
ready or fails. Uncheck it to hide the timer for that language.

Clicking a word or selecting a phrase opens its term card. Codex is part of the
card, without separate tabs or a divider: it translates the term using the sentence
from the book and shows its main
common meanings with brief explanations and the dictionary form. There is no fixed
number of options: words with one main meaning show one, while words with several
also show common meanings outside the sentence's context. Synonyms are grouped
within a meaning, and rare senses are not added just to lengthen the list. The best
meaning fills an empty Translation field automatically. Click another meaning to select
it, then press **Save** at the bottom of the card to store it in your vocabulary.
Saved translations and text typed while a request is running are preserved.

Every term translation from Codex is kept in a translation store in the Lute
database, one entry per word or phrase. Opening a term with a stored translation
shows it immediately, marked **saved** beside the model, even if the term card
already exists. An empty **Translation** field otherwise starts Codex
automatically, regardless of whether the word or phrase already has a database
record or is marked as known. Whitespace alone counts as empty. If **Translation**
is filled and nothing is stored, opening the term does not start a translation.
The ↻ icon at the top right of the card always asks Codex again and replaces the
stored translation. Phrase suggestions stored from another sentence are shown
only if they occur in the current one.

Sentence and page translation commands also use Codex. The image icon beside ↻
opens the Bing image search inside the card.

For an unambiguous inflected word, Codex also adds the dictionary headword to
**Parents** automatically: an infinitive for a verb, nominative singular for a
noun, or the language's standard base form. Expand the collapsed **Parent**
section to choose from the headword's main common dictionary meanings without a
fixed number of options, each with a brief
explanation. For example, `halusi` can have
`хотела`, while its parent `haluta` has `хотеть`. The parent and its translation
are saved together with the child when you press **Save**. Looking up a word
alone does not create vocabulary. Existing parent translations are kept until
you explicitly choose a different dictionary meaning;
that change is saved with the child. Existing parents and
parents changed or removed while the lookup was running are preserved. If the
grammar is uncertain, Codex leaves Parents alone.

When you click a single word with sentence context, **Phrases**
can suggest up to three useful phrases or collocations from nearby words, with
translations. Each phrase contains the clicked word and is copied from the
sentence. Check phrases to save them together with the term when you press
**Save**: one click creates the word card, its parent and the checked phrases.
Press **Add** to save a phrase at once. Phrase checkboxes start unchecked;
nothing is saved until you choose it. Phrase cards are separate terms from the clicked word,
and reading highlights refresh after saving. Existing translations, parents and
learning statuses are preserved. The section stays hidden when there is no
useful phrase, no sentence context, or you selected several words.

For a phrase with 2–40 distinct words, **Words** shows individual word
cards, translations and any inflected words' base forms. Use **Add** on one
card, or select checkboxes and press **Add selected**. These buttons save
the selected word cards to the Lute vocabulary immediately, independently of
saving the complete phrase, and refresh reading highlights. Existing word
translations, parents and learning statuses are preserved; missing translations
are filled. New inflected cards also get a parent with its dictionary meaning.
Words are taken from Lute's language parser; the CLI must translate those exact
words and cannot add invented words to this list.

Install and log into Codex CLI on the computer running the Lute server:

```sh
codex login
```

The server must find `codex` on its PATH. If needed, set `LUTE_CODEX_CLI` to the
absolute executable path before starting Lute. A Docker installation needs the
CLI and its authentication inside the container; it cannot execute the host CLI.
The CLI uses your existing Codex account and sends the selected text and sentence
to its model provider. It is a local CLI integration, not offline inference.

Lute invokes `codex exec` in an empty temporary directory with a read-only
sandbox, ephemeral sessions, disabled shell/web search, and a JSON output schema.
The CLI's user configuration and authentication are reused. Each request has a
90-second timeout. Two translations can run concurrently; the bounded queue and
one-hour in-memory cache avoid repeated calls for the same term, context, target
language, model, reasoning effort and Fast mode. Changing either option starts
a new lookup instead of reusing a translation from the previous settings.
Errors appear in the panel with a Retry button.

Model suggestions come from the local CLI cache when it is available. The list
can be empty until the CLI has fetched models; entering an ID still works.
Startup automatically migrates the database and makes the usual migration
backup.

[Official documentation for non-interactive Codex](https://developers.openai.com/codex/noninteractive/)
