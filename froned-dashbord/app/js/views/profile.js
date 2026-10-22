import { h } from "../dom.js";
import { S } from "../state.js";
import { panel } from "../components/panel.js";
import { toggle, previewBox, runButton, quickButton, liveRunConfirm } from "../forms.js";

export function renderProfile() {
  return h(
    "div",
    { class: "page" },
    h("header", { class: "page-head" }, h("div", {}, h("h1", { text: "Naukri profile" }), h("p", { class: "lead", text: "Keep your Naukri headline and resume fresh so you surface in recruiter searches." }))),
    h(
      "div",
      { class: "dash" },
      h(
        "section",
        { class: "span-7" },
        panel(
          "Run settings",
          {},
          toggle("profile", "dry_run", "Dry run", "Show what would change without saving it."),
          toggle('profile','review','Review the full profile','Audit and update profile sections from your saved facts, beyond the headline and resume.'),
          toggle("profile", "if_due", "Only if due", "Skip unless the schedule says it’s time."),
          toggle("profile", "headless", "Headless browser"),
          previewBox("profile"),
          runButton("profile", "Run", { confirm: () => (S.forms.profile && S.forms.profile.dry_run ? null : liveRunConfirm("This updates your live Naukri profile.")) }),
        ),
      ),
      h(
        "section",
        { class: "span-5" },
        panel(
          "Scheduled updates",
          { sub: "Run the profile update automatically on a timer." },
          h("div", { class: "row", style: { flexWrap: "wrap" } }, quickButton("profile_status", "Check schedule status"), quickButton("profile_install", "Turn on the schedule", {}, { confirm: { title: "Turn on the schedule?", body: "This enables a recurring job on this computer. It can act as soon as the next scheduled step is due." } }), quickButton("profile_disable", "Turn off the schedule", {}, { confirm: { title: "Turn off the schedule?", body: "This disables future scheduled runs and unloads the current scheduled job. You can still run this bot manually.", ok: "Turn off", tone: "danger" } })),
        ),
      ),
    ),
  );
}
