# dnd-transcriber

`dnd-transcriber` turns recordings of a tabletop D&D session into a clean transcript and a set of session notes.

The transcript says who spoke each line. In-character lines are credited to the character and the player. Out-of-game chatter is marked as table talk and credited to the real person. The session notes can include a summary, updated character profiles, a recap of the funniest moments, and image prompts.

Transcripts never reveal campaign spoilers. Everything written comes from what was said at the table, not from knowledge of the published adventure.

## How it works

The work happens in two steps.

1. **Transcribe** (`transcribe.py`). This runs on your Mac. It turns a session's recordings into a base transcript: timestamped lines of text, each labeled with a voice such as `VOICE_03`. A voice label is a guess at "the same person", made from how the voice sounds. It does not yet say who that person is.
2. **Clean up** (`CLEANUP_PROMPT.md`). A language model reads the base transcripts along with your campaign files. It works out which voice belongs to which player, fixes misheard names, sorts every line into a category, and writes the session outputs. You can run this step in Claude Code, in Codex, or through the Anthropic API.

A session is often recorded in several parts, because recording was stopped and restarted. The parts are joined into one recording before anything else happens. The joined session is then transcribed and cut into windows of about 45 minutes, each cut at a pause. The cleanup works one window at a time, because a model cleaning a whole session in one pass tends to condense it. One long recording of a session works exactly the same way. Each line's timestamp is the local clock time, so times run straight through the whole session.

### Step 1 in more detail

- **Joining.** The parts are joined in part order. Any gap between one part's end and the next part's recorded start becomes silence, so clock times stay exact.
- **Speaker separation.** `pyannote` (through `whisperx`) splits the whole session into turns and groups the turns by voice, so `VOICE_03` is the same person in every window.
- **Voice matching.** Each voice gets a fingerprint, saved in `<session>.voices.json`. The DM's NPC voices sometimes form their own group; the matcher folds them back into the DM.
- **Speech recognition.** NVIDIA's Parakeet TDT 0.6B v2 model, through `parakeet-mlx`, writes the words. Before this step the audio is leveled, which lifts quiet voices far from the microphone.
- Everything runs on the Mac's GPU. A 4-hour session took 12 minutes on an M4 Pro.

### Line categories

The cleanup sorts every line into one of four categories:

- **DM**: the Dungeon Master narrating, making rulings, or voicing an NPC.
- **In character**: a player speaking or acting as their character.
- **Game talk**: a player speaking as themselves about the game, for example rules, rolls, or who takes the loot.
- **Table talk**: anything not about the game, for example food, scheduling, or real life.

## Requirements

- A Mac with Apple Silicon.
- [`uv`](https://docs.astral.sh/uv/) and `ffmpeg` (`brew install ffmpeg`).
- A Hugging Face account. Accept the terms of [`pyannote/speaker-diarization-community-1`](https://huggingface.co/pyannote/speaker-diarization-community-1), then sign in once with `uvx hf auth login`.
- For the cleanup step: Claude Code, Codex, or an Anthropic API key.

Install the dependencies:

```sh
uv sync
```

## Set up a campaign folder

The campaign folder holds campaign-wide files. Each session gets its own folder with its recordings:

```
My Campaign/
  characters.json          the player characters
  session-outputs.md       what to write for each session
  characters.md            the character overview (written by the cleanup)
  corrections.md           corrections from the wiki (written by pull_corrections.py)
  aria portrait.png      portraits and other supplemental files
  Session 1/
    Session 1 (part 1).m4a
    Session 1 (part 2).m4a
```

A recording's name ties it to its session. `Session 1 (part 2)` belongs to the session `Session 1`.

`examples/` holds a starting `characters.json` and `session-outputs.md` to copy into your campaign folder.

### `characters.json`

This file lists the DM and every player character. Each character needs at least `player` and `name`:

```json
{
  "campaign": "Name of the published campaign, if any",
  "dm": "Pat",
  "characters": [
    { "name": "Aria Vale", "player": "Jordan", "nicknames": ["Aria"] },
    { "name": "Brunn", "player": "Alex", "nicknames": ["Red"] }
  ]
}
```

You can add anything else that helps the cleanup, such as appearance, class, backstory, or companions. The `campaign` field only tells the cleanup what to avoid spoiling. It is never used as a source of facts.

### `session-outputs.md`

This file lists what the cleanup writes for each session. Each `## heading` is one output, and the text under it describes what that output must contain. For example:

```markdown
## summary
What happened in the session, in order. End with a list of noteworthy inventory items.

## laughs
The jokes and moments that made the table laugh, with timestamps.
```

Edit it freely. The cleanup follows whatever it lists.

## Step 1: transcribe

```sh
uv run python transcribe.py "My Campaign/Session 1/Session 1 (part "*").m4a" \
  --characters "My Campaign/characters.json" \
  --present Jordan Sam Alex
```

- `--present` names the players at the table. The DM is counted automatically. Leave it out if you do not know who came.
- `--models` picks the speech models. The default is `parakeet`. `v2` and `turbo` are Whisper models, and they are slower.
- `--out-dir` changes where files go. The default is a `work` folder next to the recordings.

The command writes these files for each session:

- `<session> (window N).parakeet.transcript.txt`: the base transcript, one file per window.
- `<session>.speakers.csv`: the saved speaker turns. They are reused if you add another model later.
- `<session>.voices.json`: the voice fingerprints.

Existing transcripts are never overwritten. To redo a session, delete its transcripts and its `.speakers.csv`.

## Step 2: clean up

### In Claude Code or Codex

Open the tool in the campaign folder and ask:

> Follow `~/dev/dnd-transcriber/CLEANUP_PROMPT.md` for Session 2. The transcripts are in `Session 2/work`, the characters are in `characters.json`, and the outputs are listed in `session-outputs.md`. Use `characters.md`, `corrections.md` and Session 1's outputs as context.

The cleanup runs in two stages:

- **Stage A** cleans each window in order and writes `<session>/work/<session> (window N).clean.md`.
- **Stage B** reads the whole session, writes each session output from `session-outputs.md` as `<session>/<session> - <output>.md`, and updates the campaign files it lists, such as `characters.md`. The full transcript is not retyped by the model: `join_windows.py` joins the cleaned windows.

```sh
uv run python join_windows.py "My Campaign/Session 1/work" "Session 1"
```

### Through the Anthropic API

`cleanup_api.py` runs stage A for one window at a time:

```sh
export ANTHROPIC_API_KEY=...
uv run python cleanup_api.py "My Campaign/Session 1/work/Session 1 (window 1).parakeet.transcript.txt" \
  --context "My Campaign/characters.json"
```

- Add the `.clean.md` files of earlier windows to `--context` so voices and names carry over.
- `--force` overwrites an existing `.clean.md`. Without it, the script stops before making the API call.
- If the model stops early, the text it wrote so far is saved as `.clean.md.partial`.

Stage B has no API script yet. Run it in Claude Code or Codex.

## Output layout

```
My Campaign/
  characters.md
  Session 1/
    Session 1 (part 1).m4a ...
    Session 1 - transcript.md
    Session 1 - summary.md
    Session 1 - character developments.md
    Session 1 - laughs.md
    Session 1 - image prompts.md
    The Armor Awakens.jpeg        images you generate from the prompts
    work/
      Session 1 (window 1).parakeet.transcript.txt
      Session 1 (window 1).clean.md
      Session 1.speakers.csv
      Session 1.voices.json
```

A session folder holds its recordings, its finished outputs and your generated images. Everything in progress lives in `work/`. Each session's outputs, and the campaign's `characters.md`, become context for the next session's cleanup.

## Campaign wiki

`wiki/` builds a private website from a campaign folder: a home page, a Characters page with each character's overview and portrait, and every session's outputs, with search. On a session's image prompts page, each generated image appears under its scene when the image's file name starts with the scene's title or number (`The Armor Awakens.jpeg`, `3 alt.png`). Every page ends with a corrections form. A correction is stored with the sender's email, and the next cleanup reads it.

The site is hosted on Cloudflare Pages. Cloudflare Access keeps it private: only the email addresses you list can open it, and they sign in with a one-time code sent by email. Both are free for a group this size. The corrections are kept in a Cloudflare D1 database.

Campaign content is never committed: `wiki/docs`, `wiki/site` and `wiki/mkdocs.yml` are generated and ignored by git.

### One-time setup

Copy `wiki/wrangler.example.toml` to `wiki/wrangler.toml` and `wiki/mailer/wrangler.example.toml` to `wiki/mailer/wrangler.toml`, then fill in your site name, address and Cloudflare details. Both copies stay out of git.

Run these from the `wiki` folder:

```sh
npx wrangler login                                   # opens a browser
npx wrangler d1 create campaign-corrections          # put the printed database_id into wrangler.toml
npx wrangler d1 execute campaign-corrections --remote --file schema.sql
npx wrangler pages project create my-campaign --production-branch main
```

Then, in the Cloudflare dashboard:

1. **Custom domain.** In the Pages project, add a custom domain, for example `wiki.example.com`.
2. **Private access.** In Zero Trust, under Access, add a self-hosted application for that hostname. Add a policy that allows your friends' email addresses, and use the one-time PIN login method.
3. **Close the back door.** In the Pages project settings, turn on the access policy, edit the Access application it creates, and remove the `*` from the subdomain so it protects `my-campaign.pages.dev` itself. Otherwise the site is public at that address.

### Who can get in

Cloudflare Access only proves who a visitor is: its policy lets anyone sign in. The site itself checks the signed-in email against a members list. A member sees the wiki. Anyone else sees a "Request access" page with a short form. You approve requests from the terminal:

```sh
uv run python wiki/access.py requests                  # pending requests
uv run python wiki/access.py approve friend@gmail.com  # let them in and email them
uv run python wiki/access.py welcome friend@gmail.com  # email a member the welcome again
uv run python wiki/access.py add me@gmail.com "Riley"  # add someone directly
uv run python wiki/access.py deny friend@gmail.com     # decline a request
uv run python wiki/access.py revoke friend@gmail.com   # take access away
uv run python wiki/access.py members                   # who is in
```

The check verifies Cloudflare's signed login token (`wiki/lib/access.js`) instead of trusting a header, because it is the only thing between a stranger and the wiki. `wrangler.toml` holds the Access team domain and the audience tags of the two Access applications.

### Welcome emails

`access.py approve` emails the person once they are approved, from `wiki@example.com`, through [Resend](https://resend.com). Cloudflare's own mail only reaches addresses you have verified, so it cannot email friends. Setup: verify the domain in Resend (it lists DNS records on the `resend._domainkey` and `send` names, which do not touch Email Routing), create a sending-only API key, and keep it in the macOS Keychain:

```sh
security add-generic-password -a resend -s dnd-wiki-resend -w   # paste the key when asked
```

The approval is saved before the email is sent, so a failed email never blocks access. `--quiet` approves without emailing.

### Email alerts for access requests

`wiki/mailer` is a small Worker that emails you when someone asks to join. The wiki calls it through a service binding; it has no public address. It sends with Cloudflare Email Routing, which only delivers to addresses you have verified, so it can only ever email you.

One-time setup:

1. In the Cloudflare dashboard, turn on **Email Routing** for your domain and verify your personal address under **Destination addresses**. Routing rules there can also forward mail sent to your domain, for example `asher@example.com`, to that address.
2. Deploy the Worker and give it your address as an encrypted secret, so the address never enters the repo:

```sh
cd wiki/mailer
npx wrangler deploy
npx wrangler secret put NOTIFY_TO   # type your personal email when asked
```

A failed email never affects the request itself: the request is saved first.

### After each session

```sh
uv run --group wiki python wiki/build_site.py "My Campaign" --characters "My Campaign/characters.json" --title "My Campaign"
cd wiki && npx wrangler pages deploy site --project-name my-campaign
```

Before cleaning the next session, download the corrections so the cleanup can use them:

```sh
uv run python wiki/pull_corrections.py "My Campaign/corrections.md"
```

## Tests

```sh
uv run pytest -q
node --test wiki/test/access.test.mjs wiki/test/mailer.test.mjs
```

The tests replace the speech models, speaker separation, `ffmpeg`, and the Anthropic API with fakes. They do not download models or make paid calls.

## License

MIT. See `LICENSE`.
