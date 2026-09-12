# Pilot

A checklist for the first time someone other than the owner takes a course
through this tool, on a machine the owner has never touched. It tests two
things at once: setup and the launchers on a bare machine, including the one
CUDA state D24 could only simulate, and whether the tour, hover help and
glossary carry a first course with nobody helping. The observer fills it in.

## Before

- A machine with **no NVIDIA GPU**, ideally with no Python and no ffmpeg. A
  bare machine is the point; do not prepare it.
- One course delivery in the colleague's Downloads, as it arrives from the
  vendor.
- The observer has this page and the repository address, and does not touch
  the keyboard or answer a question until the colleague has tried the
  interface's own help. Note every question asked aloud and what answered it.

## What the colleague does

1. **Get the folder:** `git clone` if git is there, otherwise the ZIP from
   the repository page, unpacked anywhere.
2. **Run setup:** double-click `qa-setup.cmd` (Windows) or `qa-setup.command`
   (macOS). Do what it prints and run it again, until the smoke test passes.
3. **Open the interface:** double-click `qa-web.cmd` or `qa-web.command`.
   Take the tour or skip it; both are being watched.
4. **Bring the course in** on Intake: choose the files, answer the questions,
   submit, start the run from there.
5. **Watch it run** on Runs, then read Results: the listen list first, then
   download the packet.

## What the observer watches for

| Step | Watch for |
|---|---|
| 1 | Whether the README's START HERE block is found and followed. |
| 2 | With no Python: an install table, not an error nobody can act on. Each rerun picks up what was installed. Time from first double-click to "smoke test passed". |
| 3 | The tour appears once; Skip or the X works first time; the "Tour" link is found later unprompted. |
| 4 | Where the colleague hesitates, and whether a hover mark answers it. Whether the sidebar's GPU reason is read, and how it lands. |
| 5 | The run completes untouched. The listen list is understood as "my job" untold. Whether a column mark is hovered and the glossary reached from it. |

## Claims under test

Tick what held; write down what was seen when it did not.

- [ ] **NO GPU on a bare machine.** `qa-setup --check` reports the CUDA row
      `MISSING (optional)`, not `NOT USABLE` or `VERSION MISMATCH`, and the
      sidebar says GPU unavailable with a reason naming the cause. Record the
      exact text: a machine that never had CUDA takes a different branch from
      D24's simulation.
- [ ] **The CPU run completes unaided,** and the packet header says
      requested cpu, decoded on cpu.
- [ ] **Setup carries a bare machine.** Every missing prerequisite was named
      with a command that worked, nothing system-wide was installed by the
      tool, and the smoke test passed.
- [ ] **The launchers open from a double-click,** wherever the folder is.
- [ ] **The tour and help layer carry a first course.** A packet was reached
      with at most two questions to the observer, at least one answered by a
      hover mark or the glossary rather than by a person.
- [ ] **The glossary is discoverable** from a column mark or the Docs tab,
      unmentioned.

## Bring back

The ticked list with notes, the `qa-setup --check` output pasted whole, the
packet file, the time from first double-click to packet, and the questions
asked aloud. Enough to flip D24's NO GPU caveat and close the onboarding
claims in D30 and D36.
