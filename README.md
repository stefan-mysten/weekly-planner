# Weekly planner

A local page for logging what you worked on each day, with a weekly summary of
what got finished and what did not. One Markdown file per week in `data/`.

- Page: <http://localhost:4747/>
- Check-in: a dialog pops up at 16:00 on weekdays. If the laptop is asleep then,
  it appears on wake (until 20:00).

## Running

```sh
./service.sh install     # run in the background, now and at every login
./service.sh uninstall   # stop and remove
./planner.py             # or run it in a terminal instead
./planner.py ping        # show the check-in dialog now
```

Python 3 standard library only. The schedule, port and weekday list are
constants at the top of `planner.py`; restart after changing them
(`./service.sh install` again).

## File format

`data/2026-W47.md` (ISO week number):

```markdown
# Week 47 · Nov 16 – 20, 2026

## Monday 2026-11-16
- [x] work on X
- [ ] work on Y
  - [x] a sub-item of Y
  - [ ] another one

## Tuesday 2026-11-17
...

## Notes
free text

## Summary
### Finished
- work on X
### Not finished
- work on Y
### Also finished
- something of my own
### Also not finished
- another thing of my own
```

The search box on the page looks through every week in `data/`: day items,
notes and your own summary lines. All words must match, in any order. Press `/`
to jump to it, Escape to leave, and click a result to open its week.

Rules for editing the files by hand or with an agent:

- Add items under the `## <Day>` headings. `- [x]` is finished, `- [ ]` or a
  plain `- ` bullet is not finished yet.
- Indent a line by two spaces or more to make it a sub-item of the item above
  (in the page: Tab and Shift+Tab). There is one level; deeper indents are
  flattened to it.
- Sub-items have their own checkboxes. A parent is finished only when it is
  ticked itself. The summary shows `(1/3 sub-items done)` next to a parent and
  lists the still-open sub-items under unfinished parents.
- In `## Summary`, the `### Finished` and `### Not finished` lists are
  regenerated from the checkboxes on every save from the page, so do not edit
  them; they can lag behind after a hand edit until the next save.
- Your own summary lines go under `### Also finished` and
  `### Also not finished`. Those are kept as written and are editable in the
  page under the generated lists.
- An item is finished for the week if any entry with the same text is ticked,
  so re-listing Monday's unfinished item on Tuesday and ticking it there works.
- Any other `## Section` you add is kept as is.
- The page reloads the file when its tab regains focus. If the file changes
  while you are typing in the page, the file wins and the page reloads.
