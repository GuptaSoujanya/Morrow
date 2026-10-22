import { h } from "../dom.js";
import { S } from "../state.js";
import { api } from "../api.js";
import { panel } from "../components/panel.js";
import { field, toggle, textInput, textArea, previewBox, runButton } from "../forms.js";
import { toast } from "../components/toast.js";

function openResumes() {
  api("/api/open", { what: "resumes" }).catch((error) => toast(error.message, "error"));
}

export function renderResume() {
  return h(
    "div",
    { class: "page" },
    h("header", { class: "page-head" }, h("div", {}, h("h1", { text: "Tailor resume" }), h("p", { class: "lead", text: "Paste a job description, and get a resume tailored to it." })), h("div", { class: "head-actions" }, h("button", { class: "btn", type: "button", text: "Open resumes folder", onclick: openResumes }))),
    panel(
      "Run settings",
      {},
      field("Job description", textArea("resume", "jd_text", { placeholder: "Paste the job description here…", rows: 8 })),
      field("…or a saved JD file", textInput("resume", "jd_file", { placeholder: "path to a .txt file" }), "Used only when the box above is empty."),
      h(
        "div",
        { class: "form-grid" },
        field("Title", textInput("resume", "title", { placeholder: "Job title" })),
        field("Company", textInput("resume", "company", { placeholder: "Company" })),
      ),
      toggle("resume", "headless", "Headless browser"),
      previewBox("resume"),
      runButton("resume", "Build the resume"),
    ),
  );
}
