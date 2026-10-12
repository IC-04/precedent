# Public README media

The README is the complete reviewer experience. These assets are deliberately curated from
the existing recorded film, not synthetic interface mockups. Raw footage and private account
evidence stay in the ignored `output/` and `runs/` directories.

`manifest.json` identifies the source segments, timestamps, cuts, output sizes and the separate
assessment results. Privacy masks and speed/staging labels are baked into the source clips and
retained in the previews. The banners reuse the project's existing Ava vector drawing and palette.

- `execution.gif`: an 18-second edit of the cross-app task, with actual typing and native results.
- `verification.gif`: a separate invoice hearing and a labelled staged recovery explanation.
- `learning.gif`: notes, a candidate procedure and interpreted teaching; activation is not implied.
- The stills are frames from the same reviewed segments. Open full-size screenshots through the
  README's expandable galleries.

To regenerate footage-derived assets when the ignored source package is available:

```sh
.venv/bin/python scripts/build_readme_media.py
.venv/bin/python scripts/check_readme.py
```

The committed assets are sufficient to view the README from a clean clone; the source recordings
are not required. Regeneration additionally needs Pillow and imageio-ffmpeg, used by the existing
film toolchain. `imageio-ffmpeg` is already a project dependency; install Pillow in the editing
environment if absent. No model call or new narration is made during this build.

The full 1080p film is a versioned GitHub Release asset, not a large file committed to Git history.
Its passing invoice hearing and its Gmail execution are distinct runs. The public
[evidence index](../../docs/evidence/README.md) keeps that distinction explicit.
