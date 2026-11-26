# HelloWorld pre-production

This folder of HelloWorld connects open-source film tools into one pre-production and previs pipeline:

- **[Open Shot Designer](https://github.com/koosoli/OpenShotDesigner)** for planning: the shot list, camera notes and storyboards.
- **[Kitsu](https://www.cg-wire.com/kitsu)** and **[AYON](https://ynput.io/ayon/)** for tracking: tasks, reviews and pipeline folders.
- **[OpenTimelineIO](https://opentimelineio.readthedocs.io)** into **[Blender](https://www.blender.org)** for the cut.

The pipeline does not generate images. It organises the boards, reference frames and renders that people make, and moves them between the tools.

```
Open Shot Designer  (.osd)          shot list, camera notes, your storyboard drawings
        │
        │  helloworld kitsu push
        ▼
      Kitsu  ── AYON Kitsu addon (live, one way) ──▶  AYON
        │                                              pipeline folders, tasks, frame ranges
        │  artists post previs / renders on Layout, Animation … tasks
        │
        │  helloworld kitsu pull                helloworld animatic   (boards → cut)
        ▼                                         helloworld conform    (renders on disk → cut)
     cut.otio  ◀──────────────────────────────────┘
        │
        ▼
   Blender sequencer  (HelloWorld OTIO add-on)
        import the cut, flip each shot between board / previs / final, export it back
```

| Piece | What it does here | License |
| --- | --- | --- |
| Open Shot Designer | Shot lists, floor plans and storyboards. You upload your own drawings or photos as frames. | GPL-3.0 |
| Kitsu | Production tracking and review of boards, previs and renders. | AGPL-3.0 |
| AYON | Pipeline project that mirrors Kitsu: folders, tasks, frame ranges, fps and resolution. | Apache-2.0 |
| OpenTimelineIO | The cut, with several media versions per shot. | Apache-2.0 |
| Blender | Sequencer for the board-o-matic, previs cut and finishing. | GPL-2.0-or-later |
| **HelloWorld pre-production** | The `helloworld` command, the stack setup and the Blender add-on in this folder. | GPL-3.0-or-later |

## Requirements

- Python 3.10 or newer.
- Docker Desktop, for Kitsu and AYON.
- Blender 4.2 or newer (tested with 5.1).
- git, to build the AYON images.
- Node.js (npm), to build Open Shot Designer for the app.

## Install

Every command in this README runs from the `preproduction/` folder.

```bash
cd preproduction
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
```

## The app

Everything below can be run from one local web page. Double-click `HelloWorld.command` in Finder, or run:

```bash
helloworld app          # opens http://localhost:8765
```

The first time, open **Setup** in the sidebar. Each step has a button: build the AYON images, start Kitsu and AYON, build Open Shot Designer, and install the Blender add-on.

After that:

- **Open Shot Designer** runs inside the app. To open a HelloWorld plan there, use **Cloud → Nextcloud → Connect** (the address and password are already filled in), then **Open**. Saving it back with the Nextcloud button on its card updates the project in HelloWorld. You can also drop a `.osd` file onto the app.
- Each **project page** walks the pipeline: **Push** to Kitsu, **Sync** to AYON, **Build the cut**, **Pull** previews from Kitsu, **Attach renders**, then **Open in Blender**. Every shot shows its boards, its tasks in Kitsu, and which versions (board, previs, final) the cut has.
- **Kitsu** and **AYON** also open inside the app. Their logins are on the Setup page.
- The **Activity** bar at the bottom shows the log of everything the app runs.

Projects live in `~/Documents/HelloWorld Projects/<name>/`:

| Path | What it is |
| --- | --- |
| `plan.osd` | The plan. Older versions are kept in `history/`. |
| `cut/cut.otio` | The cut. Media from Kitsu sits next to it in `cut/cut_media/`. |
| `renders/` | Put finished renders here, named after their shot (`SC001_SH002_v001.mov`). |
| `edit.blend` | The Blender edit. **Rebuild from cut** moves the old one to `history/`. |

Options: `--port`, `--projects <folder>` (or the `HELLOWORLD_PROJECTS` variable), and `--no-browser`. The app only answers on localhost. Its WebDAV password for Open Shot Designer is in `.app/settings.json`, which git ignores.

The sections below do the same steps from the command line.

## 1. Start the tracking stack (Kitsu + AYON)

```bash
python stack/setup.py build    # once: builds the AYON server and Kitsu-sync images
python stack/setup.py up       # starts everything and connects AYON to Kitsu
python stack/setup.py status   # URLs and logins
```

`up` does the following:

- Starts Kitsu on <http://localhost:8080> and AYON on <http://localhost:5005>. Port 5000 is avoided because macOS uses it for AirPlay.
- Installs AYON's `core` and `kitsu` addons.
- Points the `kitsu` addon at the Kitsu container.
- Starts the service that copies Kitsu changes into AYON.

Every port is bound to `127.0.0.1` only.

Logins are generated on the first `up` and written to `stack/.env`. That file is git-ignored, so keep it private.

Kitsu starts with the cgwire image's default admin, `admin@example.com` / `mysecretpassword`. If you change that password in Kitsu, also change it in `stack/.env` and in AYON (Studio settings → Secrets → `kitsu_password`), so the sync keeps working.

Ynput publishes AYON images for x86-64 only. `build` compiles the same release tags (AYON 1.17.8, Kitsu addon 1.2.8) for whatever machine you run it on, so Apple Silicon runs natively without Rosetta. To use other images, set `AYON_IMAGE` or `KITSU_PROCESSOR_IMAGE` in `stack/.env`.

To stop the stack:

```bash
python stack/setup.py down          # stop, keeping the data
python stack/setup.py down --wipe   # stop and delete Kitsu and AYON data
```

## 2. Plan in Open Shot Designer

Build the shot list in Open Shot Designer, upload your storyboard frames to each shot, and save the project as a `.osd` file. `examples/sample.osd` is a small two-scene project to try things with:

```bash
helloworld inspect examples/sample.osd
```

```
Sample Production  (24 fps, schema v42)
  SC001    INT. LIVING ROOM - NIGHT
    SH001   slate 1/1    WS   24mm   Static      45.0s  1 board(s)  [ready]
    SH002   slate 1/2    MCU  50mm   Static      25.0s  1 board(s)  [planned]
    SH003   slate 1/3    CU   85mm   Dolly In    30.0s  2 board(s)  [planned]
  SC002    INT. INTERROGATION ROOM - NIGHT
    ...
```

HelloWorld reads `.osd` files from Open Shot Designer project schemas 40–42 (app version 1.15). It reads both the zip package format and the older JSON export.

## 3. Push the plan to Kitsu

```bash
export KITSU_HOST=http://localhost:8080 KITSU_EMAIL=admin@example.com KITSU_PASSWORD=...   # from stack/.env
helloworld kitsu push examples/sample.osd
```

| Open Shot Designer | Kitsu |
| --- | --- |
| The project title | The production (or set `--kitsu-project`). Its fps and resolution come from the plan, e.g. 24 fps and 1920×804 for 2.39:1. |
| Scene 1 | Sequence `SC001`, described with the scene heading |
| Shot `1/2` (lettered shots such as `1A` keep their name) | Shot `SH002`, with frames = estimated duration × fps (3 s if no estimate) |
| Slate, size, lens, angle, movement, camera, status | Shot metadata columns |
| Storyboard frames (start frame plus camera waypoints) | One preview revision on the shot's Storyboard task |

Pushing again updates the shots, and re-uploads boards only for shots whose boards changed.

## 4. Mirror it into AYON

```bash
python stack/setup.py pair "Sample Production"
```

This pairs the Kitsu production with a new AYON project and runs the first sync. From then on, changes in Kitsu reach AYON on their own. For example, a new Layout task appears as `/sequences/sc001/sh002/layout` with frame range 1001+ and the plan's fps and resolution.

The sync runs one way only: AYON's Kitsu addon copies Kitsu into AYON and never writes back.

## 5. Build the cut

```bash
helloworld animatic examples/sample.osd -o cut/cut.otio
```

This writes a board-o-matic: one clip per shot, holding that shot's boards for its estimated duration, with scene markers. The board images go next to the cut, in `cut/cut_media/`.

Each clip is named `SC001_SH002`, which is Kitsu's own OTIO naming (`${sequence_name}_${shot_name}`), so Kitsu's OTIO import matches the same shots. The clip keeps its camera notes in its metadata.

As previs and renders arrive, attach them to the cut as new stages:

```bash
# newest Layout preview of every shot, from Kitsu
helloworld kitsu pull cut/cut.otio --task-type Layout --stage previs

# renders on disk: SC001_SH002.mov, SC001_SH002_v003.mov or a SC001_SH002_v004/ frame folder
helloworld conform cut/cut.otio renders/ --stage final
```

When a shot has several versions, the highest one wins.

Each stage is stored as its own media reference on the clip. The boards stay attached, so nothing is replaced.

## 6. Open it in Blender

Package the add-on and install it:

```bash
blender --command extension build --source-dir blender/helloworld_otio --output-dir dist
```

Then, in Blender, go to Preferences → Get Extensions → Install from Disk and choose `dist/helloworld_otio-0.1.0.zip`.

In the Sequencer, open the sidebar (N) and the **HelloWorld** tab. Click **Install OpenTimelineIO** once; this needs Blender's *Allow Online Access* setting.

- **File → Import → OpenTimelineIO (HelloWorld)** builds the cut, showing each shot's most finished stage (final, then previs, then board).
  - Shots with several boards are split into one strip per board.
  - A shot with no media yet becomes a colour placeholder.
  - A label strip shows the slate and camera notes.
  - Scenes become timeline markers.
- **Show Stage** switches the selected strips between board, previs and final.
- **File → Export → OpenTimelineIO (HelloWorld)** writes the cut back out with your trims and reordering. Every stage's media and the shot metadata come along.

## Tests

The Blender smoke test runs inside Blender:

```bash
blender --background --factory-startup --python tests/blender/smoke_vse.py -- \
    --otio cut/cut.otio --out /tmp/hw-smoke --deps /path/to/site-packages-with-opentimelineio
```

It covers import, labels, stage switching and the export round trip. It also fails on any Blender API that is marked for removal.

`tests/integration/post_previs.py` stands in for an artist by posting a movie to a shot's Layout task in Kitsu. Use it to try `kitsu pull` without opening Kitsu.

## Regenerating the sample project

`tools/make_sample_osd.mts` builds `examples/sample.osd` with Open Shot Designer's own project code, so it needs a checkout of that repo:

```bash
git clone --depth 1 https://github.com/koosoli/OpenShotDesigner.git vendor/osd
(cd vendor/osd && npm ci)
python tools/make_placeholder_boards.py /tmp/boards
vendor/osd/node_modules/.bin/tsx tools/make_sample_osd.mts --out examples/sample.osd --title "Sample Production" /tmp/boards/*.png
```

Pass your own images instead of `/tmp/boards/*.png` to put real boards in the sample.

## Status

This is early. The full loop works on a local stack: plan → Kitsu → AYON → previs back from Kitsu → Blender cut. The known gaps:

- There are no unit tests for the Python package yet, only the Blender smoke test and the integration helper.
- The Blender add-on downloads OpenTimelineIO on first use instead of bundling it.
- Kitsu → AYON is one way, because that is how AYON's Kitsu addon works.

## License

The code in this `preproduction/` folder is licensed under GPL-3.0-or-later (see `LICENSE` here). That license covers this folder only, not the rest of the HelloWorld repo. The tools it connects keep their own licenses, listed in the table above. The CLI talks to Kitsu through [Gazu](https://github.com/cgwire/gazu), which is LGPL-3.0.
