import { h } from "../dom.js";
import { S } from "../state.js";
import { panel } from "../components/panel.js";
import { field, toggle, textInput, selectInput, previewBox, runButton, liveRunConfirm } from "../forms.js";

export function renderNaukri() {
  const meta = S.meta;
  return h(
    "div",
    { class: "page" },
    h("header", { class: "page-head" }, h("div", {}, h("h1", { text: "Apply on Naukri" }), h("p", { class: "lead", text: "Search, score and apply to matching jobs on Naukri." }))),
    panel(
      "Run settings",
      {},
      h(
        "div",
        { class: "form-grid" },
        field("Keywords", textInput("naukri", "keywords", { placeholder: "e.g. AI Engineer" }), "Leave blank to use the keywords in your .env."),
        field("Location", textInput("naukri", "location", { placeholder: "e.g. Bengaluru" }), "Leave blank to use your .env location."),
        field("Limit", textInput("naukri", "limit", { placeholder: "e.g. 20", type: "number", inputmode: "numeric" }), "How many jobs to consider this run; leave blank for no limit."),
        field("Answer mode", selectInput("naukri", "answer_mode", meta.answer_modes, "")),
        field('Minimum match score', textInput('naukri','min_score',{type:'number',min:0,max:100,placeholder:'Use configured score'}),'Only consider jobs meeting this score, from 0 to 100.'),
        field('Maximum job age (days)', textInput('naukri','max_days_old',{type:'number',min:0,max:365,placeholder:'Use configured age'}),'Zero disables the age filter.'),
        field('Scoring provider', selectInput('naukri','llm_backend',[{value:'',label:'Use configured provider'},...['claude-cli','kiro-cli','anthropic','none'].map(value=>({value,label:value==='none'?'Keyword scoring only':value}))],'')),
        field('Early-access collection limit', textInput('naukri','early_access_limit',{type:'number',min:1,max:500,placeholder:'Use configured limit'})),
      ),
      toggle("naukri", "dry_run", "Dry run", "Rank and preview jobs without applying to any of them."),
      toggle("naukri", "headless", "Headless browser", "Run Chrome without a visible window."),
      toggle("naukri", "early_access", "Include early-access jobs", "Also consider jobs from Naukri’s early-access feed."),
      toggle("naukri", "early_access_only", "Early-access only", "Only look at the early-access feed."),
      previewBox("naukri"),
      h(
        "div",
        { class: "row" },
        runButton("naukri", "Run", { confirm: () => (S.forms.naukri && S.forms.naukri.dry_run ? null : liveRunConfirm("This submits real applications on Naukri, not a practice run.")) }),
      ),
    ),
  );
}
