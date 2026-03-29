import { api } from "./api.js";

// ── Helpers ─────────────────────────────────────────────
function statusBadge(status) {
    return `<span class="badge badge-${status}">${status.replace(/_/g, " ")}</span>`;
}

function fmt(val) {
    return val == null ? "—" : `$${parseFloat(val).toFixed(2)}`;
}

function showError(el, msg) {
    el.innerHTML = `<div class="alert alert-error">${msg}</div>`;
}

// ── Boot ─────────────────────────────────────────────────
const params  = new URLSearchParams(window.location.search);
const claimId = params.get("id");
const root    = document.getElementById("claim-root");

if (!claimId) {
    root.innerHTML = `<div class="alert alert-error">No claim ID specified in URL.</div>`;
} else {
    loadClaim();
}

async function loadClaim() {
    root.innerHTML = `<div class="skeleton" style="height:80px;margin-bottom:16px"></div>
                      <div class="skeleton" style="height:200px"></div>`;
    try {
        const claim = await api.getClaim(claimId);
        renderClaim(claim);
    } catch (err) {
        root.innerHTML = `<div class="alert alert-error">${err.message}</div>`;
    }
}

// ── Render ───────────────────────────────────────────────
function renderClaim(claim) {
    const activeItems = claim.line_items;

    const totalPlanPays   = activeItems.reduce((s, li) =>
        s + (li.adjudication_result ? parseFloat(li.adjudication_result.plan_pays) : 0), 0);
    const totalMemberOwes = activeItems.reduce((s, li) =>
        s + (li.adjudication_result ? parseFloat(li.adjudication_result.member_owes) : 0), 0);

    root.innerHTML = `
        <!-- Header -->
        <div class="card">
            <div class="claim-header">
                <div class="claim-header__item">
                    <label>Claim ID</label>
                    <span class="value id-mono">${claim.id}</span>
                </div>
                <div class="claim-header__item">
                    <label>Status</label>
                    <span class="value">${statusBadge(claim.status)}</span>
                </div>
                <div class="claim-header__item">
                    <label>Review Type</label>
                    <span class="value">${claim.review_type}</span>
                </div>
                <div class="claim-header__item">
                    <label>Date of Service</label>
                    <span class="value">${claim.date_of_service}</span>
                </div>
                <div class="claim-header__item">
                    <label>Member</label>
                    <span class="value">${claim.member.name}</span>
                </div>
                <div class="claim-header__item">
                    <label>Provider</label>
                    <span class="value">${claim.provider.name}</span>
                </div>
                <div class="claim-header__item">
                    <label>Plan</label>
                    <span class="value">${claim.policy.plan_name}</span>
                </div>
                <div class="claim-header__item">
                    <label>Submitted</label>
                    <span class="value">${new Date(claim.submitted_at).toLocaleString()}</span>
                </div>
            </div>
        </div>

        <!-- Line items -->
        <div class="card">
            <div class="card__title">Line Items</div>
            <div class="table-wrap">
                <table>
                    <thead>
                        <tr>
                            <th>CPT Code</th>
                            <th>Diagnosis</th>
                            <th class="text-right">Billed</th>
                            <th class="text-right">Applied to Ded.</th>
                            <th class="text-right">Plan Pays</th>
                            <th class="text-right">Member Owes</th>
                            <th>Status</th>
                            <th></th>
                        </tr>
                    </thead>
                    <tbody id="line-items-body">
                        ${activeItems.map((li, idx) => renderLineItemRow(li, idx)).join("")}
                        <tr class="table-summary">
                            <td colspan="4" class="text-right">Totals</td>
                            <td class="text-right text-mono">${fmt(totalPlanPays)}</td>
                            <td class="text-right text-mono">${fmt(totalMemberOwes)}</td>
                            <td colspan="2"></td>
                        </tr>
                    </tbody>
                </table>
            </div>
        </div>

        <!-- Conditional sections -->
        <div id="action-sections"></div>
    `;

    // Wire up expand buttons
    root.querySelectorAll(".expand-btn").forEach(btn => {
        btn.addEventListener("click", () => {
            const rowId = btn.dataset.target;
            const row   = document.getElementById(rowId);
            if (row) row.classList.toggle("hidden");
        });
    });

    renderActionSections(claim);
}

function renderLineItemRow(li, idx) {
    const r    = li.adjudication_result;
    const expl = r ? r.explanation : null;
    const rowId = `expl-${idx}`;
    return `
        <tr>
            <td class="text-mono">${li.cpt_code}</td>
            <td class="text-mono">${li.diagnosis_code}</td>
            <td class="text-right text-mono">${fmt(li.billed_amount)}</td>
            <td class="text-right text-mono">${r ? fmt(r.applied_to_deductible) : "—"}</td>
            <td class="text-right text-mono">${r ? fmt(r.plan_pays) : "—"}</td>
            <td class="text-right text-mono">${r ? fmt(r.member_owes) : "—"}</td>
            <td>${statusBadge(li.adjudication_status)}</td>
            <td>${expl ? `<button class="expand-btn" data-target="${rowId}">details</button>` : ""}</td>
        </tr>
        ${expl ? `<tr id="${rowId}" class="explanation-row hidden">
            <td colspan="8">${expl}</td>
        </tr>` : ""}
    `;
}

// ── Action sections ──────────────────────────────────────
function renderActionSections(claim) {
    const container = document.getElementById("action-sections");
    const sections  = [];

    // Payment card (status = paid)
    if (claim.status === "paid" && claim.payment) {
        sections.push(`
            <div class="card">
                <div class="card__title">Payment</div>
                <div class="claim-header">
                    <div class="claim-header__item"><label>Amount</label><span class="value text-mono">${fmt(claim.payment.amount)}</span></div>
                    <div class="claim-header__item"><label>Paid At</label><span class="value">${new Date(claim.payment.paid_at).toLocaleString()}</span></div>
                </div>
            </div>`);
    }

    // Dispute card (denied or partially_approved, no existing dispute)
    if ((claim.status === "denied" || claim.status === "partially_approved") && !claim.dispute) {
        sections.push(`
            <div class="card" id="dispute-card">
                <div class="card__title">Submit Dispute</div>
                <div style="margin-bottom:16px">
                    <div style="font-size:12px;font-weight:600;color:var(--text-muted);margin-bottom:8px">LINE ITEM CORRECTIONS (optional)</div>
                    <div class="table-wrap">
                        <table>
                            <thead>
                                <tr>
                                    <th>CPT Code</th>
                                    <th class="text-right">Billed</th>
                                    <th>Corrected CPT</th>
                                    <th>Corrected Amount</th>
                                </tr>
                            </thead>
                            <tbody>
                                ${claim.line_items.map(li => `
                                    <tr>
                                        <td class="text-mono">${li.cpt_code}</td>
                                        <td class="text-right text-mono">${fmt(li.billed_amount)}</td>
                                        <td><input class="form-control li-cpt-input" data-li-id="${li.id}" placeholder="${li.cpt_code}" style="width:110px"></td>
                                        <td><input class="form-control li-amount-input" data-li-id="${li.id}" type="number" min="0.01" step="0.01" placeholder="${parseFloat(li.billed_amount).toFixed(2)}" style="width:120px"></td>
                                    </tr>`).join("")}
                            </tbody>
                        </table>
                    </div>
                </div>
                <div class="form-group">
                    <label for="dispute-reason">Reason</label>
                    <textarea id="dispute-reason" class="form-control" rows="3"
                        placeholder="Explain why you are disputing this claim…" style="resize:vertical"></textarea>
                </div>
                <div id="dispute-error"></div>
                <div class="form-actions">
                    <button id="submit-dispute-btn" class="btn btn-primary">Submit Dispute</button>
                </div>
            </div>`);
    }

    // Show existing dispute
    if (claim.dispute) {
        sections.push(`
            <div class="card">
                <div class="card__title">Dispute</div>
                <div class="claim-header">
                    <div class="claim-header__item"><label>Status</label><span class="value">${statusBadge(claim.dispute.status)}</span></div>
                    <div class="claim-header__item"><label>Submitted</label><span class="value">${new Date(claim.dispute.submitted_at).toLocaleString()}</span></div>
                    ${claim.dispute.resolved_at ? `<div class="claim-header__item"><label>Resolved</label><span class="value">${new Date(claim.dispute.resolved_at).toLocaleString()}</span></div>` : ""}
                </div>
                <div style="margin-top:10px">
                    <div style="font-size:12px;font-weight:600;color:var(--text-muted);margin-bottom:4px">REASON</div>
                    <div>${claim.dispute.reason}</div>
                </div>
                ${claim.dispute.line_item_updates && claim.dispute.line_item_updates.length > 0 ? `
                <div style="margin-top:10px">
                    <div style="font-size:12px;font-weight:600;color:var(--text-muted);margin-bottom:4px">MEMBER CORRECTIONS</div>
                    <div class="table-wrap">
                        <table>
                            <thead><tr><th>Line Item</th><th>Corrected CPT</th><th>Corrected Amount</th></tr></thead>
                            <tbody>
                                ${claim.dispute.line_item_updates.map(u => `
                                    <tr>
                                        <td class="id-mono">${u.line_item_id.slice(0, 8)}…</td>
                                        <td class="text-mono">${u.cpt_code ?? "—"}</td>
                                        <td class="text-mono">${u.billed_amount != null ? fmt(u.billed_amount) : "—"}</td>
                                    </tr>`).join("")}
                            </tbody>
                        </table>
                    </div>
                </div>` : ""}
                ${claim.dispute.reviewer_note ? `
                <div style="margin-top:10px">
                    <div style="font-size:12px;font-weight:600;color:var(--text-muted);margin-bottom:4px">REVIEWER NOTE</div>
                    <div>${claim.dispute.reviewer_note}</div>
                </div>` : ""}
            </div>`);
    }

    // Accept payment button (partially_approved, no dispute)
    if (claim.status === "partially_approved" && !claim.dispute) {
        sections.push(`
            <div class="card" id="accept-card">
                <div class="card__title">Accept Partial Payment</div>
                <p style="margin-bottom:12px;color:var(--text-muted);font-size:13px">
                    Accept the partial payment and mark this claim as paid.
                </p>
                <div id="accept-error"></div>
                <button id="accept-btn" class="btn btn-primary">Accept Payment</button>
            </div>`);
    }

    container.innerHTML = sections.join("");

    // Wire dispute submit
    const disputeBtn = document.getElementById("submit-dispute-btn");
    if (disputeBtn) {
        disputeBtn.addEventListener("click", async () => {
            const reason = document.getElementById("dispute-reason").value.trim();
            const errEl  = document.getElementById("dispute-error");
            if (!reason) { showError(errEl, "Reason is required."); return; }

            const liIds = [...new Set(
                [...document.querySelectorAll("[data-li-id]")].map(el => el.dataset.liId)
            )];
            const lineItemUpdates = [];
            for (const liId of liIds) {
                const cptVal    = document.querySelector(`.li-cpt-input[data-li-id="${liId}"]`).value.trim();
                const amountVal = document.querySelector(`.li-amount-input[data-li-id="${liId}"]`).value.trim();
                if (cptVal || amountVal) {
                    const entry = { line_item_id: liId };
                    if (cptVal) entry.cpt_code = cptVal;
                    if (amountVal) entry.billed_amount = amountVal;
                    lineItemUpdates.push(entry);
                }
            }

            disputeBtn.disabled = true;
            disputeBtn.textContent = "Submitting…";
            try {
                await api.submitDispute(claim.id, reason, lineItemUpdates.length ? lineItemUpdates : null);
                loadClaim();
            } catch (err) {
                showError(errEl, err.message);
                disputeBtn.disabled = false;
                disputeBtn.textContent = "Submit Dispute";
            }
        });
    }

    // Wire accept payment
    const acceptBtn = document.getElementById("accept-btn");
    if (acceptBtn) {
        acceptBtn.addEventListener("click", async () => {
            const errEl = document.getElementById("accept-error");
            acceptBtn.disabled = true;
            acceptBtn.textContent = "Processing…";
            try {
                await api.acceptPayment(claim.id);
                loadClaim();
            } catch (err) {
                showError(errEl, err.message);
                acceptBtn.disabled = false;
                acceptBtn.textContent = "Accept Payment";
            }
        });
    }
}
