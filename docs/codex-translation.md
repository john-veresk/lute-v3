# Translation with local Codex CLI

In **Settings → Languages → Edit**, select **Codex CLI translation** under
**Translation source**. Set **Translate into** (Russian by default), and choose
a **Codex model** from the suggestions or enter a model ID. Leave the model
blank to use the CLI's configured default. Save the language and reload the book.
No website dictionaries are required in this mode. Existing website settings
are retained for switching back.

Clicking a word or selecting a phrase opens a **Codex** tab in the dictionary
panel. It translates the term using the sentence from the book and shows up to
four meanings with brief explanations and the dictionary form. The best meaning
fills an empty Translation field automatically. Click another meaning to select
it, then use the existing **Save** button to store it in your vocabulary.
Saved translations and text typed while a request is running are preserved.
Sentence and page translation commands also use Codex. Sentences and image
lookup tabs remain available.

For an unambiguous inflected word, Codex also adds the dictionary headword to
**Parents** automatically: an infinitive for a verb, nominative singular for a
noun, or the language's standard base form. The panel shows a separate editable
**Dictionary translation** for that parent. For example, `halusi` can have
`хотела`, while its parent `haluta` has `хотеть`. The parent and its translation
are saved together with the child when you press **Save**. Looking up a word
alone does not create vocabulary. Existing parents, parent translations, and
parents changed or removed while the lookup was running are preserved. If the
grammar is uncertain, Codex leaves Parents alone.

For a phrase with 2–40 distinct words, **Words in phrase** shows individual word
cards, translations and any inflected words' base forms. Use **Add word** on one
card, or select checkboxes and press **Add selected words**. These buttons save
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
language and model. Errors appear in the panel with a Retry button.

Model suggestions come from the local CLI cache when it is available. The list
can be empty until the CLI has fetched models; entering an ID still works.
Startup automatically migrates the database and makes the usual migration
backup. Existing languages keep their dictionary provider until changed.

[Official documentation for non-interactive Codex](https://developers.openai.com/codex/noninteractive/)
