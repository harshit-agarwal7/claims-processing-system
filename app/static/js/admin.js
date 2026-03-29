import { api } from "./api.js";

// ── Helpers ─────────────────────────────────────────────
function showError(el, msg) {
    el.innerHTML = `<div class="alert alert-error">${msg}</div>`;
}
function showSuccess(el, msg) {
    el.innerHTML = `<div class="alert alert-success">${msg}</div>`;
    setTimeout(() => { el.innerHTML = ""; }, 3000);
}

// ── Tabs ─────────────────────────────────────────────────
document.querySelectorAll(".tab-btn").forEach(btn => {
    btn.addEventListener("click", () => {
        document.querySelectorAll(".tab-btn").forEach(b => b.classList.remove("active"));
        document.querySelectorAll(".tab-panel").forEach(p => p.classList.remove("active"));
        btn.classList.add("active");
        document.getElementById(btn.dataset.tab).classList.add("active");
    });
});

// ════════════════════════════════════════════════════════
// Plans tab
// ════════════════════════════════════════════════════════
const plansList     = document.getElementById("plans-list");
const planFormError = document.getElementById("plan-form-error");
const planFormMsg   = document.getElementById("plan-form-msg");
const createPlanBtn = document.getElementById("create-plan-btn");

async function loadPlans() {
    plansList.innerHTML = `<div class="skeleton" style="height:80px"></div>`;
    try {
        const plans = await api.listPlans();
        renderPlansList(plans);
    } catch (err) {
        showError(plansList, err.message);
    }
}

function renderPlansList(plans) {
    if (plans.length === 0) {
        plansList.innerHTML = `<div class="empty-state">No plans yet.</div>`;
        return;
    }
    plansList.innerHTML = plans.map(p => renderPlanCard(p)).join("");
    // Wire rule forms
    plans.forEach(p => wirePlanCard(p));
}

function renderPlanCard(plan) {
    const rules = plan.coverage_rules;
    return `
        <div class="card" style="margin-bottom:12px" id="plan-card-${plan.id}">
            <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:10px;flex-wrap:wrap;gap:8px">
                <div>
                    <strong>${plan.name}</strong>
                    <span class="id-mono" style="margin-left:8px">${plan.id.slice(0, 8)}…</span>
                </div>
                <div style="color:var(--text-muted);font-size:13px">Deductible: <strong>$${parseFloat(plan.deductible).toFixed(2)}</strong></div>
            </div>

            <!-- Coverage rules table -->
            <div class="table-wrap" style="margin-bottom:12px">
                <table>
                    <thead>
                        <tr>
                            <th>CPT Code</th>
                            <th>Covered</th>
                            <th>Coverage %</th>
                            <th></th>
                        </tr>
                    </thead>
                    <tbody id="rules-body-${plan.id}">
                        ${rules.length === 0
                            ? `<tr><td colspan="4"><em style="color:var(--text-muted)">No rules yet.</em></td></tr>`
                            : rules.map(r => renderRuleRow(plan.id, r)).join("")}
                    </tbody>
                </table>
            </div>

            <!-- Add/edit rule form -->
            <details>
                <summary style="cursor:pointer;font-size:13px;color:var(--primary);margin-bottom:10px">+ Add / Edit Coverage Rule</summary>
                <div class="form-row-3" style="margin-top:10px">
                    <div class="form-group">
                        <label>CPT Code</label>
                        <input id="rule-cpt-${plan.id}" class="form-control" placeholder="e.g. 99213">
                    </div>
                    <div class="form-group">
                        <label>Covered?</label>
                        <select id="rule-covered-${plan.id}" class="form-control">
                            <option value="true">Yes</option>
                            <option value="false">No</option>
                        </select>
                    </div>
                    <div class="form-group">
                        <label>Coverage % (0–1)</label>
                        <input id="rule-pct-${plan.id}" class="form-control" type="number" min="0" max="1" step="0.01" placeholder="e.g. 0.8">
                    </div>
                </div>
                <div id="rule-error-${plan.id}"></div>
                <button class="btn btn-primary btn-sm upsert-rule-btn" data-plan="${plan.id}">Save Rule</button>
            </details>
        </div>`;
}

function renderRuleRow(planId, rule) {
    return `
        <tr>
            <td class="text-mono">${rule.cpt_code}</td>
            <td>${rule.is_covered ? "✓ Yes" : "✗ No"}</td>
            <td>${(parseFloat(rule.coverage_percentage) * 100).toFixed(0)}%</td>
            <td>
                <button class="btn btn-outline btn-sm delete-rule-btn"
                    data-plan="${planId}" data-cpt="${rule.cpt_code}">Delete</button>
            </td>
        </tr>`;
}

function wirePlanCard(plan) {
    // Upsert rule
    const card = document.getElementById(`plan-card-${plan.id}`);
    if (!card) return;

    card.querySelectorAll(".upsert-rule-btn").forEach(btn => {
        btn.addEventListener("click", async () => {
            const pid     = btn.dataset.plan;
            const cpt     = document.getElementById(`rule-cpt-${pid}`).value.trim();
            const covered = document.getElementById(`rule-covered-${pid}`).value === "true";
            const pct     = document.getElementById(`rule-pct-${pid}`).value;
            const errEl   = document.getElementById(`rule-error-${pid}`);

            if (!cpt || !pct) { showError(errEl, "CPT code and coverage % are required."); return; }

            btn.disabled = true;
            try {
                await api.upsertCoverageRule(pid, cpt, { is_covered: covered, coverage_percentage: parseFloat(pct) });
                await loadPlans();
            } catch (err) {
                showError(errEl, err.message);
                btn.disabled = false;
            }
        });
    });

    // Delete rule
    card.querySelectorAll(".delete-rule-btn").forEach(btn => {
        btn.addEventListener("click", async () => {
            if (!confirm(`Delete coverage rule for CPT ${btn.dataset.cpt}?`)) return;
            btn.disabled = true;
            try {
                await api.deleteCoverageRule(btn.dataset.plan, btn.dataset.cpt);
                await loadPlans();
            } catch (err) {
                alert(err.message);
                btn.disabled = false;
            }
        });
    });
}

createPlanBtn.addEventListener("click", async () => {
    const name        = document.getElementById("plan-name").value.trim();
    const deductible  = document.getElementById("plan-deductible").value;
    planFormError.innerHTML = "";

    if (!name || !deductible) { showError(planFormError, "Name and deductible are required."); return; }

    createPlanBtn.disabled = true;
    createPlanBtn.textContent = "Creating…";
    try {
        await api.createPlan({ name, deductible: parseFloat(deductible) });
        showSuccess(planFormMsg, `Plan "${name}" created.`);
        document.getElementById("plan-name").value = "";
        document.getElementById("plan-deductible").value = "";
        await loadPlans();
    } catch (err) {
        showError(planFormError, err.message);
    } finally {
        createPlanBtn.disabled = false;
        createPlanBtn.textContent = "Create Plan";
    }
});

// ════════════════════════════════════════════════════════
// Providers tab
// ════════════════════════════════════════════════════════
const providersList     = document.getElementById("providers-list");
const providerFormError = document.getElementById("provider-form-error");
const providerFormMsg   = document.getElementById("provider-form-msg");
const createProviderBtn = document.getElementById("create-provider-btn");

async function loadProviders() {
    providersList.innerHTML = `<div class="skeleton" style="height:60px"></div>`;
    try {
        const providers = await api.listProviders();
        if (providers.length === 0) {
            providersList.innerHTML = `<div class="empty-state">No providers yet.</div>`;
        } else {
            providersList.innerHTML = `
                <div class="table-wrap">
                    <table>
                        <thead><tr><th>Name</th><th>NPI</th><th>Type</th><th>ID</th></tr></thead>
                        <tbody>
                            ${providers.map(p => `
                                <tr>
                                    <td>${p.name}</td>
                                    <td class="text-mono">${p.npi}</td>
                                    <td>${p.provider_type}</td>
                                    <td class="id-mono">${p.id.slice(0,8)}…</td>
                                </tr>`).join("")}
                        </tbody>
                    </table>
                </div>`;
        }
    } catch (err) {
        showError(providersList, err.message);
    }
}

createProviderBtn.addEventListener("click", async () => {
    const name         = document.getElementById("provider-name").value.trim();
    const npi          = document.getElementById("provider-npi").value.trim();
    const providerType = document.getElementById("provider-type").value;
    providerFormError.innerHTML = "";

    if (!name || !npi) { showError(providerFormError, "Name and NPI are required."); return; }

    createProviderBtn.disabled = true;
    createProviderBtn.textContent = "Creating…";
    try {
        await api.createProvider({ name, npi, provider_type: providerType });
        showSuccess(providerFormMsg, `Provider "${name}" created.`);
        document.getElementById("provider-name").value = "";
        document.getElementById("provider-npi").value = "";
        await loadProviders();
    } catch (err) {
        showError(providerFormError, err.message);
    } finally {
        createProviderBtn.disabled = false;
        createProviderBtn.textContent = "Create Provider";
    }
});

// ════════════════════════════════════════════════════════
// Policies tab
// ════════════════════════════════════════════════════════
const policyFormError = document.getElementById("policy-form-error");
const policyFormMsg   = document.getElementById("policy-form-msg");
const createPolicyBtn = document.getElementById("create-policy-btn");
const planSelect      = document.getElementById("policy-plan-id");
const memberLookupBtn = document.getElementById("member-lookup-btn");
const memberLookupResult = document.getElementById("member-lookup-result");
const memberPoliciesList = document.getElementById("member-policies-list");
let policyMemberId = null;

function renderMemberPolicies(policies) {
    if (policies.length === 0) {
        memberPoliciesList.innerHTML = `<div class="empty-state" style="font-size:13px">No existing policies for this member.</div>`;
        return;
    }
    memberPoliciesList.innerHTML = `
        <div style="font-size:13px;font-weight:600;margin-bottom:6px;color:var(--text-muted)">Existing Policies</div>
        <div class="table-wrap">
            <table>
                <thead><tr><th>Plan</th><th>Status</th><th>Start</th><th>End</th></tr></thead>
                <tbody>
                    ${policies.map(p => `
                        <tr>
                            <td>${p.plan_name}</td>
                            <td>${p.status}</td>
                            <td>${p.start_date}</td>
                            <td>${p.end_date}</td>
                        </tr>`).join("")}
                </tbody>
            </table>
        </div>`;
}

memberLookupBtn.addEventListener("click", async () => {
    const val = document.getElementById("policy-member-input").value.trim();
    if (!val) return;
    memberLookupResult.innerHTML = "";
    memberPoliciesList.innerHTML = "";
    policyMemberId = null;
    try {
        let member;
        if (val.includes("@")) {
            member = await api.lookupMemberByEmail(val);
        } else {
            member = await api.getMember(val);
        }
        policyMemberId = member.id;
        memberLookupResult.innerHTML = `<div class="alert alert-info">Found: <strong>${member.name}</strong> <span class="id-mono">${member.id}</span></div>`;
        const policies = await api.listMemberPolicies(member.id);
        renderMemberPolicies(policies);
    } catch (err) {
        showError(memberLookupResult, err.message);
    }
});

async function populatePlanSelect() {
    planSelect.innerHTML = `<option value="">Loading plans…</option>`;
    try {
        const plans = await api.listPlans();
        planSelect.innerHTML = `<option value="">Select plan…</option>` +
            plans.map(p => `<option value="${p.id}">${p.name} (ded. $${parseFloat(p.deductible).toFixed(2)})</option>`).join("");
    } catch {
        planSelect.innerHTML = `<option value="">Failed to load plans</option>`;
    }
}

createPolicyBtn.addEventListener("click", async () => {
    const planId    = planSelect.value;
    const startDate = document.getElementById("policy-start").value;
    const endDate   = document.getElementById("policy-end").value;
    policyFormError.innerHTML = "";

    if (!policyMemberId)  { showError(policyFormError, "Look up a member first."); return; }
    if (!planId)          { showError(policyFormError, "Select a plan."); return; }
    if (!startDate || !endDate) { showError(policyFormError, "Start and end dates are required."); return; }

    createPolicyBtn.disabled = true;
    createPolicyBtn.textContent = "Creating…";
    try {
        await api.createPolicy({ member_id: policyMemberId, plan_id: planId, start_date: startDate, end_date: endDate });
        showSuccess(policyFormMsg, "Policy created successfully.");
        policyMemberId = null;
        memberLookupResult.innerHTML = "";
        memberPoliciesList.innerHTML = "";
        document.getElementById("policy-member-input").value = "";
        planSelect.value = "";
        document.getElementById("policy-start").value = "";
        document.getElementById("policy-end").value = "";
    } catch (err) {
        showError(policyFormError, err.message);
    } finally {
        createPolicyBtn.disabled = false;
        createPolicyBtn.textContent = "Create Policy";
    }
});

// ════════════════════════════════════════════════════════
// Members tab
// ════════════════════════════════════════════════════════
const membersList     = document.getElementById("members-list");
const memberFormError = document.getElementById("member-form-error");
const memberFormMsg   = document.getElementById("member-form-msg");
const createMemberBtn = document.getElementById("create-member-btn");

async function loadMembers() {
    membersList.innerHTML = `<div class="skeleton" style="height:60px"></div>`;
    try {
        const members = await api.listMembers();
        if (members.length === 0) {
            membersList.innerHTML = `<div class="empty-state">No members yet.</div>`;
        } else {
            membersList.innerHTML = `
                <div class="table-wrap">
                    <table>
                        <thead><tr><th>Name</th><th>Email</th><th>Date of Birth</th><th>Phone</th><th>ID</th></tr></thead>
                        <tbody>
                            ${members.map(m => `
                                <tr>
                                    <td>${m.name}</td>
                                    <td>${m.email}</td>
                                    <td>${m.date_of_birth}</td>
                                    <td>${m.phone ?? "—"}</td>
                                    <td class="id-mono">${m.id.slice(0, 8)}…</td>
                                </tr>`).join("")}
                        </tbody>
                    </table>
                </div>`;
        }
    } catch (err) {
        showError(membersList, err.message);
    }
}

createMemberBtn.addEventListener("click", async () => {
    const name  = document.getElementById("member-name").value.trim();
    const dob   = document.getElementById("member-dob").value;
    const email = document.getElementById("member-email").value.trim();
    const phone = document.getElementById("member-phone").value.trim();
    memberFormError.innerHTML = "";

    if (!name || !dob || !email) { showError(memberFormError, "Name, date of birth, and email are required."); return; }

    createMemberBtn.disabled = true;
    createMemberBtn.textContent = "Creating…";
    try {
        await api.createMember({ name, date_of_birth: dob, email, phone: phone || null });
        showSuccess(memberFormMsg, `Member "${name}" created.`);
        document.getElementById("member-name").value = "";
        document.getElementById("member-dob").value = "";
        document.getElementById("member-email").value = "";
        document.getElementById("member-phone").value = "";
        await loadMembers();
    } catch (err) {
        showError(memberFormError, err.message);
    } finally {
        createMemberBtn.disabled = false;
        createMemberBtn.textContent = "Create Member";
    }
});

// ════════════════════════════════════════════════════════
// Disputes tab
// ════════════════════════════════════════════════════════
const disputesList = document.getElementById("disputes-list");

async function loadDisputes() {
    disputesList.innerHTML = `<div class="skeleton" style="height:60px"></div>`;
    try {
        const claims = await api.listDisputedClaims();
        if (claims.length === 0) {
            disputesList.innerHTML = `<div class="empty-state">No pending disputes.</div>`;
            return;
        }
        disputesList.innerHTML = claims.map(c => renderDisputeCard(c)).join("");
        claims.forEach(c => wireDisputeCard(c));
    } catch (err) {
        showError(disputesList, err.message);
    }
}

function renderDisputeCard(claim) {
    const d = claim.dispute;
    return `
        <div class="card" style="margin-bottom:12px" id="dispute-card-${claim.id}">
            <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:10px;flex-wrap:wrap;gap:8px">
                <div>
                    <span class="id-mono">${claim.id}</span>
                    <span style="margin-left:10px;font-weight:600">${claim.member.name}</span>
                </div>
                <div style="color:var(--text-muted);font-size:13px">Date of service: <strong>${claim.date_of_service}</strong></div>
            </div>
            <div style="margin-bottom:10px">
                <div style="font-size:12px;font-weight:600;color:var(--text-muted);margin-bottom:4px">DISPUTE REASON</div>
                <div>${d.reason}</div>
            </div>
            <div style="font-size:12px;color:var(--text-muted);margin-bottom:12px">
                Submitted: ${new Date(d.submitted_at).toLocaleString()}
            </div>
            <div class="form-group">
                <label for="reviewer-note-${claim.id}">Reviewer Note (optional)</label>
                <textarea id="reviewer-note-${claim.id}" class="form-control" rows="3"
                    placeholder="Notes from the reviewer…" style="resize:vertical"></textarea>
            </div>
            <div id="readjudicate-error-${claim.id}"></div>
            <div class="form-actions">
                <button id="readjudicate-btn-${claim.id}" class="btn btn-primary"
                    data-claim="${claim.id}">Trigger Re-adjudication</button>
            </div>
        </div>`;
}

function wireDisputeCard(claim) {
    const btn   = document.getElementById(`readjudicate-btn-${claim.id}`);
    const errEl = document.getElementById(`readjudicate-error-${claim.id}`);
    if (!btn) return;
    btn.addEventListener("click", async () => {
        const note = document.getElementById(`reviewer-note-${claim.id}`).value.trim() || null;
        btn.disabled = true;
        btn.textContent = "Processing…";
        try {
            await api.adjudicate(claim.id, note);
            await loadDisputes();
        } catch (err) {
            showError(errEl, err.message);
            btn.disabled = false;
            btn.textContent = "Trigger Re-adjudication";
        }
    });
}

// ── Init ─────────────────────────────────────────────────
loadPlans();
loadProviders();
populatePlanSelect();
loadMembers();
loadDisputes();
