// KYC report generator — all 21 doc types listed; main 5 required, rest optional.
const KYC = (() => {
  const MAIN = [
    { key: "trade_license", label: "Trade License" },
    { key: "moa",           label: "Memorandum of Association (MOA)" },
    { key: "ejari",         label: "Ejari" },
    { key: "passport",      label: "Passport" },
    { key: "emirates_id",   label: "Emirates ID" },
  ];
  const OPTIONAL = [
    { key: "free_zone_license",            label: "Free Zone License" },
    { key: "partners_annex",               label: "Partners Annex" },
    { key: "residence_visa",               label: "Residence Visa" },
    { key: "vat_certificate",              label: "VAT Certificate" },
    { key: "insurance",                    label: "Insurance" },
    { key: "board_resolution",             label: "Board Resolution" },
    { key: "poa",                          label: "Power of Attorney" },
    { key: "certificate_of_incorporation", label: "Certificate of Incorporation" },
    { key: "certificate_of_good_standing", label: "Certificate of Good Standing" },
    { key: "register_of_shareholders",     label: "Register of Shareholders" },
    { key: "register_of_directors",        label: "Register of Directors" },
    { key: "dcci_membership",              label: "DCCI Membership" },
    { key: "renewal_receipt",              label: "Renewal Receipt" },
    { key: "audited_financials",           label: "Audited Financials" },
    { key: "ubo_declaration",              label: "UBO Declaration" },
    { key: "specimen_signatures",          label: "Specimen Signatures" },
  ];

  let lastSession = null;
  let lastExtracted = null;
  let lastDocxBase64 = null;
  let lastFilename = null;

  const $ = (id) => document.getElementById(id);

  function buildSlot({ key, label, optional }) {
    const slot = document.createElement("div");
    slot.className = "slot";
    slot.dataset.key = key;
    slot.innerHTML = `
      <div class="slot-label">
        ${label}
        ${optional ? `<span class="slot-tag">Optional</span>` : ""}
      </div>
      <div class="file-list"></div>
      <div class="slot-controls">
        <button class="slot-action" type="button">Choose file(s)</button>
      </div>
      <input type="file" multiple accept=".pdf,.jpg,.jpeg,.png,.webp" />`;
    Uploads.attach(slot, { multi: true });
    return slot;
  }

  function buildAllSlots() {
    const grid = $("kyc-slots");
    grid.innerHTML = "";
    MAIN.forEach((d) => grid.appendChild(buildSlot({ ...d, optional: false })));
    const divider = document.createElement("div");
    divider.className = "slot-divider";
    divider.textContent = "Optional documents";
    grid.appendChild(divider);
    OPTIONAL.forEach((d) => grid.appendChild(buildSlot({ ...d, optional: true })));
  }

  function collectFormData() {
    const fd = new FormData();
    let total = 0;
    document.querySelectorAll("#kyc-slots .slot").forEach((slot) => {
      (slot._files || []).forEach((f) => { fd.append(slot.dataset.key, f); total++; });
    });
    return { fd, total };
  }

  function showError(msg) {
    const el = $("kyc-error");
    el.textContent = msg; el.classList.remove("hidden");
  }
  function clearError() { $("kyc-error").classList.add("hidden"); }

  function busy(btn, on, label) {
    btn.disabled = on;
    if (on) btn.innerHTML = `<span class="spinner"></span> ${label}`;
    else btn.textContent = label;
  }

  async function submit() {
    clearError();
    const { fd, total } = collectFormData();
    if (total === 0) { showError("Upload at least one document."); return; }

    const btn = $("kyc-submit");
    busy(btn, true, "Generating…");
    $("kyc-status").textContent = "Extracting fields and analysing compliance — this can take 30-60 seconds.";
    $("kyc-result").classList.add("hidden");
    $("partner-block").classList.add("hidden");

    try {
      const res = await Api.post("/generate-kyc", fd);
      $("kyc-status").textContent = "";
      if (res.needs_partner_docs) {
        lastSession = res.session_id;
        lastExtracted = res.extracted_data;
        renderPartnerBlock(res.partners || []);
      } else {
        renderResult(res);
      }
    } catch (err) {
      showError(err.message || "Could not generate report.");
      $("kyc-status").textContent = "";
    } finally {
      busy(btn, false, "Generate KYC Report");
    }
  }

  function renderPartnerBlock(partners) {
    const list = $("partner-list");
    list.innerHTML = "";
    partners.forEach((p, idx) => {
      const card = document.createElement("div");
      card.className = "partner-card";
      const have = [];
      if (p.has_passport) have.push("passport");
      if (p.has_emirates_id) have.push("EID");
      if (p.has_residence_visa) have.push("visa");
      card.innerHTML = `
        <div class="partner-head">
          <h3>${p.name || `Partner ${idx + 1}`}</h3>
          <small>${p.share_percentage || ""} ${p.nationality ? "· " + p.nationality : ""}</small>
        </div>
        ${have.length ? `<div class="muted" style="margin-bottom: 8px; font-size: 12px;">Already have: ${have.join(", ")}</div>` : ""}
        <div class="slot-grid" data-partner="${idx}">
          ${["passport","emirates_id","residence_visa"].filter(k => !p[`has_${k}`]).map(k => `
            <div class="slot" data-key="partner_${idx}_${k}">
              <div class="slot-label">${k === "emirates_id" ? "Emirates ID" : k === "residence_visa" ? "Residence Visa" : "Passport"}</div>
              <div class="file-list"></div>
              <div class="slot-controls">
                <button class="slot-action" type="button">Choose file(s)</button>
              </div>
              <input type="file" multiple accept=".pdf,.jpg,.jpeg,.png,.webp" />
            </div>`).join("")}
        </div>`;
      list.appendChild(card);
    });
    list.querySelectorAll(".slot").forEach((s) => Uploads.attach(s, { multi: true }));
    $("partner-block").classList.remove("hidden");
    $("partner-block").scrollIntoView({ behavior: "smooth", block: "start" });
  }

  async function submitPartners() {
    const btn = $("partner-submit");
    busy(btn, true, "Completing…");
    $("partner-status").textContent = "Extracting partner documents…";

    const fd = new FormData();
    fd.append("session_id", lastSession);
    fd.append("extracted_json", btoa(unescape(encodeURIComponent(JSON.stringify(lastExtracted)))));
    let any = false;
    document.querySelectorAll("#partner-list .slot").forEach((slot) => {
      (slot._files || []).forEach((f) => { fd.append(slot.dataset.key, f); any = true; });
    });
    if (!any) {
      busy(btn, false, "Complete KYC Report");
      $("partner-status").textContent = "";
      showError("Upload at least one partner document.");
      return;
    }
    try {
      const res = await Api.post("/generate-kyc-complete", fd);
      $("partner-status").textContent = "";
      $("partner-block").classList.add("hidden");
      renderResult(res);
    } catch (err) {
      showError(err.message || "Could not complete report.");
      $("partner-status").textContent = "";
    } finally {
      busy(btn, false, "Complete KYC Report");
    }
  }

  function renderResult(res) {
    lastDocxBase64 = res.docx;
    lastFilename = res.filename || "kyc_report.docx";
    const kv = $("kyc-result-kv");
    kv.innerHTML = "";
    const rows = [
      ["File", lastFilename],
      ["NAS folder", res.nas_folder || "(not archived)"],
      ["Company",  res.report?.company?.name || "—"],
      ["Generated", new Date().toLocaleString()],
    ];
    rows.forEach(([k, v]) => {
      const dt = document.createElement("dt"); dt.textContent = k;
      const dd = document.createElement("dd"); dd.textContent = v;
      kv.appendChild(dt); kv.appendChild(dd);
    });
    $("kyc-result").classList.remove("hidden");
    $("kyc-result").scrollIntoView({ behavior: "smooth", block: "start" });
  }

  function downloadDocx() {
    if (!lastDocxBase64) return;
    const bin = atob(lastDocxBase64);
    const buf = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) buf[i] = bin.charCodeAt(i);
    const blob = new Blob([buf], { type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url; a.download = lastFilename; a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  function clearAll() {
    document.querySelectorAll("#kyc-slots .slot").forEach((s) => s._reset && s._reset());
    $("kyc-result").classList.add("hidden");
    $("partner-block").classList.add("hidden");
    clearError();
  }

  function init() {
    buildAllSlots();
    $("kyc-submit").addEventListener("click", submit);
    $("kyc-clear").addEventListener("click", clearAll);
    $("kyc-download").addEventListener("click", downloadDocx);
    $("partner-submit").addEventListener("click", submitPartners);
  }

  return { init };
})();
