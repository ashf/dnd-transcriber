# Session outputs for My Campaign

Write one file per item under "Session outputs" for every session, in the session folder, named `<session> - <output name>.md`. Then update every file under "Campaign files" in the campaign folder. Only the transcript has timestamps: no other output or campaign file contains any.

In the character files (character developments and `characters.md`), each character is a `## ` section. Inside it, a field with a short value stays on one line (`**Player:** Jordan`); every other field gets a `### ` subheading (`### What he did`, `### Relationships`) with its content below as a paragraph or a bullet list, never as one long bullet.

# Context

**Reference** for the spelling check (optional; see the cleanup prompt's No spoilers section): a URL or file for the published adventure, used only to correct the spelling of names, places, items and terms said at the table.

Each stage reads exactly these earlier files, and nothing else from earlier sessions.

**Stage A** (cleaning a window):
- the characters file, `characters.md` and `world.md`
- `corrections.md`, if it exists
- the previous session's summary, character developments and laughs
- the previous cleaned window of this session (none for window 1)

**Stage B** (writing the session outputs):
- this session's joined transcript
- the characters file, `characters.md` and `world.md` (both are updated by this stage)
- `corrections.md`, if it exists
- the previous session's summary, character developments and laughs

Never read earlier sessions' transcripts or raw transcripts, any `work/` folder other than this session's, image prompts, images or portraits.

# Session outputs

## transcript
The full cleaned transcript of the session as one continuous transcript, with one speaker map for the whole session. The recording parts are arbitrary cuts, so no part headings; lines exactly as in the cleaned windows. Build it with `join_windows.py`, never by retyping.

## summary
What happened in the session, in order, in plain prose with short headings per scene. End with a **Noteworthy inventory** list: items gained, lost, used or traded, who holds each one now, and where it came from.

## character developments
What changed for each character this session, one `## <character name>` section per character in the order of the characters file: what they did, what they revealed or learned, relationships that moved, items gained or lost, and new running jokes. Skip a character who was absent.

## laughs
A recap of the jokes, innuendo and moments that made the table laugh, in session order. For each: who said it (character and player), the line as spoken, and a few words of context. Include table-talk moments too.

## image prompts
Five prompts for an image generator, each from a separate pivotal scene of this session, numbered `## 1. <title>` to `## 5. <title>` (generated images are matched to scenes by that number or title). The prompts are used with each character's portrait attached as a reference image. For each scene:
- **Characters and reference images**: a numbered list of every player character in the scene, each with their portrait file from `source_files.portrait` in the characters file, in the order the images will be attached.
- **Prompt**: a self-contained prompt of 60 to 150 words. It opens by mapping the attachments ("Reference image 1 is Aria, reference image 2 is Sorrel"), asks the generator to keep each character's face, body and outfit from their reference image, then describes the setting, lighting, mood and composition and what each character is doing, naming them by character name (never by player name). NPCs and creatures have no reference image, so describe them in words. Describe only what the party saw.

# Campaign files

## characters.md
An overview of every player character as they stand now, one `## <short name>` section per character in the order of the characters file (for example `## Aria`). It is not tied to a session: no session headings and no timestamps. For each character: player, who they are, appearance, personality, relationships with the others, items they carry, running jokes, and open threads. Start from the current file when it exists and fold in this session's character developments; otherwise build it from the characters file and this session. Only facts shown at the table; nothing from source material.

## world.md
The campaign's world as the party knows it now, with no session headings and no timestamps. Sections: `## NPCs`, `## Places`, `## Items and artifacts` (notable things in the world, not the characters' inventories, which live in `characters.md`), `## Factions and organizations`, and `## Open mysteries`. Each entry is a `### <name as the party knows it>` subheading followed by a short paragraph: who or what it is, how the party met or found it, how it stands with the party, and the session it first appeared in (`First appeared: Session 2`). Spellings follow the transcripts, `[sp?]` marks included. Nest a place inside the place that contains it (rooms inside a floor, floors inside a building, buildings inside a town): give it the next heading level (`####`, then `#####`) and wrap each group of contained places in `<div class="nested" markdown>` and `</div>`, with blank lines inside, so the wiki indents it. Start from the current file when it exists and fold in this session; otherwise build it from this session. Only what the party learned at the table; nothing from source material.
