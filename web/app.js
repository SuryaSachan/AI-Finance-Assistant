const $ = (s) => document.querySelector(s);
const messages = $("#messages");
let sessionId = null;
let busy = false;

const MONEY_COLS = /amount|total|balance|sum_|avg_|min_|max_|value|baseline/i;
const CURRENCY = "INR";

function fmtMoney(v) {
  return Number(v).toLocaleString("en-IN", { style: "currency", currency: CURRENCY, maximumFractionDigits: 2 });
}

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function fmtCell(col, v) {
  if (v === null || v === undefined) return '<span style="color:#556">—</span>';
  if (typeof v === "number" && MONEY_COLS.test(col)) return fmtMoney(v);
  if (typeof v === "number") return v.toLocaleString();
  return esc(v);
}

function table(columns, rows) {
  if (!rows || !rows.length) return "";
  const head = columns.map((c) => `<th>${esc(c.replace(/_/g, " "))}</th>`).join("");
  const body = rows
    .map(
      (r) =>
        "<tr>" +
        columns
          .map((c) => `<td class="${typeof r[c] === "number" ? "num" : ""}">${fmtCell(c, r[c])}</td>`)
          .join("") +
        "</tr>"
    )
    .join("");
  return `<table class="data"><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table>`;
}

function addUser(text) {
  messages.insertAdjacentHTML(
    "beforeend",
    `<div class="msg user"><div class="bubble">${esc(text)}</div></div>`
  );
  messages.scrollTop = messages.scrollHeight;
}

function addPending() {
  const el = document.createElement("div");
  el.className = "msg bot";
  el.innerHTML =
    `<div class="bubble"><span class="typing"><i></i><i></i><i></i></span>
     <span style="color:#8b96a8;font-size:13px;margin-left:8px">planning query → running SQL → verifying numbers</span></div>`;
  messages.appendChild(el);
  messages.scrollTop = messages.scrollHeight;
  return el;
}

function render(el, d) {
  const conf = d.confidence || {};
  el.className = "msg bot" + (conf.level === "medium" ? " warn" : conf.level === "low" ? " bad" : "");

  const badges = [
    `<span class="badge ${conf.level}">confidence: ${conf.level} (${Math.round((conf.score || 0) * 100)}%)</span>`,
    d.period ? `<span class="badge">${esc(d.period)}</span>` : "",
    d.explain?.matching_records !== undefined
      ? `<span class="badge">${Number(d.explain.matching_records).toLocaleString()} source records</span>`
      : "",
    d.explain?.plan_source ? `<span class="badge">plan: ${esc(d.explain.plan_source)}</span>` : "",
    d.answer_source === "deterministic"
      ? `<span class="badge">wording: computed</span>`
      : `<span class="badge">wording: ${esc(d.usage?.models?.[0] || "model")}</span>`,
    d.usage?.total_tokens
      ? `<span class="badge">${d.usage.total_tokens} tokens · ${d.usage.total_ms} ms</span>`
      : "",
  ].join("");

  let anomalyHtml = "";
  if (d.anomalies && d.anomalies.length) {
    anomalyHtml =
      `<div class="callout"><b>Anomaly check:</b> ` +
      d.anomalies
        .map(
          (a) =>
            `${esc(a.entity)} at ${fmtMoney(a.period_total)} is ${a.times_baseline}× its ` +
            `${a.history_months}-month average of ${fmtMoney(a.baseline_monthly_avg)} (z=${a.z_score})`
        )
        .join("; ") +
      `.</div>`;
  }

  let comparisonHtml = "";
  if (d.comparison) {
    const c = d.comparison;
    comparisonHtml = table(
      ["period", "value", "records"],
      [
        { period: c.current_period, value: c.current_value, records: c.current_records },
        { period: c.previous_period, value: c.previous_value, records: c.previous_records },
        { period: "change", value: c.absolute_change, records: null },
      ]
    );
  }

  const g = d.explain?.guardrail || {};
  const explainHtml = d.explain?.sql
    ? `<details class="explain"><summary>How I got this answer</summary>
        <div class="explain-body">
          <h4>Interpretation</h4>
          <ul class="kv">
            <li>Dataset: <b>${esc(d.explain.dataset)}</b></li>
            <li>Period: <b>${esc(d.period || "all time")}</b> (${esc(d.date_range?.[0] || "start")} → ${esc(d.date_range?.[1] || "end")})</li>
            <li>Matching records: <b>${Number(d.explain.matching_records).toLocaleString()}</b> · query time ${d.explain.query_ms} ms</li>
          </ul>
          ${d.explain.assumptions?.length
            ? `<h4>Assumptions applied</h4><ul class="kv">${d.explain.assumptions.map((a) => `<li>${esc(a)}</li>`).join("")}</ul>`
            : ""}
          ${d.explain.issues?.length
            ? `<h4>Corrections made to the plan</h4><ul class="kv">${d.explain.issues.map((a) => `<li>${esc(a)}</li>`).join("")}</ul>`
            : ""}
          <h4>Query plan (produced by the model)</h4>
          <pre>${esc(JSON.stringify(d.explain.plan, null, 2))}</pre>
          <h4>SQL executed (built in code, not by the model)</h4>
          <pre>${esc(d.explain.sql)}</pre>
          <h4>Hallucination guardrail</h4>
          <ul class="kv">
            <li>${esc(g.policy || "")}</li>
            <li>Status: <b>${g.triggered ? "TRIGGERED — model wording rejected, computed answer shown" : "passed"}</b>
              ${g.rejected_numbers?.length ? `(rejected: ${esc(g.rejected_numbers.join(", "))})` : ""}</li>
          </ul>
          <h4>Why this confidence</h4>
          <ul class="kv">${(conf.reasons || []).map((r) => `<li>${esc(r)}</li>`).join("")}</ul>
          ${d.has_records ? `<h4>Sample of the underlying records</h4><div class="records">loading…</div>` : ""}
        </div>
      </details>`
    : "";

  const exportHtml = d.can_export
    ? `<div class="actions">
         <a href="/api/export?session_id=${encodeURIComponent(d.session_id)}&fmt=csv">Download CSV</a>
         <a href="/api/export?session_id=${encodeURIComponent(d.session_id)}&fmt=xlsx">Download Excel</a>
       </div>`
    : "";

  el.innerHTML = `<div class="bubble">
      <div class="answer">${esc(d.answer)}</div>
      ${anomalyHtml}
      ${table(d.table?.columns || [], d.table?.rows || [])}
      ${comparisonHtml}
      <div class="meta">${badges}</div>
      ${exportHtml}
      ${explainHtml}
    </div>`;

  const details = el.querySelector("details.explain");
  if (details && d.has_records) {
    details.addEventListener(
      "toggle",
      async () => {
        if (!details.open) return;
        const slot = details.querySelector(".records");
        if (!slot || slot.dataset.loaded) return;
        slot.dataset.loaded = "1";
        try {
          const r = await fetch(`/api/records?session_id=${encodeURIComponent(d.session_id)}&limit=10`);
          const rec = await r.json();
          slot.outerHTML = table(rec.columns, rec.rows);
        } catch {
          slot.textContent = "could not load records";
        }
      },
      { once: false }
    );
  }
  messages.scrollTop = messages.scrollHeight;
}

async function ask(question) {
  if (busy || !question.trim()) return;
  busy = true;
  $("#send").disabled = true;
  addUser(question);
  const pending = addPending();
  try {
    const res = await fetch("/api/ask", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question, session_id: sessionId }),
    });
    if (!res.ok) throw new Error((await res.json()).detail || res.statusText);
    const data = await res.json();
    sessionId = data.session_id;
    render(pending, data);
  } catch (e) {
    pending.className = "msg bot bad";
    pending.innerHTML = `<div class="bubble"><div class="answer">Request failed: ${esc(e.message)}</div></div>`;
  } finally {
    busy = false;
    $("#send").disabled = false;
    $("#q").focus();
  }
}

$("#composer").addEventListener("submit", (e) => {
  e.preventDefault();
  const v = $("#q").value;
  $("#q").value = "";
  ask(v);
});

$("#reset").addEventListener("click", async () => {
  if (sessionId) {
    await fetch("/api/reset", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question: "", session_id: sessionId }),
    });
  }
  sessionId = null;
  messages.innerHTML = "";
  showWelcome();
});

function showWelcome() {
  messages.insertAdjacentHTML(
    "beforeend",
    `<div class="empty">
      <h3>Ask anything about payments, counterparties, balances or reconciliation.</h3>
      <p>Answers are computed with SQL over the ledger and checked number-by-number before you see them.
         Follow-up questions keep the context — try “how does that compare to the month before?”</p>
     </div>`
  );
}

async function boot() {
  showWelcome();
  try {
    const [h, s] = await Promise.all([
      fetch("/api/health").then((r) => r.json()),
      fetch("/api/samples").then((r) => r.json()),
    ]);
    const db = h.database || {};
    $("#st-data").textContent = h.status === "ok" ? "connected" : "missing";
    $("#st-records").textContent = db.transactions
      ? `${Number(db.transactions).toLocaleString()} txns · ${Number(db.accounts).toLocaleString()} accounts`
      : "–";
    $("#st-span").textContent = db.date_from ? `${db.date_from} → ${db.date_to}` : "–";
    $("#st-model").textContent = h.llm.model;
    $("#st-mode").textContent = h.llm.reachable ? "LLM planner + narrator" : "rule parser (no LLM)";
    if (db.company) $("#company").textContent = db.company;
    $("#samples").innerHTML = (s.questions || [])
      .map((q) => `<button class="chip">${esc(q)}</button>`)
      .join("");
    document.querySelectorAll(".chip").forEach((c) =>
      c.addEventListener("click", () => ask(c.textContent))
    );
  } catch (e) {
    $("#st-data").textContent = "error";
  }
}

boot();
