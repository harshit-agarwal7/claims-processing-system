import { api } from "./api.js";

// ── State ──────────────────────────────────────────────
let currentMember = null;

// ── Helpers ────────────────────────────────────────────
function statusBadge(status) {
    return `<span class="badge badge-${status}">${status.replace(/_/g, " ")}</span>`;
}

function showError(el, msg) {
    el.innerHTML = `<div class="alert alert-error">${msg}</div>`;
}

function fmt(val) {
    return val == null ? "—" : `$${parseFloat(val).toFixed(2)}`;
}

// ── Member lookup ───────────────────────────────────────
const memberInput = document.getElementById("member-input");
const loadBtn     = document.getElementById("load-btn");
const memberCard  = document.getElementById("member-card");
const claimsSection = document.getElementById("claims-section");
const newClaimBtn = document.getElementById("new-claim-btn");

async function loadMember() {
    const val = memberInput.value.trim();
    if (!val) return;
    memberCard.innerHTML = `<span class="skeleton" style="width:200px;height:14px"></span>`;
    memberCard.classList.remove("hidden");
    claimsSection.classList.add("hidden");
    newClaimBtn.classList.add("hidden");

    try {
        let member;
        if (val.includes("@")) {
            member = await api.lookupMemberByEmail(val);
        } else {
            member = await api.getMember(val);
        }
        currentMember = member;
        renderMemberCard(member);
        await loadClaims(member.id);
        newClaimBtn.classList.remove("hidden");
    } catch (err) {
        showError(memberCard, err.message);
        currentMember = null;
        claimsSection.classList.add("hidden");
    }
}

function renderMemberCard(m) {
    memberCard.innerHTML = `
        <div style="display:flex;align-items:center;gap:24px;flex-wrap:wrap">
            <div>
                <div style="font-size:16px;font-weight:700">${m.name}</div>
                <div class="id-mono">${m.id}</div>
            </div>
            <div class="claim-header" style="flex:1;min-width:0">
                <div class="claim-header__item"><label>Email</label><span class="value">${m.email}</span></div>
                <div class="claim-header__item"><label>DOB</label><span class="value">${m.date_of_birth}</span></div>
                ${m.phone ? `<div class="claim-header__item"><label>Phone</label><span class="value">${m.phone}</span></div>` : ""}
            </div>
        </div>`;
}

loadBtn.addEventListener("click", loadMember);
memberInput.addEventListener("keydown", (e) => { if (e.key === "Enter") loadMember(); });

// ── Claims table ────────────────────────────────────────
const claimsBody  = document.getElementById("claims-body");
const claimsError = document.getElementById("claims-error");

async function loadClaims(memberId) {
    claimsSection.classList.remove("hidden");
    claimsError.innerHTML = "";
    claimsBody.innerHTML = `<tr><td colspan="6"><span class="skeleton" style="width:100%;display:block"></span></td></tr>`;

    try {
        const claims = await api.getMemberClaims(memberId);
        renderClaimsTable(claims);
    } catch (err) {
        claimsBody.innerHTML = "";
        showError(claimsError, err.message);
    }
}

function renderClaimsTable(claims) {
    if (claims.length === 0) {
        claimsBody.innerHTML = `<tr><td colspan="6"><div class="empty-state">No claims found for this member.</div></td></tr>`;
        return;
    }
    claimsBody.innerHTML = claims.map(c => `
        <tr>
            <td><a href="/claim?id=${c.id}" class="text-mono">${c.id.slice(0, 8)}…</a></td>
            <td>${c.date_of_service}</td>
            <td>${statusBadge(c.status)}</td>
            <td>${c.provider_name}</td>
            <td class="text-right text-mono">${fmt(c.total_billed)}</td>
            <td class="text-right text-mono">${fmt(c.total_plan_pays)}</td>
        </tr>`).join("");
}

// ── New Claim Modal ─────────────────────────────────────
const modalOverlay   = document.getElementById("modal-overlay");
const modalCloseBtn  = document.getElementById("modal-close");
const claimForm      = document.getElementById("claim-form");
const lineItemsWrap  = document.getElementById("line-items-wrap");
const addLineItemBtn = document.getElementById("add-line-item");
const claimFormError = document.getElementById("claim-form-error");
const submitClaimBtn = document.getElementById("submit-claim-btn");
const providerSelect = document.getElementById("provider-id");

newClaimBtn.addEventListener("click", openModal);
modalCloseBtn.addEventListener("click", closeModal);
modalOverlay.addEventListener("click", (e) => { if (e.target === modalOverlay) closeModal(); });

async function openModal() {
    claimFormError.innerHTML = "";
    claimForm.reset();
    renderLineItems();
    modalOverlay.classList.remove("hidden");

    // Populate provider dropdown
    providerSelect.innerHTML = `<option value="">Loading providers…</option>`;
    try {
        const providers = await api.listProviders();
        if (providers.length === 0) {
            providerSelect.innerHTML = `<option value="">No providers found</option>`;
        } else {
            providerSelect.innerHTML = `<option value="">Select provider…</option>` +
                providers.map(p => `<option value="${p.id}">${p.name} (${p.npi})</option>`).join("");
        }
    } catch {
        providerSelect.innerHTML = `<option value="">Failed to load providers</option>`;
    }
}

function closeModal() {
    modalOverlay.classList.add("hidden");
}

// ── Line items ──────────────────────────────────────────
let lineItems = [{ cpt_code: "", diagnosis_code: "", billed_amount: "" }];

function renderLineItems() {
    lineItemsWrap.innerHTML = lineItems.map((item, i) => `
        <div class="line-item-row" data-index="${i}">
            <div class="form-group">
                ${i === 0 ? "<label>CPT Code</label>" : ""}
                <input class="form-control" placeholder="e.g. 99213" value="${item.cpt_code}"
                    oninput="window._liUpdate(${i},'cpt_code',this.value)">
            </div>
            <div class="form-group">
                ${i === 0 ? "<label>Diagnosis Code</label>" : ""}
                <input class="form-control" placeholder="e.g. Z00.00" value="${item.diagnosis_code}"
                    oninput="window._liUpdate(${i},'diagnosis_code',this.value)">
            </div>
            <div class="form-group">
                ${i === 0 ? "<label>Billed Amount</label>" : ""}
                <input class="form-control" placeholder="0.00" type="number" min="0" step="0.01" value="${item.billed_amount}"
                    oninput="window._liUpdate(${i},'billed_amount',this.value)">
            </div>
            <button type="button" class="btn btn-outline btn-sm" onclick="window._liRemove(${i})"
                ${lineItems.length === 1 ? "disabled" : ""}>✕</button>
        </div>`).join("");
}

window._liUpdate = (i, field, val) => { lineItems[i][field] = val; };
window._liRemove = (i) => { if (lineItems.length > 1) { lineItems.splice(i, 1); renderLineItems(); } };
addLineItemBtn.addEventListener("click", () => {
    lineItems.push({ cpt_code: "", diagnosis_code: "", billed_amount: "" });
    renderLineItems();
});

// ── Submit claim ────────────────────────────────────────
claimForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    if (!currentMember) return;

    claimFormError.innerHTML = "";
    submitClaimBtn.disabled = true;
    submitClaimBtn.textContent = "Submitting…";

    const providerId = providerSelect.value;
    const dateOfService = document.getElementById("date-of-service").value;

    if (!providerId || !dateOfService) {
        showError(claimFormError, "Provider and date of service are required.");
        submitClaimBtn.disabled = false;
        submitClaimBtn.textContent = "Submit Claim";
        return;
    }

    const items = lineItems.map(li => ({
        cpt_code: li.cpt_code.trim(),
        diagnosis_code: li.diagnosis_code.trim(),
        billed_amount: parseFloat(li.billed_amount),
    }));

    if (items.some(li => !li.cpt_code || !li.diagnosis_code || isNaN(li.billed_amount))) {
        showError(claimFormError, "All line items must have CPT code, diagnosis code, and billed amount.");
        submitClaimBtn.disabled = false;
        submitClaimBtn.textContent = "Submit Claim";
        return;
    }

    try {
        const claim = await api.submitClaim({
            member_id: currentMember.id,
            provider_id: providerId,
            date_of_service: dateOfService,
            line_items: items,
        });
        closeModal();
        lineItems = [{ cpt_code: "", diagnosis_code: "", billed_amount: "" }];
        // Navigate to claim detail
        window.location.href = `/claim?id=${claim.id}`;
    } catch (err) {
        showError(claimFormError, err.message);
        submitClaimBtn.disabled = false;
        submitClaimBtn.textContent = "Submit Claim";
    }
});
