import { h } from "../dom.js";
import { S } from "../state.js";
import { panel } from "../components/panel.js";
import { field, toggle, textInput, selectInput, previewBox, runButton, quickButton, liveRunConfirm } from "../forms.js";

export function renderLinkedin() {
  const meta = S.meta;
  return h(
    "div",
    { class: "page" },
    h("header", { class: "page-head" }, h("div", {}, h("h1", { text: "LinkedIn post" }), h("p", { class: "lead", text: "Draft, propose or publish a LinkedIn update." }))),
    h(
      "div",
      { class: "dash" },
      h(
        "section",
        { class: "span-7" },
        panel(
          "Run settings",
          {},
          field("What to do", selectInput("linkedin", "mode", meta.linkedin_modes, "dry-run")),
          field("Draft file", textInput("linkedin", "draft", { placeholder: "path to a saved draft (optional)" }), "Leave blank to draft a new one."),
          toggle("linkedin", "headless", "Headless browser"),
          previewBox("linkedin"),
          runButton("linkedin", "Run", { confirm: () => (S.forms.linkedin && S.forms.linkedin.mode === "post" ? liveRunConfirm("This publishes the post on LinkedIn right now.") : null) }),
        ),
      ),
      h(
        "section",
        { class: "span-5" },
        panel(
          "Scheduled posts",
          { sub: "Post automatically on a timer." },
          h("div", { class: "row", style: { flexWrap: "wrap" } }, quickButton("linkedin_status", "Check schedule status"), quickButton("linkedin_install", "Turn on the schedule", {}, { confirm: { title: "Turn on the schedule?", body: "This enables a recurring job on this computer. It can act as soon as the next scheduled step is due." } }), quickButton("linkedin_disable", "Turn off the schedule", {}, { confirm: { title: "Turn off the schedule?", body: "This disables future scheduled runs and unloads the current scheduled job. You can still run this bot manually.", ok: "Turn off", tone: "danger" } })),
        ),
      ),
    ),
  );
}
