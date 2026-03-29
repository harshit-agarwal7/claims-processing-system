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
let policyMemberId = null;

memberLookupBtn.addEventListener("click", async () => {
    const val = document.getElementById("policy-member-input").value.trim();
    if (!val) return;
    memberLookupResult.innerHTML = "";
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

// ── Init ─────────────────────────────────────────────────
loadPlans();
loadProviders();
populatePlanSelect();
