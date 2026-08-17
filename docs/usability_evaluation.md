# Usability Evaluation Protocol

This is a small formative evaluation for the GUI and CLI. Confirm university
ethics requirements before recruiting or recording participants. If formal
approval is not available, use expert review or clearly labelled informal peer
feedback instead of presenting the work as a user study.

## Participants

Aim for 3-5 people familiar with at least one of lighting, compositing,
rendering or Python pipeline work. Record their relevant experience, not
unnecessary personal data.

## Tasks

1. Select and inspect the generated multilayer EXR.
2. Identify how many colour and technical AOVs are present.
3. Run default validation and explain the emission finding.
4. Change the luminance model to custom weights and rerun.
5. Find missing frame 1002 in the generated sequence.
6. Export JSON and locate the overall status and per-frame metrics.

## Measures

- Task completion without assistance.
- Time per task.
- Number of navigation or interpretation errors.
- Whether PASS, WARNING and FAIL are understood correctly.
- Whether the finding message and recommendation lead to the expected action.
- A 1-5 confidence rating after each task.

## Interview prompts

- Which result would you check first in a real delivery?
- Was any label ambiguous?
- Did the distinction between aggregate and per-frame metrics make sense?
- Which rule would you enable or disable for your own workflow?
- What information is still missing before you would trust the tool?

## Reporting

Report participant count, background, task success, median completion time and
recurring observations. Separate direct observations from interpretation.
Do not generalise a small convenience sample to the whole VFX industry.
